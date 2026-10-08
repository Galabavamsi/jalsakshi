"""Day reconciler: household check-ins to a village's status for one day (ARCHITECTURE.md §4).

Pure and deterministic: no I/O, no clock reads, no LLM. Any change to the rules below must bump
`RULE_VERSION`, because stored `DayStatus` items record the version that produced them.

A household counts as *answered* only when its latest attempt is ANSWERED **and** it gave a
water answer. UNREACHABLE and DECLINED never count, and a call that was picked up but left the
water question blank is not evidence of anything (missing answers are never guessed).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime

from jalsakshi.core.models import (
    CallOutcome,
    CheckIn,
    CleanAnswer,
    DayCounts,
    DayStatus,
    DayStatusValue,
    Purpose,
    TicketReason,
    Village,
    WaterAnswer,
)

RULE_VERSION = "r1"

_TICKET_REASONS: dict[DayStatusValue, TicketReason] = {
    DayStatusValue.NO_SUPPLY: TicketReason.NO_SUPPLY,
    DayStatusValue.DIRTY: TicketReason.DIRTY,
}


def latest_attempts(checkins: Iterable[CheckIn]) -> list[CheckIn]:
    """Keep the latest check-in per household (latest date, then highest attempt).

    Exact duplicates collapse to one, and ties are broken by a total order on the record, so the
    result does not depend on input order. Pass check-ins for one village and purpose; the
    result is sorted by household id.
    """
    latest: dict[str, CheckIn] = {}
    for checkin in checkins:
        current = latest.get(checkin.household_id)
        if current is None or _recency_key(checkin) > _recency_key(current):
            latest[checkin.household_id] = checkin
    return [latest[household_id] for household_id in sorted(latest)]


def is_answered(checkin: CheckIn) -> bool:
    """True when the household picked up and answered the water question."""
    return checkin.outcome == CallOutcome.ANSWERED and checkin.water is not None


def count_answers(latest: Sequence[CheckIn]) -> DayCounts:
    """Count answers over check-ins that are already one-per-household (see `latest_attempts`)."""
    answered = [checkin for checkin in latest if is_answered(checkin)]
    return DayCounts(
        answered=len(answered),
        yes=sum(checkin.water == WaterAnswer.YES for checkin in answered),
        no=sum(checkin.water == WaterAnswer.NO for checkin in answered),
        partial=sum(checkin.water == WaterAnswer.PARTIAL for checkin in answered),
        dirty=sum(checkin.clean == CleanAnswer.NO for checkin in answered),
        unreachable=sum(checkin.outcome == CallOutcome.UNREACHABLE for checkin in latest),
    )


def status_for(counts: DayCounts, quorum: int) -> DayStatusValue:
    """Apply the §4 rule table, top to bottom, to a day's counts."""
    if quorum < 1:
        raise ValueError(f"quorum must be at least 1, got {quorum}")
    if counts.answered < quorum:
        return DayStatusValue.UNVERIFIED
    if counts.no >= quorum and counts.no >= counts.yes + counts.partial:
        return DayStatusValue.NO_SUPPLY
    if counts.dirty >= quorum:
        return DayStatusValue.DIRTY
    if counts.no + counts.partial >= 1:
        return DayStatusValue.PARTIAL
    return DayStatusValue.SUPPLIED


def reconcile_day(
    checkins: Iterable[CheckIn], village: Village, day: date, now: datetime
) -> DayStatus:
    """Compute the village's status for `day` from its DAILY check-ins (others are ignored)."""
    daily = (
        checkin
        for checkin in checkins
        if checkin.purpose == Purpose.DAILY
        and checkin.village_id == village.id
        and checkin.date == day
    )
    counts = count_answers(latest_attempts(daily))
    return DayStatus(
        village_id=village.id,
        date=day,
        status=status_for(counts, village.quorum),
        counts=counts,
        rule_version=RULE_VERSION,
        computed_at=now,
    )


def should_open_ticket(status: DayStatusValue, has_open_ticket: bool) -> TicketReason | None:
    """Return the reason to open a repair ticket, or None (no trigger, or one is already open)."""
    if has_open_ticket:
        return None
    return _TICKET_REASONS.get(DayStatusValue(status))


def _recency_key(checkin: CheckIn) -> tuple[date, int, datetime, str, str]:
    """Order check-ins of one household: latest date, highest attempt, then a total tie-break."""
    return (
        checkin.date,
        checkin.attempt,
        checkin.captured_at,
        checkin.call_id,
        checkin.model_dump_json(),
    )
