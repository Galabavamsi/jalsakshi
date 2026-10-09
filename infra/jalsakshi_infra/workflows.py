"""Step Functions definitions for CheckInRun and TicketFlow (docs/ARCHITECTURE.md §6).

CheckInRun:  LoadRoster -> Map(households: PolicyCheck -> PlaceCall [waitForTaskToken, 10 min]
             -> catch => MarkUnreachable -> one retry after 30 min) -> ReconcileDay
             -> Choice -> StartTicketFlow
TicketFlow:  OpenTicket -> NotifyOperator [waitForTaskToken, heartbeat 48 h => Escalate]
             -> StartVerification -> Map(verify households) -> EvaluateVerification
             -> Choice(CLOSED_VERIFIED | REOPENED => notify again | PENDING => retry round,
             then Escalate [waitForTaskToken] -> verify again)

Every Lambda task retries transient Lambda errors with full jitter. Tasks are idempotent, so a
retry never dials twice or writes a second check-in.
"""

from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from jalsakshi_infra.settings import StageSettings

LAMBDA_TRANSIENT = [
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
]


@dataclass(frozen=True, slots=True)
class TaskFunctions:
    """One Lambda per task in ``jalsakshi.handlers.sfn_tasks``."""

    load_roster: lambda_.IFunction
    policy_check_call: lambda_.IFunction
    place_call: lambda_.IFunction
    mark_unreachable: lambda_.IFunction
    reconcile_day: lambda_.IFunction
    open_ticket: lambda_.IFunction
    notify_operator: lambda_.IFunction
    start_verification: lambda_.IFunction
    evaluate_verification: lambda_.IFunction
    escalate: lambda_.IFunction


@dataclass(frozen=True, slots=True)
class Timing:
    """Waits and timeouts, from the stage settings."""

    call_timeout: cdk.Duration
    retry_wait: cdk.Duration
    escalation_heartbeat: cdk.Duration
    fix_timeout: cdk.Duration
    max_verify_rounds: int
    map_concurrency: int

    @classmethod
    def from_settings(cls, cfg: StageSettings) -> Timing:
        """Durations for this stage (demo stages may shorten the 48 h escalation)."""
        return cls(
            call_timeout=cdk.Duration.minutes(cfg.call_timeout_minutes),
            retry_wait=cdk.Duration.minutes(cfg.retry_wait_minutes),
            escalation_heartbeat=cdk.Duration.seconds(int(cfg.escalation_hours * 3600)),
            fix_timeout=cdk.Duration.days(cfg.fix_timeout_days),
            max_verify_rounds=cfg.max_verify_rounds,
            map_concurrency=cfg.map_concurrency,
        )


def invoke(
    scope: Construct,
    cid: str,
    fn: lambda_.IFunction,
    *,
    result_path: str,
    payload: sfn.TaskInput | None = None,
) -> tasks.LambdaInvoke:
    """A request-response Lambda task whose JSON result lands at ``result_path``."""
    task = tasks.LambdaInvoke(
        scope,
        cid,
        lambda_function=fn,
        payload=payload,
        payload_response_only=True,
        result_path=result_path,
        retry_on_service_exceptions=False,
    )
    return _with_retry(task)


def wait_for_token(
    scope: Construct,
    cid: str,
    fn: lambda_.IFunction,
    *,
    result_path: str,
    timeout: cdk.Duration,
    heartbeat: cdk.Duration | None = None,
) -> tasks.LambdaInvoke:
    """A callback task: the Lambda gets ``{task_token, input}`` and something resumes it later."""
    task = tasks.LambdaInvoke(
        scope,
        cid,
        lambda_function=fn,
        integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
        payload=sfn.TaskInput.from_object(
            {"task_token": sfn.JsonPath.task_token, "input": sfn.JsonPath.entire_payload}
        ),
        result_path=result_path,
        task_timeout=sfn.Timeout.duration(timeout),
        heartbeat_timeout=sfn.Timeout.duration(heartbeat) if heartbeat else None,
        retry_on_service_exceptions=False,
    )
    return _with_retry(task)


def _with_retry(task: tasks.LambdaInvoke) -> tasks.LambdaInvoke:
    task.add_retry(
        errors=LAMBDA_TRANSIENT,
        interval=cdk.Duration.seconds(2),
        max_attempts=4,
        backoff_rate=2,
        jitter_strategy=sfn.JitterType.FULL,
    )
    return task


def call_households(
    scope: Construct, cid: str, fns: TaskFunctions, timing: Timing, items_path: str
) -> sfn.Map:
    """Map over households: policy check, call and wait, one retry when unreachable."""
    ns = Construct(scope, f"{cid}Steps")
    check = invoke(ns, "PolicyCheck", fns.policy_check_call, result_path="$.policy")
    place = wait_for_token(
        ns, "PlaceCall", fns.place_call, result_path="$.call", timeout=timing.call_timeout
    )
    unreachable = invoke(ns, "MarkUnreachable", fns.mark_unreachable, result_path="$.call")
    place.add_catch(unreachable, errors=["States.ALL"], result_path="$.call_error")
    done = sfn.Succeed(ns, "CallDone")
    wait = sfn.Wait(ns, "WaitBeforeRetry", time=sfn.WaitTime.duration(timing.retry_wait))
    next_attempt = sfn.Pass(
        ns,
        "NextAttempt",
        parameters={
            "village_id.$": "$.village_id",
            "household_id.$": "$.household_id",
            "date.$": "$.date",
            "purpose.$": "$.purpose",
            "ticket_id.$": "$.ticket_id",
            "attempt.$": "States.MathAdd($.attempt, 1)",
            "retries_left": 0,
        },
    )
    answered = (
        sfn.Choice(ns, "Answered")
        .when(sfn.Condition.boolean_equals("$.call.answered", True), done)
        .when(sfn.Condition.number_greater_than("$.retries_left", 0), wait)
        .otherwise(done)
    )
    allowed = (
        sfn.Choice(ns, "Allowed")
        .when(sfn.Condition.boolean_equals("$.policy.allowed", True), place)
        .otherwise(sfn.Succeed(ns, "CallSkipped"))
    )
    check.next(allowed)
    place.next(answered)
    unreachable.next(answered)
    wait.next(next_attempt)
    next_attempt.next(check)
    households = sfn.Map(
        scope,
        cid,
        items_path=items_path,
        max_concurrency=timing.map_concurrency,
        result_path=sfn.JsonPath.DISCARD,
    )
    households.item_processor(check)
    return households


def checkin_run_definition(
    scope: Construct, fns: TaskFunctions, timing: Timing, ticket_flow: sfn.IStateMachine
) -> sfn.IChainable:
    """CheckInRun: call today's households, reconcile, start a TicketFlow when needed."""
    roster = invoke(scope, "LoadRoster", fns.load_roster, result_path="$.roster")
    calls = call_households(scope, "CallHouseholds", fns, timing, "$.roster.households")
    reconcile = invoke(
        scope,
        "ReconcileDay",
        fns.reconcile_day,
        result_path="$.day",
        payload=sfn.TaskInput.from_object(
            {
                "village_id": sfn.JsonPath.string_at("$.roster.village_id"),
                "date": sfn.JsonPath.string_at("$.roster.date"),
            }
        ),
    )
    start_flow = tasks.StepFunctionsStartExecution(
        scope,
        "StartTicketFlow",
        state_machine=ticket_flow,
        integration_pattern=sfn.IntegrationPattern.REQUEST_RESPONSE,
        associate_with_parent=True,
        input=sfn.TaskInput.from_object(
            {
                "village_id": sfn.JsonPath.string_at("$.day.village_id"),
                "reason": sfn.JsonPath.string_at("$.day.ticket_reason"),
                "ticket_id": sfn.JsonPath.string_at("$.day.ticket_id"),
                "date": sfn.JsonPath.string_at("$.day.date"),
            }
        ),
        result_path=sfn.JsonPath.DISCARD,
    )
    start_flow.add_retry(
        errors=["StepFunctions.SdkClientException", "StepFunctions.ServiceException"],
        max_attempts=3,
        jitter_strategy=sfn.JitterType.FULL,
    )
    needs_ticket = (
        sfn.Choice(scope, "NeedsTicket")
        .when(sfn.Condition.is_not_null("$.day.ticket_reason"), start_flow)
        .otherwise(sfn.Succeed(scope, "DayRecorded"))
    )
    start_flow.next(sfn.Succeed(scope, "TicketFlowStarted"))
    return roster.next(calls).next(reconcile).next(needs_ticket)


def ticket_flow_definition(scope: Construct, fns: TaskFunctions, timing: Timing) -> sfn.IChainable:
    """TicketFlow: open, notify, wait for a fix, verify with households, close or loop."""
    open_ticket = invoke(scope, "OpenTicket", fns.open_ticket, result_path="$.open")
    init = sfn.Pass(
        scope, "InitVerify", result=sfn.Result.from_object({"round": 0}), result_path="$.verify"
    )
    notify = wait_for_token(
        scope,
        "NotifyOperator",
        fns.notify_operator,
        result_path="$.fix",
        timeout=timing.fix_timeout,
        heartbeat=timing.escalation_heartbeat,
    )
    escalate = wait_for_token(
        scope, "Escalate", fns.escalate, result_path="$.fix", timeout=timing.fix_timeout
    )
    notify.add_catch(escalate, errors=["States.ALL"], result_path="$.escalation_cause")
    escalate.add_catch(
        sfn.Fail(scope, "NoFixReported", error="NoFix", cause="No fix reported after escalation"),
        errors=["States.ALL"],
    )
    start_verify = invoke(
        scope, "StartVerification", fns.start_verification, result_path="$.verify"
    )
    verify_calls = call_households(scope, "CallBackHouseholds", fns, timing, "$.verify.households")
    evaluate = invoke(
        scope, "EvaluateVerification", fns.evaluate_verification, result_path="$.result"
    )
    next_round = sfn.Wait(
        scope, "WaitBeforeNextRound", time=sfn.WaitTime.duration(timing.retry_wait)
    )
    pending_retry = sfn.Condition.and_(
        sfn.Condition.string_equals("$.result.outcome", "PENDING"),
        sfn.Condition.number_less_than("$.result.round", timing.max_verify_rounds),
    )
    decide = (
        sfn.Choice(scope, "VerifyOutcome")
        .when(
            sfn.Condition.string_equals("$.result.outcome", "CLOSED_VERIFIED"),
            sfn.Succeed(scope, "ClosedVerified"),
        )
        .when(sfn.Condition.string_equals("$.result.outcome", "REOPENED"), notify)
        .when(pending_retry, next_round)
        .otherwise(escalate)
    )
    skip = (
        sfn.Choice(scope, "AlreadyClosed")
        .when(
            sfn.Condition.boolean_equals("$.verify.skip", True),
            sfn.Succeed(scope, "ClosedElsewhere"),
        )
        .otherwise(verify_calls)
    )
    opened = (
        sfn.Choice(scope, "Opened")
        .when(sfn.Condition.boolean_equals("$.open.opened", True), init)
        .otherwise(sfn.Succeed(scope, "TicketAlreadyOpen"))
    )
    # A resident who reported by missed call is still on the line for a few seconds; wait
    # before calling the operator so the two calls never collide on a shared phone.
    settle = sfn.Wait(
        scope, "SettleBeforeNotify", time=sfn.WaitTime.duration(cdk.Duration.seconds(45))
    )
    init.next(settle)
    settle.next(notify)
    notify.next(start_verify)
    escalate.next(start_verify)
    start_verify.next(skip)
    verify_calls.next(evaluate)
    evaluate.next(decide)
    next_round.next(start_verify)
    return open_ticket.next(opened)
