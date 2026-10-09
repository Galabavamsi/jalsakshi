"""Web-phone simulator (``/sim/*`` behind Cognito): the console keypad drives the same IVR engine
as a real call, and its answers are stored with ``captured_via = SIMULATOR``.

When the workflow runs with ``VOICE_PROVIDER=simulator`` it leaves each call *pending*; starting
a simulator call for that household (or operator) picks the pending call up, so the waiting
CheckInRun or TicketFlow task resumes when the call ends. Any other simulator call is a console
call: it is policy-checked here and refreshes the village's day status when it ends.
"""

from __future__ import annotations

from typing import Any

from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response

from jalsakshi.core.clock import today_ist
from jalsakshi.core.ids import new_id
from jalsakshi.core.models import CapturedVia, Household, Operator, Purpose, Ticket
from jalsakshi.handlers import config, residents, tickets
from jalsakshi.handlers.calls import (
    CallRecord,
    LoadedCall,
    find_pending,
    finish_call,
    household_decision,
    load_call,
    next_attempt,
    operator_decision,
    reported_households,
    save_call,
)
from jalsakshi.handlers.common import (
    ApiError,
    PolicyDeniedError,
    activity,
    count,
    entrypoint,
    install_error_handlers,
    json_body,
    json_response,
    record_denial,
)
from jalsakshi.handlers.config import VoiceProvider
from jalsakshi.store import Repository
from jalsakshi.voice import flow as ivr
from jalsakshi.voice.actions import Hangup
from jalsakshi.voice.adapters.simulator import (
    from_json,
    input_response,
    parse_start,
    start_response,
)

app = APIGatewayHttpResolver()
install_error_handlers(app)


@app.post("/sim/calls")
def start_call() -> Response:
    """Start (or pick up) a simulated call and return its first actions."""
    request = parse_start(json_body(app))
    repo = config.repository()
    if request.operator_id is not None:
        loaded = _operator_call(repo, request.operator_id)
    else:
        loaded = _household_call(repo, str(request.household_id), request.purpose)
    flow, actions = ivr.start(residents.with_language(repo, loaded.record.flow))
    record = loaded.record.model_copy(update={"flow": flow})
    save_call(repo, record)
    audio = config.settings().audio_base_url
    return json_response(200, start_response(record.call_id, actions, audio))


@app.post("/sim/calls/<call_id>/input")
def call_input(call_id: str) -> Response:
    """Apply one keypad result (or timeout) and return the next actions."""
    sim_input = from_json(json_body(app))
    repo = config.repository()
    loaded = load_call(repo, call_id)
    if loaded is None:
        raise ApiError(404, "not_found", f"call {call_id!r} not found or expired")
    audio = config.settings().audio_base_url
    if loaded.record.finished or loaded.record.flow.done:
        return json_response(200, input_response([Hangup()], True, audio))
    flow, actions, done = ivr.on_input(
        loaded.record.flow, sim_input.digits, timeout=sim_input.timeout
    )
    record = loaded.record.model_copy(update={"flow": flow})
    step = {"digits": sim_input.digits, "timeout": sim_input.timeout}
    repo.record_call_step(call_id, f"turn-{flow.turn:03d}", step)
    save_call(repo, record)
    if done:
        finish_call(repo, LoadedCall(record, loaded.task_token), CapturedVia.SIMULATOR)
    return json_response(200, input_response(actions, done, audio))


@entrypoint
def handler(event: Any, context: Any) -> Any:
    """Lambda entrypoint for every ``/sim/*`` route."""
    return app.resolve(event, context)


def _household_call(repo: Repository, household_id: str, purpose: Purpose) -> LoadedCall:
    household = _find_household(repo, household_id)
    pending = find_pending(repo, household.id, purpose)
    if pending is not None:
        return pending
    decision = household_decision(repo, household, purpose)
    if not decision.allowed:
        record_denial(decision, household.village_id, f"simulator call to {household.id}")
        raise PolicyDeniedError(decision)
    day = today_ist(config.now())
    open_ticket = repo.get_open_ticket(household.village_id)
    flow = ivr.FlowSession(
        call_id=new_id("sim"),
        purpose=purpose,
        village_id=household.village_id,
        household_id=household.id,
        ticket_id=open_ticket.id if purpose is Purpose.VERIFY and open_ticket else None,
        access=household.access,
    )
    attempt = next_attempt(repo, household.village_id, day, purpose, household.id)
    record = CallRecord(
        flow=flow, provider=VoiceProvider.SIMULATOR, day=day, attempt=attempt, origin="console"
    )
    _announce(household.village_id, f"household {household.id}", purpose)
    return LoadedCall(record, None)


def _operator_call(repo: Repository, operator_id: str) -> LoadedCall:
    operator = repo.get_operator(operator_id)
    if operator is None:
        raise ApiError(404, "not_found", f"operator {operator_id!r} not found")
    pending = find_pending(repo, operator.id, Purpose.OPERATOR)
    if pending is not None:
        return pending
    ticket = _open_ticket_for(repo, operator)
    decision = operator_decision(operator, ticket.village_id)
    if not decision.allowed:
        record_denial(decision, ticket.village_id, f"simulator call to {operator.id}")
        raise PolicyDeniedError(decision)
    status = repo.get_day_status(ticket.village_id, tickets.ticket_day(ticket))
    flow = ivr.FlowSession(
        call_id=new_id("sim"),
        purpose=Purpose.OPERATOR,
        village_id=ticket.village_id,
        operator_id=operator.id,
        ticket_id=ticket.id,
        ticket_reason=ticket.reason,
        reported_households=reported_households(status, ticket.reason),
    )
    day = today_ist(config.now())
    record = CallRecord(flow=flow, provider=VoiceProvider.SIMULATOR, day=day, origin="console")
    _announce(ticket.village_id, f"operator {operator.id}", Purpose.OPERATOR)
    return LoadedCall(record, None)


def _find_household(repo: Repository, household_id: str) -> Household:
    """Households are keyed under their village, so look in each village (small scale)."""
    for village in repo.list_villages():
        household = repo.get_household(village.id, household_id)
        if household is not None:
            return household
    raise ApiError(404, "not_found", f"household {household_id!r} not found")


def _open_ticket_for(repo: Repository, operator: Operator) -> Ticket:
    for village_id in operator.village_ids:
        ticket = repo.get_open_ticket(village_id)
        if ticket is not None:
            return ticket
    raise ApiError(409, "no_open_ticket", "no open ticket in this operator's villages")


def _announce(village_id: str, who: str, purpose: Purpose) -> None:
    count("CallsPlaced")
    activity(
        "call",
        village_id,
        f"Simulator call to {who} ({purpose}), labelled simulated",
        f"सिम्युलेटर कॉल: {who} ({purpose}), सिम्युलेटेड",
    )
