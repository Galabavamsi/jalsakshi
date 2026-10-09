"""Call sessions shared by the simulator, the Vobiz webhooks and the Step Functions tasks.

``CALL#{call_id}`` holds a ``CallRecord``: the voice engine's ``FlowSession`` plus where its
answers go (village-day and attempt). Finishing a call writes the CheckIn once (conditional
put), resumes the waiting workflow task and updates the console feed, so duplicate webhooks
and Lambda retries are harmless.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from jalsakshi.core.clock import today_ist
from jalsakshi.core.models import (
    BlockerCode,
    CallOutcome,
    CapturedVia,
    CheckIn,
    Consent,
    ConsentStatus,
    DayStatus,
    Household,
    Operator,
    Purpose,
    TicketOrigin,
    TicketReason,
    WaterAnswer,
)
from jalsakshi.core.reconcile import reconcile_day
from jalsakshi.core.tickets import Denied
from jalsakshi.handlers import config, residents, sfn, tickets
from jalsakshi.handlers.common import activity, count, logger
from jalsakshi.handlers.config import VoiceProvider
from jalsakshi.policy import Decision, can_place_call, ist_hour
from jalsakshi.store import Repository
from jalsakshi.voice.flow import (
    FlowSession,
    FlowStep,
    ReportChoice,
    result_to_checkin_fields,
    result_to_operator,
    result_to_registration,
    stop_requested,
)

PENDING_TTL_DAYS: Final = 1
REACHED: Final = frozenset({CallOutcome.ANSWERED, CallOutcome.DECLINED})
_WATER_HI: Final = {WaterAnswer.YES: "हाँ", WaterAnswer.NO: "नहीं", WaterAnswer.PARTIAL: "थोड़ा"}
_PURPOSE_HI: Final = {
    Purpose.DAILY: "रोज़ की",
    Purpose.VERIFY: "पुष्टि की",
    Purpose.REPORT: "मिस्ड-कॉल शिकायत की",
}
_REPORT_REASONS: Final = {
    ReportChoice.NO_WATER: TicketReason.NO_SUPPLY,
    ReportChoice.DIRTY: TicketReason.DIRTY,
}
CALLBACK_WINDOW: Final = timedelta(hours=24)


class CallRecord(BaseModel):
    """What ``CALL#{call_id}`` stores: the IVR state and where its answers belong."""

    flow: FlowSession
    provider: VoiceProvider
    day: date
    attempt: int = Field(default=1, ge=1)
    origin: Literal["workflow", "console", "callback", "broadcast", "summary"] = "console"
    finished: bool = False
    provider_call_uuid: str | None = None
    caller_initiated: bool = False
    phone_e164: str | None = None
    broadcast_id: str | None = None
    ticket_number: int | None = None

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


def household_decision(
    repo: Repository,
    household: Household,
    purpose: Purpose,
    *,
    caller_initiated: bool = False,
    callbacks_today: int = 0,
) -> Decision:
    """Cedar ``PlaceCall`` check for calling this household now."""
    now = config.now()
    calls = 0
    if purpose is Purpose.DAILY:
        calls = reached_today(repo, household.village_id, today_ist(now), household.id)
    elif purpose is Purpose.REGISTER and not caller_initiated:
        calls = registered_today(repo, household.village_id, household.id)
    return can_place_call(
        household,
        purpose,
        ist_hour(now),
        calls,
        caller_initiated=caller_initiated,
        callbacks_today=callbacks_today,
        test_phone=household.phone_e164 in config.allowed_numbers(),
    )


def registered_today(repo: Repository, village_id: str, household_id: str) -> int:
    """Registration calls already logged in the consent ledger for this household today."""
    today = today_ist(config.now())
    return sum(
        1
        for e in repo.list_consent_events(village_id)
        if e.household_id == household_id and today_ist(e.at) == today
    )


def operator_decision(
    operator: Operator,
    village_id: str,
    *,
    caller_initiated: bool = False,
    callbacks_today: int = 0,
) -> Decision:
    """Cedar ``PlaceCall`` check for an operator call (calling hours apply to everyone).

    Operators agree to be called when they take the role, so the role itself is the consent.
    A call-back after the operator's own missed call is limited like anyone else's.
    """
    consent = Consent(given_at=config.now(), channel="in_person", evidence_ref="operator-role")
    stand_in = Household(
        id=operator.id, village_id=village_id, phone_e164=operator.phone_e164, consent=consent
    )
    return can_place_call(
        stand_in,
        Purpose.OPERATOR,
        ist_hour(config.now()),
        0,
        caller_initiated=caller_initiated,
        callbacks_today=callbacks_today,
        test_phone=operator.phone_e164 in config.allowed_numbers(),
    )


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
    match record.flow.purpose:
        case Purpose.OPERATOR:
            _finish_operator(repo, record)
        case Purpose.REGISTER:
            _finish_registration(repo, record)
        case Purpose.BROADCAST:
            _finish_broadcast(repo, record)
        case Purpose.SUMMARY:
            logger.info("summary call ended", extra={"call_id": record.call_id})
        case _:
            record = _finish_household(repo, record, loaded.task_token, captured_via)
    done = record.model_copy(update={"finished": True})
    save_call(repo, done)
    return done


def refresh_day(repo: Repository, village_id: str, day: date) -> DayStatus | None:
    """Recompute and store a village-day's status from its DAILY check-ins."""
    village = repo.get_village(village_id)
    if village is None:
        return None
    checkins = repo.list_checkins(village_id, day)
    points = repo.list_water_points(village_id)
    status = reconcile_day(checkins, village, day, config.now(), points)
    repo.put_day_status(status)
    return status


def reported_households(
    status: DayStatus | None, reason: TicketReason, water_point_id: str | None = None
) -> int:
    """How many households reported the ticket's problem that day (for the operator summary)."""
    if status is None:
        return 0
    counts = status.counts
    for point in status.points:
        if point.water_point_id == water_point_id:
            counts = point.counts
            break
    return counts.dirty if reason is TicketReason.DIRTY else counts.no


def _finish_household(
    repo: Repository, record: CallRecord, token: str | None, captured_via: CapturedVia
) -> CallRecord:
    flow = record.flow
    if flow.village_id is None or flow.household_id is None:
        raise ValueError(f"call {record.call_id} has no household")
    household = repo.get_household(flow.village_id, flow.household_id)
    if flow.purpose is Purpose.REPORT:
        record = _finish_report(repo, record, household, captured_via)
    else:
        fields = result_to_checkin_fields(flow)
        checkin = CheckIn(
            village_id=flow.village_id,
            date=record.day,
            household_id=flow.household_id,
            attempt=record.attempt,
            call_id=record.call_id,
            purpose=flow.purpose,
            water_point_id=household.water_point_id if household else None,
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
    if stop_requested(flow) and household is not None:
        residents.withdraw(repo, household, call_id=record.call_id)
    clear_pending(repo, record)
    return record


def _finish_report(
    repo: Repository, record: CallRecord, household: Household | None, captured_via: CapturedVia
) -> CallRecord:
    """A missed-call menu choice: store the answer, refresh the day, open or join a complaint."""
    flow = record.flow
    reason = _REPORT_REASONS.get(flow.answers.report) if flow.answers.report else None
    village = repo.get_village(flow.village_id or "")
    if reason is None or household is None or village is None:
        return record
    reports = repo.list_checkins(village.id, record.day, Purpose.REPORT)
    stored = next((c for c in reports if c.call_id == record.call_id), None)
    # A retried finish reuses this call's attempt, so the conditional put stays a no-op.
    attempt = (
        stored.attempt
        if stored
        else next_attempt(repo, village.id, record.day, Purpose.REPORT, household.id)
    )
    checkin = CheckIn(
        village_id=village.id,
        date=record.day,
        household_id=household.id,
        attempt=attempt,
        call_id=record.call_id,
        purpose=Purpose.REPORT,
        water_point_id=household.water_point_id,
        captured_via=captured_via,
        captured_at=config.now(),
        **result_to_checkin_fields(flow),
    )
    if repo.put_checkin(checkin):
        _report_checkin(checkin)
    refresh_day(repo, village.id, record.day)
    ticket = residents.report_problem(repo, village, household, reason, origin=TicketOrigin.REPORT)
    return record.model_copy(update={"ticket_number": ticket.number})


def _finish_registration(repo: Repository, record: CallRecord) -> None:
    flow = record.flow
    if flow.village_id is None or flow.household_id is None:
        raise ValueError(f"registration call {record.call_id} has no village or household")
    existing = repo.get_household(flow.village_id, flow.household_id)
    phone = record.phone_e164 or (existing.phone_e164 if existing else None)
    if phone is None:
        raise ValueError(f"registration call {record.call_id} has no phone number")
    result = result_to_registration(flow)
    residents.finish_registration(
        repo,
        village_id=flow.village_id,
        household_id=flow.household_id,
        phone=phone,
        call_id=record.call_id,
        adult=result["adult"],
        consent=result["consent"],
        digits=result["consent_digits"],
        access=result["access"],
        language=result["language"],
    )


def _finish_broadcast(repo: Repository, record: CallRecord) -> None:
    flow = record.flow
    if not (record.broadcast_id and flow.village_id):
        return
    if flow.step is FlowStep.START:
        return  # busy, no answer or failed: the hangup callback is not a delivery
    from jalsakshi.handlers import broadcasts

    broadcasts.record_delivery(
        repo, flow.village_id, record.broadcast_id, heard=flow.answers.heard is True
    )
    if stop_requested(flow) and flow.household_id:
        household = repo.get_household(flow.village_id, flow.household_id)
        if household is not None:
            residents.withdraw(repo, household, call_id=record.call_id)


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
    outcome = result_to_operator(flow)
    fixed, blocker = outcome["fixed"], outcome["blocker"]
    actor = f"operator:{flow.operator_id}"
    if fixed is True and flow.ticket_id:
        result = tickets.report_fixed(repo, flow.ticket_id, actor, via="call")
        if isinstance(result, Denied):
            logger.warning("operator fix not applied", extra={"reason": result.reason})
        return
    if blocker is not None and flow.ticket_id:
        _record_blocker(repo, flow.ticket_id, blocker, actor, flow.operator_id)
        return
    activity(
        "call",
        flow.village_id,
        f"Operator {flow.operator_id} says ticket {flow.ticket_id} is not fixed yet",
        f"मित्र {flow.operator_id} ने कहा शिकायत {flow.ticket_id} अभी ठीक नहीं हुई",
    )


def _record_blocker(
    repo: Repository,
    ticket_id: str,
    blocker: BlockerCode,
    actor: str,
    operator_id: str | None,
) -> None:
    """The operator gave a reason it is not fixed: note it, and re-route a "not mine"."""
    detail: dict[str, object] = {"note": "operator_reason", "code": blocker.value}
    if blocker is BlockerCode.NOT_MINE:
        detail["not_mine"] = operator_id
    result = residents.update_ticket(
        repo, ticket_id, lambda t: t.model_copy(update={"blocker": blocker}), detail, actor
    )
    if isinstance(result, Denied):
        logger.warning("blocker not recorded", extra={"reason": result.reason})
        return
    activity(
        "ticket",
        result.village_id,
        f"Operator says complaint #{result.number} is blocked: {blocker.value}",
        f"मित्र ने बताया शिकायत क्रमांक {result.number} क्यों अटकी है: {blocker.value}",
    )


def callbacks_today(repo: Repository, phone: str) -> int:
    """Call-backs queued for this number's missed calls in the last 24 hours.

    Rings inside the 10-minute cooldown are logged but queue nothing, so they do not count.
    """
    since = config.now() - CALLBACK_WINDOW
    return sum(1 for m in repo.list_missed_calls(phone, since) if callback_queued(m))


def callback_queued(missed: Mapping[str, Any]) -> bool:
    """True when a logged missed call queued a call-back (entries without the flag: assume so)."""
    return missed.get("callback", True) is not False


def is_consented(household: Household | None) -> bool:
    """True for an active household that has granted consent."""
    return (
        household is not None
        and household.active
        and household.effective_consent is ConsentStatus.GRANTED
    )
