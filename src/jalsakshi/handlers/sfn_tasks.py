"""Step Functions task Lambdas for CheckInRun and TicketFlow (ARCHITECTURE.md §6).

Each task takes the state as JSON and returns JSON. Tasks that wait for a callback
(``place_call``, ``notify_operator``, ``escalate``) are invoked with
``{"task_token": ..., "input": <state>}``; the workflow resumes when a call ends or a fix is
reported (``SendTaskSuccess``). Every task is safe to retry: call ids are deterministic, check-ins
and tickets use conditional writes, and transitions go through the state machine in core.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from jalsakshi.core import verify as core_verify
from jalsakshi.core.clock import today_ist
from jalsakshi.core.models import (
    CallOutcome,
    CapturedVia,
    CheckIn,
    DayStatusValue,
    OperatorRole,
    Purpose,
    Ticket,
    TicketReason,
    TicketState,
    Village,
)
from jalsakshi.core.reconcile import is_answered
from jalsakshi.core.tickets import Denied, TicketEventKind, closing_quorum, new_ticket
from jalsakshi.core.verify import VerifyOutcome
from jalsakshi.handlers import config, residents, sfn, tickets
from jalsakshi.handlers.calls import (
    CallRecord,
    clear_pending,
    household_call_id,
    household_decision,
    load_call,
    mark_pending,
    operator_call_id,
    operator_decision,
    refresh_day,
    reported_households,
    save_call,
)
from jalsakshi.handlers.common import activity, count, entrypoint, logger, record_denial
from jalsakshi.handlers.config import VoiceProvider
from jalsakshi.handlers.dialer import DialError, dial
from jalsakshi.policy import can_close_verified
from jalsakshi.store import Repository
from jalsakshi.voice.flow import FlowSession

SYSTEM_ACTOR: Final = "system:ticket-flow"
TICKET_SOURCES: Final = frozenset({DayStatusValue.NO_SUPPLY, DayStatusValue.DIRTY})


class TaskError(RuntimeError):
    """Input or state the workflow cannot continue from; fails the execution visibly."""


class CallItem(BaseModel):
    """One household to call: an item of the workflows' Map state."""

    model_config = ConfigDict(extra="ignore")

    village_id: str
    household_id: str
    date: date
    purpose: Purpose
    attempt: int = Field(default=1, ge=1)
    retries_left: int = Field(default=1, ge=0)
    ticket_id: str | None = None


# --- CheckInRun -----------------------------------------------------------------------------------


@entrypoint
def load_roster(event: Any, context: Any) -> dict[str, Any]:
    """Active households of the village to call today, each with its next attempt number."""
    payload, _ = _unwrap(event)
    repo = config.repository()
    village = _village(repo, str(payload.get("village_id", "")))
    purpose = Purpose(payload.get("purpose") or Purpose.DAILY)
    day = date.fromisoformat(payload["date"]) if payload.get("date") else _today()
    households = repo.list_households(village.id, active_only=True) if village.active else []
    attempts = _next_attempts(repo, village.id, day, purpose)
    items = [
        CallItem(
            village_id=village.id,
            household_id=h.id,
            date=day,
            purpose=purpose,
            attempt=attempts.get(h.id, 1),
        )
        for h in households
    ]
    activity(
        "checkin_run",
        village.id,
        f"Check-in run started for {village.name}: {len(items)} households",
        f"{village.name} में जाँच शुरू: {len(items)} घर",
    )
    return {
        "village_id": village.id,
        "date": day.isoformat(),
        "purpose": purpose.value,
        "quorum": village.quorum,
        "households": [item.model_dump(mode="json") for item in items],
    }


@entrypoint
def policy_check_call(event: Any, context: Any) -> dict[str, Any]:
    """Cedar ``PlaceCall`` check for one Map item (consent, withdrawal)."""
    payload, _ = _unwrap(event)
    item = CallItem.model_validate(payload)
    repo = config.repository()
    household = repo.get_household(item.village_id, item.household_id)
    if household is None:
        return {"allowed": False, "policy_id": "household-missing", "reason_en": "No household"}
    decision = household_decision(repo, household, item.purpose)
    if decision.allowed:
        return {"allowed": True, "policy_id": None, "reason_en": None, "reason_hi": None}
    record_denial(decision, item.village_id, f"call to household {item.household_id}")
    return {
        "allowed": False,
        "policy_id": decision.policy_ids[0],
        "reason_en": decision.reasons_en[0],
        "reason_hi": decision.reasons_hi[0],
    }


@entrypoint
def place_call(event: Any, context: Any) -> dict[str, Any]:
    """Start one household call and park the task token on it (waitForTaskToken)."""
    payload, token = _unwrap(event)
    if not token:
        raise TaskError("place_call must be invoked with a task token")
    item = CallItem.model_validate(payload)
    repo = config.repository()
    call_id = household_call_id(
        item.purpose, item.village_id, item.household_id, item.date, item.attempt
    )
    existing = load_call(repo, call_id)
    record = existing.record if existing else _new_household_call(repo, call_id, item)
    repo.set_task_token(call_id, token)
    if record.finished:
        sfn.send_task_success(token, _stored_result(repo, item, call_id))
        return {"call_id": call_id, "status": "finished"}
    if record.provider is VoiceProvider.SIMULATOR:
        if existing is None:
            mark_pending(repo, record)
            count("CallsPlaced")
            activity(
                "call",
                item.village_id,
                f"Call to household {item.household_id} is waiting in the console simulator",
                f"घर {item.household_id} की कॉल कंसोल सिम्युलेटर में प्रतीक्षा में है",
            )
        return {"call_id": call_id, "status": "pending"}
    if not repo.record_call_step(call_id, "dispatch", {"attempt": item.attempt}):
        return {"call_id": call_id, "status": "already_dispatched"}
    household = repo.get_household(item.village_id, item.household_id)
    if household is None:
        raise TaskError(f"household {item.household_id} disappeared")
    request_uuid = dial(record, household.phone_e164)
    save_call(repo, record.model_copy(update={"provider_call_uuid": request_uuid or None}))
    return {"call_id": call_id, "status": "dialled"}


@entrypoint
def mark_unreachable(event: Any, context: Any) -> dict[str, Any]:
    """The call timed out or failed: store UNREACHABLE for this attempt (unless it finished)."""
    payload, _ = _unwrap(event)
    item = CallItem.model_validate(payload)
    repo = config.repository()
    call_id = household_call_id(
        item.purpose, item.village_id, item.household_id, item.date, item.attempt
    )
    loaded = load_call(repo, call_id)
    simulated = loaded is not None and loaded.record.provider is VoiceProvider.SIMULATOR
    checkin = CheckIn(
        village_id=item.village_id,
        date=item.date,
        household_id=item.household_id,
        attempt=item.attempt,
        call_id=call_id,
        purpose=item.purpose,
        outcome=CallOutcome.UNREACHABLE,
        captured_via=CapturedVia.SIMULATOR if simulated else CapturedVia.DTMF,
        captured_at=config.now(),
    )
    if repo.put_checkin(checkin):
        count("CallsUnreachable")
        activity(
            "call",
            item.village_id,
            f"Household {item.household_id} unreachable (attempt {item.attempt})",
            f"घर {item.household_id} से संपर्क नहीं हुआ (प्रयास {item.attempt})",
        )
    if loaded is not None and not loaded.record.finished:
        save_call(repo, loaded.record.model_copy(update={"finished": True}))
        clear_pending(repo, loaded.record)
    cause = payload.get("call_error") if isinstance(payload.get("call_error"), Mapping) else {}
    return {**_stored_result(repo, item, call_id), "cause": (cause or {}).get("Error")}


@entrypoint
def reconcile_day(event: Any, context: Any) -> dict[str, Any]:
    """Reconcile the village-day (rule r1) and say whether a ticket should open."""
    payload, _ = _unwrap(event)
    repo = config.repository()
    village = _village(repo, str(payload.get("village_id", "")))
    day = date.fromisoformat(str(payload["date"]))
    status = refresh_day(repo, village.id, day)
    if status is None:
        raise TaskError(f"village {village.id} vanished")
    already_open = repo.list_open_tickets(village.id)
    count("DayStatus", status=status.status.value)
    activity(
        "day_status",
        village.id,
        f"{village.name} {day}: {status.status} ({status.counts.answered} households answered)",
        f"{village.name} {day}: {status.status} ({status.counts.answered} घरों ने जवाब दिया)",
    )
    for point in status.points:
        if point.status not in TICKET_SOURCES:
            continue
        for ticket in already_open:
            if ticket.water_point_id == point.water_point_id:
                _note_still_bad(repo, ticket, day, point.status)
    checkins = repo.list_checkins(village.id, day)
    opened = residents.open_reconciled_tickets(repo, village, status, checkins)
    first, rest = (opened[0], opened[1:]) if opened else (None, [])
    for ticket in rest:
        residents.start_ticket_flow(ticket)
    return {
        "village_id": village.id,
        "date": day.isoformat(),
        "status": status.status.value,
        "counts": status.counts.model_dump(),
        "ticket_reason": first.reason.value if first else None,
        "ticket_id": first.id if first else None,
        "tickets_opened": [t.id for t in opened],
    }


# --- TicketFlow -----------------------------------------------------------------------------------


@entrypoint
def open_ticket(event: Any, context: Any) -> dict[str, Any]:
    """Open the repair ticket unless the village already has one (conditional write)."""
    payload, _ = _unwrap(event)
    repo = config.repository()
    village = _village(repo, str(payload.get("village_id", "")))
    reason = TicketReason(str(payload["reason"]))
    existing = (
        repo.get_ticket_by_id(str(payload["ticket_id"])) if payload.get("ticket_id") else None
    )
    if existing is not None:
        opened = existing.state is not TicketState.CLOSED_VERIFIED
        return {"opened": opened, "ticket_id": existing.id}
    ticket = new_ticket(
        village.id,
        reason,
        config.now(),
        ticket_id=payload.get("ticket_id"),
        number=repo.next_ticket_number(village.id),
    )
    stored = repo.open_ticket_if_none(ticket)
    if stored is None:
        current = repo.get_open_ticket(village.id, None, reason)
        return {"opened": False, "ticket_id": current.id if current else None}
    if stored.opened_at == ticket.opened_at:
        count("TicketsOpened")
        activity(
            "ticket",
            village.id,
            f"Ticket {stored.id} opened for {village.name}: {reason}",
            f"{village.name} के लिए शिकायत {stored.id} खुली: {reason}",
        )
    return {"opened": True, "ticket_id": stored.id}


@entrypoint
def notify_operator(event: Any, context: Any) -> dict[str, Any]:
    """Assign the ticket and call the Nal Jal Mitra; waits until a fix is reported."""
    payload, token = _unwrap(event)
    if not token:
        raise TaskError("notify_operator must be invoked with a task token")
    repo = config.repository()
    ticket_id = _ticket_id(payload)
    tickets.register_wait(repo, ticket_id, token, "operator_fix")
    ticket = tickets.load_ticket(repo, ticket_id)
    if ticket.state in (TicketState.CLOSED_VERIFIED, TicketState.OPERATOR_REPORTED_FIXED):
        sfn.send_task_success(token, {"fixed": True, "state": ticket.state.value})
        return {"ticket_id": ticket.id, "status": "already_fixed"}
    if ticket.state in (TicketState.OPEN, TicketState.REOPENED):
        result = tickets.apply_event(repo, ticket.id, TicketEventKind.NOTIFIED, SYSTEM_ACTOR)
        if isinstance(result, Denied):
            raise TaskError(result.reason)
        ticket = result
    _call_operator(repo, ticket)
    return {"ticket_id": ticket.id, "status": "waiting"}


@entrypoint
def start_verification(event: Any, context: Any) -> dict[str, Any]:
    """Begin (or repeat) a verification round and list the households to call back."""
    payload, _ = _unwrap(event)
    repo = config.repository()
    ticket = tickets.load_ticket(repo, _ticket_id(payload))
    previous = int((payload.get("verify") or {}).get("round") or 0)
    if ticket.state is TicketState.CLOSED_VERIFIED:
        return {"skip": True, "round": previous, "households": []}
    if ticket.state is TicketState.OPERATOR_REPORTED_FIXED:
        result = tickets.apply_event(repo, ticket.id, TicketEventKind.VERIFY_STARTED, SYSTEM_ACTOR)
        if isinstance(result, Denied):
            raise TaskError(result.reason)
        ticket, round_no = result, 1
    elif ticket.state is TicketState.VERIFYING:
        round_no = previous + 1
    else:
        raise TaskError(f"cannot verify a ticket in state {ticket.state}")
    since = tickets.verify_started_at(ticket)
    if since is None:
        raise TaskError("verification has no start event")
    items = _verify_items(repo, ticket, since, retry=round_no > 1)
    return {
        "skip": False,
        "round": round_no,
        "since": since.isoformat(),
        "date": _today().isoformat(),
        "households": [item.model_dump(mode="json") for item in items],
    }


@entrypoint
def evaluate_verification(event: Any, context: Any) -> dict[str, Any]:
    """Decide the round from the households' answers and apply VERIFIED_OK or VERIFY_FAILED."""
    payload, _ = _unwrap(event)
    repo = config.repository()
    ticket = tickets.load_ticket(repo, _ticket_id(payload))
    verify = payload.get("verify") or {}
    round_no = int(verify.get("round") or 1)
    if ticket.state is TicketState.CLOSED_VERIFIED:
        return {"outcome": VerifyOutcome.CLOSED_VERIFIED.value, "round": round_no}
    village = _village(repo, ticket.village_id)
    since = tickets.verify_started_at(ticket)
    checkins = tickets.verify_checkins(repo, ticket, _today())
    quorum = _ticket_quorum(repo, village, ticket)
    result = core_verify.evaluate_verification(checkins, quorum, since=since)
    outcome = result.outcome
    detail = {"yes": result.yes, "no": result.no, "unreachable": result.unreachable}
    if outcome is VerifyOutcome.CLOSED_VERIFIED:
        outcome = _close(repo, ticket, quorum, result.yes, detail)
    elif outcome is VerifyOutcome.REOPENED:
        failed = tickets.apply_event(
            repo, ticket.id, TicketEventKind.VERIFY_FAILED, "system:verify", detail
        )
        if isinstance(failed, Denied):
            raise TaskError(failed.reason)
    return {"outcome": outcome.value, "round": round_no, **detail}


@entrypoint
def escalate(event: Any, context: Any) -> dict[str, Any]:
    """Escalate to PHED (simulated) and wait for a fix; skip when a fix already arrived."""
    payload, token = _unwrap(event)
    if not token:
        raise TaskError("escalate must be invoked with a task token")
    repo = config.repository()
    ticket_id = _ticket_id(payload)
    tickets.register_wait(repo, ticket_id, token, "fix_after_escalation")
    ticket = tickets.load_ticket(repo, ticket_id)
    if ticket.state in (TicketState.CLOSED_VERIFIED, TicketState.OPERATOR_REPORTED_FIXED):
        sfn.send_task_success(token, {"fixed": True, "state": ticket.state.value})
        return {"ticket_id": ticket.id, "status": "already_fixed"}
    if ticket.state is not TicketState.ESCALATED:
        cause = payload.get("escalation_cause")
        detail = {
            "to": OperatorRole.PHED_AE_SIM.value,
            "simulated": True,
            "cause": cause.get("Error") if isinstance(cause, Mapping) else None,
        }
        result = tickets.apply_event(
            repo, ticket.id, TicketEventKind.ESCALATED, "system:escalation", detail
        )
        if isinstance(result, Denied):
            raise TaskError(result.reason)
    return {"ticket_id": ticket.id, "status": "waiting"}


# --- helpers --------------------------------------------------------------------------------------


def _unwrap(event: Any) -> tuple[dict[str, Any], str | None]:
    """The state, plus the task token for waitForTaskToken invocations."""
    if not isinstance(event, Mapping):
        raise TaskError("task input must be a JSON object")
    if "task_token" in event:
        state = event.get("input")
        return (dict(state) if isinstance(state, Mapping) else {}), str(event["task_token"])
    return dict(event), None


def _today() -> date:
    return today_ist(config.now())


def _village(repo: Repository, village_id: str) -> Village:
    village = repo.get_village(village_id) if village_id else None
    if village is None:
        raise TaskError(f"village {village_id!r} not found")
    return village


def _ticket_id(payload: Mapping[str, Any]) -> str:
    opened = payload.get("open")
    ticket_id = payload.get("ticket_id") or (
        opened.get("ticket_id") if isinstance(opened, Mapping) else None
    )
    if not ticket_id:
        raise TaskError("no ticket_id in the workflow state")
    return str(ticket_id)


def _next_attempts(
    repo: Repository, village_id: str, day: date, purpose: Purpose
) -> dict[str, int]:
    latest: dict[str, int] = {}
    for checkin in repo.list_checkins(village_id, day, purpose):
        latest[checkin.household_id] = max(latest.get(checkin.household_id, 0), checkin.attempt)
    return {household_id: attempt + 1 for household_id, attempt in latest.items()}


def _new_household_call(repo: Repository, call_id: str, item: CallItem) -> CallRecord:
    household = repo.get_household(item.village_id, item.household_id)
    flow = FlowSession(
        call_id=call_id,
        purpose=item.purpose,
        village_id=item.village_id,
        household_id=item.household_id,
        ticket_id=item.ticket_id,
        access=household.access if household else None,
    )
    record = CallRecord(
        flow=flow,
        provider=config.settings().voice_provider,
        day=item.date,
        attempt=item.attempt,
        origin="workflow",
    )
    save_call(repo, record)
    return record


def _stored_result(repo: Repository, item: CallItem, call_id: str) -> dict[str, Any]:
    """The workflow's view of an attempt: what was actually stored for it."""
    stored = next(
        (
            c
            for c in repo.list_checkins(item.village_id, item.date, item.purpose)
            if c.household_id == item.household_id and c.attempt == item.attempt
        ),
        None,
    )
    outcome = stored.outcome if stored else CallOutcome.UNREACHABLE
    answered = stored is not None and is_answered(stored)
    return {"call_id": call_id, "outcome": outcome.value, "answered": answered}


def _note_still_bad(repo: Repository, ticket: Ticket, day: date, status: DayStatusValue) -> None:
    detail = {"note": "day_still_bad", "date": day.isoformat(), "status": status.value}
    try:
        tickets.apply_event(repo, ticket.id, TicketEventKind.NOTE, "system:reconcile", detail)
    except Exception:
        logger.exception("could not note the still-bad day", extra={"ticket_id": ticket.id})


def _ticket_quorum(repo: Repository, village: Village, ticket: Ticket) -> int:
    """Households that must confirm before this ticket closes (§15.5)."""
    return closing_quorum(ticket, residents.point_quorum(repo, village, ticket.water_point_id))


def _not_mine(ticket: Ticket) -> list[str]:
    """Operators who said this complaint is not theirs (operator call key 5)."""
    return [
        str(e.detail.get("not_mine"))
        for e in ticket.events
        if e.kind == TicketEventKind.NOTE and e.detail.get("not_mine")
    ]


OPERATOR_CALL_STATES: Final = frozenset(
    {TicketState.ASSIGNED, TicketState.REOPENED, TicketState.ESCALATED}
)


def call_operator(repo: Repository, ticket: Ticket, requested_at: str = "") -> None:
    """Call the operator for a complaint that still waits for a fix (deferred night calls, or the
    secretary's "call again": ``requested_at`` makes that request its own call)."""
    if ticket.state in OPERATOR_CALL_STATES:
        _call_operator(repo, ticket, requested_at)


def _call_operator(repo: Repository, ticket: Ticket, requested_at: str = "") -> None:
    """Call whoever the complaint is routed to, with the summary (best effort: the wait goes on)."""
    operator = residents.route_operator(
        repo, ticket.village_id, ticket.water_point_id, skip=_not_mine(ticket)
    )
    if operator is None:
        logger.warning("nobody to route the complaint to", extra={"ticket_id": ticket.id})
        return
    decision = operator_decision(operator, ticket.village_id)
    if not decision.allowed:
        record_denial(decision, ticket.village_id, f"operator call for {ticket.id}")
        return
    notice = sum(1 for e in ticket.events if e.kind == TicketEventKind.NOTIFIED)
    stamp = "".join(ch for ch in requested_at[:19] if ch.isdigit())
    call_id = f"operator-{ticket.id}-c{stamp}" if stamp else operator_call_id(ticket.id, notice)
    existing = load_call(repo, call_id)
    record = existing.record if existing else _new_operator_call(repo, call_id, ticket, operator.id)
    if record.provider is VoiceProvider.SIMULATOR:
        mark_pending(repo, record)
        return
    if not repo.record_call_step(call_id, "dispatch", {"notice": notice}):
        return
    try:
        request_uuid = dial(record, operator.phone_e164)
    except (DialError, config.ConfigError, httpx.HTTPError) as exc:
        logger.warning("operator call failed", extra={"ticket_id": ticket.id, "error": str(exc)})
        activity(
            "call",
            ticket.village_id,
            f"Could not call the operator for ticket {ticket.id}; waiting for the console",
            f"शिकायत {ticket.id} के लिए मित्र को कॉल नहीं हो सकी; कंसोल से प्रतीक्षा",
        )
        return
    save_call(repo, record.model_copy(update={"provider_call_uuid": request_uuid or None}))


def _new_operator_call(
    repo: Repository, call_id: str, ticket: Ticket, operator_id: str
) -> CallRecord:
    status = repo.get_day_status(ticket.village_id, tickets.ticket_day(ticket))
    households = reported_households(status, ticket.reason, ticket.water_point_id)
    flow = FlowSession(
        call_id=call_id,
        purpose=Purpose.OPERATOR,
        village_id=ticket.village_id,
        operator_id=operator_id,
        ticket_id=ticket.id,
        ticket_reason=ticket.reason,
        reported_households=max(households, len(ticket.reporters)),
        ticket_number=ticket.number,
        water_point_name=residents.point_name(repo, ticket.village_id, ticket.water_point_id),
    )
    record = CallRecord(
        flow=flow, provider=config.settings().voice_provider, day=_today(), origin="workflow"
    )
    save_call(repo, record)
    return record


def _verify_items(
    repo: Repository, ticket: Ticket, since: datetime, *, retry: bool
) -> list[CallItem]:
    village = _village(repo, ticket.village_id)
    households = [h for h in repo.list_households(village.id, active_only=True) if h.consent_given]
    day = repo.list_checkins(village.id, tickets.ticket_day(ticket))
    quorum = _ticket_quorum(repo, village, ticket)
    targets = tickets.verify_targets(village, ticket, households, day, quorum)
    if retry:
        done = {
            c.household_id
            for c in tickets.verify_checkins(repo, ticket, _today())
            if c.captured_at >= since and is_answered(c)
        }
        targets = [h for h in targets if h.id not in done]
    day = _today()
    attempts = _next_attempts(repo, village.id, day, Purpose.VERIFY)
    return [
        CallItem(
            village_id=village.id,
            household_id=h.id,
            date=day,
            purpose=Purpose.VERIFY,
            attempt=attempts.get(h.id, 1),
            retries_left=0,
            ticket_id=ticket.id,
        )
        for h in targets
    ]


def _close(
    repo: Repository, ticket: Ticket, quorum: int, yes: int, detail: dict[str, int]
) -> VerifyOutcome:
    """Close as verified when Cedar agrees; otherwise the round stays pending."""
    decision = can_close_verified(ticket, quorum, yes)
    if not decision.allowed:
        record_denial(decision, ticket.village_id, f"closing ticket {ticket.id}")
        return VerifyOutcome.PENDING
    closed = tickets.apply_event(
        repo, ticket.id, TicketEventKind.VERIFIED_OK, "system:verify", detail
    )
    if isinstance(closed, Denied):
        current = tickets.load_ticket(repo, ticket.id)
        if current.state is TicketState.CLOSED_VERIFIED:
            return VerifyOutcome.CLOSED_VERIFIED
        raise TaskError(closed.reason)
    count("TicketsClosedVerified")
    return VerifyOutcome.CLOSED_VERIFIED
