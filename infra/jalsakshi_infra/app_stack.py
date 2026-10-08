"""AppStack: Lambdas (one shared code asset), the HTTP API, the two state machines, the
scheduler group, DLQs and least-privilege IAM (docs/ARCHITECTURE.md §6).

Physical names are fixed per stage (``jalsakshi-{stage}-...``), so policies can name state
machines by ARN string. That keeps the task Lambdas' roles free of references back to the
state machines that invoke them, which would otherwise be a CloudFormation cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from jalsakshi.agent.models import MODEL_CHAIN
from jalsakshi_infra.data_stack import DataStack
from jalsakshi_infra.settings import REGION, REPO_ROOT, StageSettings
from jalsakshi_infra.web_stack import WebStack
from jalsakshi_infra.workflows import (
    TaskFunctions,
    Timing,
    checkin_run_definition,
    ticket_flow_definition,
)

HANDLERS = "jalsakshi.handlers"
TASKS = (
    "load_roster",
    "policy_check_call",
    "place_call",
    "mark_unreachable",
    "reconcile_day",
    "open_ticket",
    "notify_operator",
    "start_verification",
    "evaluate_verification",
    "escalate",
)
DIALLING_TASKS = frozenset({"place_call", "notify_operator"})
TABLE_READ = ["dynamodb:GetItem", "dynamodb:Query"]
TABLE_WRITE = [
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem",
    "dynamodb:ConditionCheckItem",
]
TASK_RESPONSE = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"]


@dataclass(frozen=True, slots=True)
class Fn:
    """Sizing for one Lambda."""

    handler: str
    timeout_s: int = 30
    memory_mb: int = 512


class AppStack(cdk.Stack):
    """Compute, workflows and the public API for one stage."""

    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        cfg: StageSettings,
        data: DataStack,
        web: WebStack,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        self.cfg = cfg
        self.data = data
        self.code = self._code()
        self.checkin_arn = self._state_machine_arn("checkin-run")
        self.ticket_arn = self._state_machine_arn("ticket-flow")
        self.http_api = self._http_api(web)
        self.env_common = self._environment(data)
        self.functions: dict[str, lambda_.Function] = {}

        task_fns = TaskFunctions(**{name: self._task_function(name) for name in TASKS})
        timing = Timing.from_settings(cfg)
        self.ticket_flow = self._state_machine(
            "TicketFlow",
            "ticket-flow",
            ticket_flow_definition(Construct(self, "TicketFlowStates"), task_fns, timing),
            cdk.Duration.days(60),
        )
        self.checkin_run = self._state_machine(
            "CheckInRun",
            "checkin-run",
            checkin_run_definition(
                Construct(self, "CheckInRunStates"), task_fns, timing, self.ticket_flow
            ),
            cdk.Duration.hours(6),
        )
        self._api_functions(web)
        self.context_refresh = self._context_refresh()
        self.workflow_dlq = self._failed_executions_queue()
        self.scheduler_dlq = self._scheduler()
        cdk.CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
        cdk.CfnOutput(self, "CheckInRunArn", value=self.checkin_run.state_machine_arn)
        cdk.CfnOutput(self, "TicketFlowArn", value=self.ticket_flow.state_machine_arn)

    @property
    def queues(self) -> list[sqs.IQueue]:
        """Every dead-letter queue (alarmed in ObsStack)."""
        return [self.workflow_dlq, self.scheduler_dlq, self.context_dlq]

    # --- code and environment ---------------------------------------------------------------------

    def _code(self) -> lambda_.Code:
        if not self.cfg.lambda_asset_built:
            cdk.Annotations.of(self).add_warning_v2(
                "jalsakshi:lambda-asset-missing",
                f"{self.cfg.lambda_asset} is not built: run "
                "`uv run --no-sync python scripts/build_lambda.py` before deploying. "
                "Synth used src/ only (no dependencies), which is not deployable.",
            )
            return lambda_.Code.from_asset(
                str(REPO_ROOT / "src"), exclude=["**/__pycache__", "**/*.pyc"]
            )
        return lambda_.Code.from_asset(str(self.cfg.lambda_asset))

    def _environment(self, data: DataStack) -> dict[str, str]:
        cfg = self.cfg
        return {
            "JALSAKSHI_STAGE": cfg.stage,
            "JALSAKSHI_REGION": REGION,
            "JALSAKSHI_TABLE": data.table.table_name,
            "JALSAKSHI_EVIDENCE_BUCKET": data.evidence_bucket.bucket_name,
            "JALSAKSHI_AUDIO_BASE_URL": data.audio_base_url,
            "JALSAKSHI_API_URL": self.http_api.api_endpoint,
            "JALSAKSHI_CHECKIN_SFN_ARN": self.checkin_arn,
            "JALSAKSHI_TICKET_SFN_ARN": self.ticket_arn,
            "JALSAKSHI_PROMPTS_PATH": "/var/task/prompts/hi.yaml",
            "JALSAKSHI_BRIEF_USE_AGENT": "true" if cfg.brief_use_agent else "false",
            "JALSAKSHI_IVR_ALLOWED_CIDRS": cfg.ivr_allowed_cidrs,
            "VOICE_PROVIDER": cfg.voice_provider,
            "POWERTOOLS_SERVICE_NAME": "jalsakshi",
            "POWERTOOLS_METRICS_NAMESPACE": "JalSakshi",
            "POWERTOOLS_LOG_LEVEL": "INFO",
        }

    def _function(self, cid: str, spec: Fn, *, write: bool = True) -> lambda_.Function:
        slug = _kebab(cid)
        log_group = logs.LogGroup(
            self,
            f"{cid}Logs",
            log_group_name=f"/aws/lambda/{self.cfg.name(slug)}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        fn = lambda_.Function(
            self,
            cid,
            function_name=self.cfg.name(slug),
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            code=self.code,
            handler=spec.handler,
            timeout=cdk.Duration.seconds(spec.timeout_s),
            memory_size=spec.memory_mb,
            environment=self.env_common,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=log_group,
        )
        self._grant_table(fn, write=write)
        self.functions[cid] = fn
        return fn

    def _task_function(self, task: str) -> lambda_.Function:
        cid = "Task" + "".join(part.title() for part in task.split("_"))
        fn = self._function(cid, Fn(f"{HANDLERS}.sfn_tasks.{task}"))
        if task in DIALLING_TASKS:
            self._grant_secrets(fn)
        if task in {"place_call", "notify_operator", "escalate"}:
            self._grant_task_response(fn)
        return fn

    def _api_functions(self, web: WebStack) -> None:
        api_fn = self._function("Api", Fn(f"{HANDLERS}.api.handler", 30, 1024))
        sim_fn = self._function("Sim", Fn(f"{HANDLERS}.sim.handler", 15))
        ivr_fn = self._function("Ivr", Fn(f"{HANDLERS}.ivr_vobiz.handler", 15))
        self.data.evidence_bucket.grant_read(api_fn, "context/*")
        api_fn.add_to_role_policy(
            iam.PolicyStatement(actions=["states:StartExecution"], resources=[self.checkin_arn])
        )
        api_fn.add_to_role_policy(self._bedrock_statement())
        for fn in (api_fn, sim_fn, ivr_fn):
            self._grant_task_response(fn)
        self._grant_secrets(ivr_fn)
        authorizer = authorizers.HttpUserPoolAuthorizer(
            "CognitoAuthorizer",
            web.user_pool,
            user_pool_clients=[web.client],
            identity_source=["$request.header.Authorization"],
        )
        get_post = [apigw.HttpMethod.GET, apigw.HttpMethod.POST]
        routes = [
            ("/api/{proxy+}", get_post, api_fn, authorizer),
            ("/sim/{proxy+}", [apigw.HttpMethod.POST], sim_fn, authorizer),
            ("/ivr/vobiz/{token}/{action}", [apigw.HttpMethod.POST], ivr_fn, None),
        ]
        for path, methods, fn, auth in routes:
            self.http_api.add_routes(
                path=path,
                methods=methods,
                integration=integrations.HttpLambdaIntegration(f"{fn.node.id}Integration", fn),
                authorizer=auth,
            )

    # --- API --------------------------------------------------------------------------------------

    def _http_api(self, web: WebStack) -> apigw.HttpApi:
        api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=self.cfg.name("api"),
            create_default_stage=False,
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=list(
                    dict.fromkeys([web.web_url, web.cdn_url, *self.cfg.local_origins])
                ),
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["authorization", "content-type"],
                max_age=cdk.Duration.hours(1),
            ),
        )
        stage = api.add_stage(
            "DefaultStage",
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=50, burst_limit=100),
        )
        access_logs = logs.LogGroup(
            self,
            "ApiAccessLogs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        cfn_stage = stage.node.default_child
        assert isinstance(cfn_stage, apigw.CfnStage)
        # routeKey, not path: the IVR path carries the secret token.
        cfn_stage.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(
            destination_arn=access_logs.log_group_arn,
            format=(
                '{"requestId":"$context.requestId","ip":"$context.identity.sourceIp",'
                '"time":"$context.requestTime","route":"$context.routeKey",'
                '"status":"$context.status","latencyMs":"$context.responseLatency",'
                '"error":"$context.integrationErrorMessage"}'
            ),
        )
        return api

    # --- workflows --------------------------------------------------------------------------------

    def _state_machine(
        self, cid: str, slug: str, definition: sfn.IChainable, timeout: cdk.Duration
    ) -> sfn.StateMachine:
        log_group = logs.LogGroup(
            self,
            f"{cid}Logs",
            log_group_name=f"/aws/vendedlogs/states/{self.cfg.name(slug)}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        return sfn.StateMachine(
            self,
            cid,
            state_machine_name=self.cfg.name(slug),
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=timeout,
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=log_group, level=sfn.LogLevel.ERROR, include_execution_data=False
            ),
        )

    def _state_machine_arn(self, slug: str) -> str:
        return self.format_arn(
            service="states",
            resource="stateMachine",
            resource_name=self.cfg.name(slug),
            arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
        )

    def _failed_executions_queue(self) -> sqs.Queue:
        """Failed, timed-out or aborted executions land here (alarmed: DLQ > 0)."""
        queue = self._queue("WorkflowFailures")
        events.Rule(
            self,
            "WorkflowFailed",
            description="JalSakshi workflow executions that did not succeed",
            event_pattern=events.EventPattern(
                source=["aws.states"],
                detail_type=["Step Functions Execution Status Change"],
                detail={
                    "status": ["FAILED", "TIMED_OUT", "ABORTED"],
                    "stateMachineArn": [
                        self.checkin_run.state_machine_arn,
                        self.ticket_flow.state_machine_arn,
                    ],
                },
            ),
            targets=[targets.SqsQueue(queue)],
        )
        return queue

    def _scheduler(self) -> sqs.Queue:
        """Schedule group + role for per-village check-in schedules (created by the seed)."""
        dlq = self._queue("SchedulerDlq")
        group = scheduler.CfnScheduleGroup(self, "ScheduleGroup", name=self.cfg.name("checkins"))
        role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal(
                "scheduler.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
            description="EventBridge Scheduler starts CheckInRun for each village",
        )
        self.checkin_run.grant_start_execution(role)
        dlq.grant_send_messages(role)
        cdk.CfnOutput(self, "ScheduleGroupName", value=str(group.name))
        cdk.CfnOutput(self, "SchedulerRoleArn", value=role.role_arn)
        cdk.CfnOutput(self, "SchedulerDlqArn", value=dlq.queue_arn)
        return dlq

    def _context_refresh(self) -> lambda_.Function:
        """Daily public-data refresh (06:00 IST) into the evidence bucket's context/ prefix."""
        self.context_dlq = self._queue("ContextRefreshDlq")
        fn = self._function("ContextRefresh", Fn(f"{HANDLERS}.context.refresh", 600), write=False)
        self.data.evidence_bucket.grant_put(fn, "context/*")
        fn.configure_async_invoke(retry_attempts=1)
        events.Rule(
            self,
            "ContextRefreshDaily",
            schedule=events.Schedule.cron(minute="30", hour="0"),
            targets=[
                targets.LambdaFunction(
                    fn,
                    dead_letter_queue=self.context_dlq,
                    retry_attempts=2,
                    max_event_age=cdk.Duration.hours(2),
                )
            ],
        )
        return fn

    # --- IAM --------------------------------------------------------------------------------------

    def _grant_table(self, fn: lambda_.Function, *, write: bool) -> None:
        table = self.data.table
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=TABLE_READ, resources=[table.table_arn, f"{table.table_arn}/index/*"]
            )
        )
        if write:
            fn.add_to_role_policy(
                iam.PolicyStatement(actions=TABLE_WRITE, resources=[table.table_arn])
            )

    def _grant_secrets(self, fn: lambda_.Function) -> None:
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    self.format_arn(
                        service="ssm",
                        resource="parameter",
                        resource_name=f"jalsakshi/{self.cfg.stage}/*",
                    )
                ],
            )
        )

    def _grant_task_response(self, fn: lambda_.Function) -> None:
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=TASK_RESPONSE, resources=[self.checkin_arn, self.ticket_arn]
            )
        )

    def _bedrock_statement(self) -> iam.PolicyStatement:
        """Invoke the brief's model chain through its inference profiles (§6, §10)."""
        resources: list[str] = []
        for profile in MODEL_CHAIN:
            model = profile.split(".", 1)[1]
            resources += [
                f"arn:aws:bedrock:{REGION}:{self.account}:inference-profile/{profile}",
                f"arn:aws:bedrock:*::foundation-model/{model}",
                f"arn:aws:bedrock:::foundation-model/{model}",
            ]
        return iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=resources,
        )

    def _queue(self, cid: str) -> sqs.Queue:
        return sqs.Queue(
            self,
            cid,
            queue_name=self.cfg.name(_kebab(cid)),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            retention_period=cdk.Duration.days(14),
        )


def _kebab(name: str) -> str:
    """``TaskPlaceCall`` -> ``task-place-call``."""
    out = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            out.append("-")
        out.append(char.lower())
    return "".join(out)
