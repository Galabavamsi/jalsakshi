"""Call sessions shared by the simulator, the Vobiz webhooks and the Step Functions tasks.

``CALL#{call_id}`` holds a ``CallRecord``: the voice engine's ``FlowSession`` plus where its
answers go (village-day and attempt). Finishing a call writes the CheckIn once (conditional
put), resumes the waiting workflow task and updates the console feed, so duplicate webhooks
and Lambda retries are harmless.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

from pydantic import BaseModel, Field

from jalsakshi.core.clock import today_ist
from jalsakshi.core.models import (
    CallOutcome,
    CapturedVia,
    CheckIn,
    Consent,
    DayStatus,
    Household,
    Operator,
    Purpose,
    TicketReason,
    WaterAnswer,
)
from jalsakshi.core.reconcile import reconcile_day
from jalsakshi.core.tickets import Denied
from jalsakshi.handlers import config, sfn, tickets
from jalsakshi.handlers.common import activity, count, logger
from jalsakshi.handlers.config import VoiceProvider
from jalsakshi.policy import Decision, can_place_call, ist_hour
from jalsakshi.store import Repository
from jalsakshi.voice.flow import FlowSession, result_to_checkin_fields, result_to_operator

PENDING_TTL_DAYS: Final = 1
REACHED: Final = frozenset({CallOutcome.ANSWERED, CallOutcome.DECLINED})
_WATER_HI: Final = {WaterAnswer.YES: "हाँ", WaterAnswer.NO: "नहीं", WaterAnswer.PARTIAL: "थोड़ा"}
_PURPOSE_HI: Final = {Purpose.DAILY: "रोज़ की", Purpose.VERIFY: "पुष्टि की"}


class CallRecord(BaseModel):
    """What ``CALL#{call_id}`` stores: the IVR state and where its answers belong."""

    flow: FlowSession
    provider: VoiceProvider
    day: date
    attempt: int = Field(default=1, ge=1)
    origin: Literal["workflow", "console"] = "console"
    finished: bool = False
    provider_call_uuid: str | None = None

    @property
    def call_id(self) -> str:
        """The engine's call id (also the CheckIn's call_id)."""
        return self.flow.call_id

    @property
    def subject_id(self) -> str:
        """The household or operator being called."""
        return self.flow.household_id or self.flow.operator_id or ""


@dataclass(frozen=True, slots=True)
class LoadedCall:
    """A stored call plus the Step Functions task token waiting on it (if any)."""

    record: CallRecord
    task_token: str | None


def household_call_id(
    purpose: Purpose, village_id: str, household_id: str, day: date, attempt: int
) -> str:
    """Deterministic id for a workflow call, so a retried Lambda never dials twice."""
    return f"{purpose.value.lower()}-{village_id}-{household_id}-{day:%Y%m%d}-a{attempt}"


def operator_call_id(ticket_id: str, notice: int) -> str:
    """Deterministic id for the operator call of one notification of a ticket."""
    return f"operator-{ticket_id}-n{notice}"


def save_call(repo: Repository, record: CallRecord) -> None:
    """Create or update the call session (the task token is kept)."""
    repo.put_call_session(record.call_id, record.model_dump(mode="json"))


def load_call(repo: Repository, call_id: str) -> LoadedCall | None:
    """The stored call, or None (unknown, expired, or not a call record)."""
    session = repo.get_call_session(call_id)
    if session is None or "flow" not in session.data:
        return None
    return LoadedCall(CallRecord.model_validate(session.data), session.task_token)


def next_attempt(
    repo: Repository, village_id: str, day: date, purpose: Purpose, household_id: str
) -> int:
    """One more than the highest attempt stored for this household, day and purpose."""
    attempts = [
        c.attempt
        for c in repo.list_checkins(village_id, day, purpose)
        if c.household_id == household_id
    ]
    return max(attempts, default=0) + 1


def reached_today(repo: Repository, village_id: str, day: date, household_id: str) -> int:
    """DAILY calls that reached the household today (unreachable attempts do not count)."""
    return sum(
        1
        for c in repo.list_checkins(village_id, day, Purpose.DAILY)
        if c.household_id == household_id and c.outcome in REACHED
    )


def household_decision(repo: Repository, household: Household, purpose: Purpose) -> Decision:
    """Cedar ``PlaceCall`` check for calling this household now."""
    now = config.now()
    calls = 0
    if purpose is Purpose.DAILY:
        calls = reached_today(repo, household.village_id, today_ist(now), household.id)
    return can_place_call(household, purpose, ist_hour(now), calls)


def operator_decision(operator: Operator, village_id: str) -> Decision:
    """Cedar ``PlaceCall`` check for an operator call (calling hours apply to everyone).

    Operators agree to be called when they take the role, so the role itself is the consent.
    """
    consent = Consent(given_at=config.now(), channel="in_person", evidence_ref="operator-role")
    stand_in = Household(
        id=operator.id, village_id=village_id, phone_e164=operator.phone_e164, consent=consent
    )
    return can_place_call(stand_in, Purpose.OPERATOR, ist_hour(config.now()), 0)


# --- simulator hand-off -----------------------------------------------------------------------


def pending_key(subject_id: str) -> str:
    """Session id pointing at a workflow call that waits for the console simulator."""
    return f"pending-{subject_id}"


def mark_pending(repo: Repository, record: CallRecord) -> None:
    """Let the console's simulator pick up this call for its household or operator."""
    data = {"call_id": record.call_id, "purpose": record.flow.purpose.value}
    repo.put_call_session(pending_key(record.subject_id), data, ttl_days=PENDING_TTL_DAYS)


def find_pending(repo: Repository, subject_id: str, purpose: Purpose) -> LoadedCall | None:
    """The unfinished workflow call waiting for this subject and purpose, if any."""
    pointer = repo.get_call_session(pending_key(subject_id))
    call_id = pointer.data.get("call_id") if pointer else None
    if not call_id:
        return None
    loaded = load_call(repo, str(call_id))
    if loaded is None or loaded.record.finished or loaded.record.flow.purpose is not purpose:
        return None
    return loaded


def clear_pending(repo: Repository, record: CallRecord) -> None:
    """Remove the simulator pointer once its call is finished."""
    pointer = repo.get_call_session(pending_key(record.subject_id))
    if pointer and pointer.data.get("call_id") == record.call_id:
        repo.put_call_session(pending_key(record.subject_id), {"call_id": None}, ttl_days=1)


# --- finishing a call -------------------------------------------------------------------------


def finish_call(repo: Repository, loaded: LoadedCall, captured_via: CapturedVia) -> CallRecord:
    """Record the call's result once and resume whatever waits for it."""
    record = loaded.record
    if record.finished:
        return record
    if record.flow.purpose is Purpose.OPERATOR:
        _finish_operator(repo, record)
    else:
        _finish_household(repo, record, loaded.task_token, captured_via)
    done = record.model_copy(update={"finished": True})
    save_call(repo, done)
    return done


def refresh_day(repo: Repository, village_id: str, day: date) -> DayStatus | None:
    """Recompute and store a village-day's status from its DAILY check-ins."""
    village = repo.get_village(village_id)
    if village is None:
        return None
    checkins = repo.list_checkins(village_id, day, Purpose.DAILY)
    status = reconcile_day(checkins, village, day, config.now())
    repo.put_day_status(status)
    return status


def reported_households(status: DayStatus | None, reason: TicketReason) -> int:
    """How many households reported the ticket's problem that day (for the operator summary)."""
    if status is None:
        return 0
    return status.counts.dirty if reason is TicketReason.DIRTY else status.counts.no


def _finish_household(
    repo: Repository, record: CallRecord, token: str | None, captured_via: CapturedVia
) -> None:
    flow = record.flow
    if flow.village_id is None or flow.household_id is None:
        raise ValueError(f"call {record.call_id} has no household")
    fields = result_to_checkin_fields(flow)
    checkin = CheckIn(
        village_id=flow.village_id,
        date=record.day,
        household_id=flow.household_id,
        attempt=record.attempt,
        call_id=record.call_id,
        purpose=flow.purpose,
        captured_via=captured_via,
        captured_at=config.now(),
        **fields,
    )
    created = repo.put_checkin(checkin)
    if created:
        _report_checkin(checkin)
    if token:
        answered = checkin.outcome is CallOutcome.ANSWERED
        output = {"call_id": record.call_id, "outcome": checkin.outcome, "answered": answered}
        sfn.send_task_success(token, output)
    elif created and flow.purpose is Purpose.DAILY:
        refresh_day(repo, flow.village_id, record.day)
    clear_pending(repo, record)


def _report_checkin(checkin: CheckIn) -> None:
    purpose_hi = _PURPOSE_HI.get(checkin.purpose, "")
    if checkin.outcome is CallOutcome.ANSWERED and checkin.water is not None:
        count("CallsAnswered")
        activity(
            "call",
            checkin.village_id,
            f"Household {checkin.household_id} answered the {checkin.purpose} call "
            f"(water: {checkin.water})",
            f"घर {checkin.household_id} ने {purpose_hi} कॉल का जवाब दिया "
            f"(पानी: {_WATER_HI[checkin.water]})",
        )
        return
    count("CallsUnreachable")
    activity(
        "call",
        checkin.village_id,
        f"Household {checkin.household_id} gave no answer on the {checkin.purpose} call",
        f"घर {checkin.household_id} से {purpose_hi} कॉल पर जवाब नहीं मिला",
    )


def _finish_operator(repo: Repository, record: CallRecord) -> None:
    flow = record.flow
    fixed = result_to_operator(flow)["fixed"]
    if fixed is True and flow.ticket_id:
        actor = f"operator:{flow.operator_id}"
        result = tickets.report_fixed(repo, flow.ticket_id, actor, via="call")
        if isinstance(result, Denied):
            logger.warning("operator fix not applied", extra={"reason": result.reason})
        return
    activity(
        "call",
        flow.village_id,
        f"Operator {flow.operator_id} says ticket {flow.ticket_id} is not fixed yet",
        f"मित्र {flow.operator_id} ने कहा शिकायत {flow.ticket_id} अभी ठीक नहीं हुई",
    )
