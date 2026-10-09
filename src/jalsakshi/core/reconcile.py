"""Day reconciler: household check-ins to a village's status for one day (ARCHITECTURE §4, §15.2).

Pure and deterministic: no I/O, no clock reads, no LLM. Any change to the rules below must bump
`RULE_VERSION`, because stored `DayStatus` items record the version that produced them.

A household counts as *answered* only when its latest attempt is ANSWERED **and** it gave a
water answer. UNREACHABLE and DECLINED never count, and a call that was picked up but left the
water question blank is not evidence of anything (missing answers are never guessed).

r2 (§15.2) groups households by water point: DAILY answers and resident REPORTs both count, the
latest answer per household wins (by capture time), each point gets the r1 table with its own
quorum, and the village takes the worst status among points that have evidence.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime

from jalsakshi.core.models import (
    CallOutcome,
    CheckIn,
    CleanAnswer,
    DayCounts,
    DayStatus,
    DayStatusValue,
    PointStatus,
    Purpose,
    TicketReason,
    Village,
    WaterAnswer,
    WaterPoint,
)

RULE_VERSION = "r2"
DAY_PURPOSES: frozenset[Purpose] = frozenset({Purpose.DAILY, Purpose.REPORT})
"""Check-in purposes that describe the day's supply (VERIFY answers belong to a ticket)."""

_SEVERITY: dict[DayStatusValue, int] = {
    DayStatusValue.NO_SUPPLY: 4,
    DayStatusValue.DIRTY: 3,
    DayStatusValue.PARTIAL: 2,
    DayStatusValue.SUPPLIED: 1,
    DayStatusValue.UNVERIFIED: 0,
}

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


def latest_answers(checkins: Iterable[CheckIn]) -> list[CheckIn]:
    """Latest check-in per household by capture time (then attempt), across purposes.

    DAILY and REPORT attempts are numbered separately, so recency is the capture time: a
    resident's afternoon report overrides the morning call. Ties use a total order on the
    record, so the result does not depend on input order. Sorted by household id.
    """
    latest: dict[str, CheckIn] = {}
    for checkin in checkins:
        current = latest.get(checkin.household_id)
        if current is None or _answer_key(checkin) > _answer_key(current):
            latest[checkin.household_id] = checkin
    return [latest[household_id] for household_id in sorted(latest)]


def worst_status(statuses: Iterable[DayStatusValue]) -> DayStatusValue:
    """The village's status from its points: the worst one with evidence, else UNVERIFIED."""
    return max(statuses, key=lambda status: _SEVERITY[status], default=DayStatusValue.UNVERIFIED)


def reconcile_day(
    checkins: Iterable[CheckIn],
    village: Village,
    day: date,
    now: datetime,
    water_points: Sequence[WaterPoint] = (),
) -> DayStatus:
    """Compute the village's status for `day` from its DAILY and REPORT check-ins (rule r2).

    Every active point in `water_points` gets a `PointStatus`, even with no answers (then
    UNVERIFIED); points that only appear on check-ins are included too.
    """
    relevant = [
        checkin
        for checkin in checkins
        if checkin.purpose in DAY_PURPOSES
        and checkin.village_id == village.id
        and checkin.date == day
    ]
    latest = latest_answers(relevant)
    groups: dict[str | None, list[CheckIn]] = defaultdict(list)
    for checkin in latest:
        groups[checkin.water_point_id].append(checkin)
    quorums: Mapping[str | None, int] = {
        point.id: point.quorum or village.quorum for point in water_points
    }
    ids = [point.id for point in water_points if point.active]
    ids += sorted((wid for wid in groups if wid is not None and wid not in ids), key=str)
    if None in groups:
        ids.append(None)
    points = [
        _point_status(wid, groups.get(wid, []), quorums.get(wid, village.quorum)) for wid in ids
    ]
    evidence = [p.status for p in points if p.status is not DayStatusValue.UNVERIFIED]
    return DayStatus(
        village_id=village.id,
        date=day,
        status=worst_status(evidence),
        counts=count_answers(latest),
        rule_version=RULE_VERSION,
        computed_at=now,
        points=points,
    )


def tickets_to_open(
    status: DayStatus, open_keys: Iterable[tuple[str | None, TicketReason]]
) -> list[tuple[str | None, TicketReason]]:
    """(water point, reason) pairs that should open a ticket today, skipping ones already open."""
    taken = set(open_keys)
    wanted: list[tuple[str | None, TicketReason]] = []
    for point in status.points:
        reason = _TICKET_REASONS.get(point.status)
        if reason is not None and (point.water_point_id, reason) not in taken:
            wanted.append((point.water_point_id, reason))
    return wanted


def should_open_ticket(status: DayStatusValue, has_open_ticket: bool) -> TicketReason | None:
    """Return the reason to open a repair ticket, or None (no trigger, or one is already open)."""
    if has_open_ticket:
        return None
    return _TICKET_REASONS.get(DayStatusValue(status))


def _point_status(
    water_point_id: str | None, latest: Sequence[CheckIn], quorum: int
) -> PointStatus:
    counts = count_answers(latest)
    return PointStatus(
        water_point_id=water_point_id, status=status_for(counts, quorum), counts=counts
    )


def _answer_key(checkin: CheckIn) -> tuple[datetime, int, str, str]:
    """Recency across purposes: capture time, then attempt, then a total tie-break."""
    return (checkin.captured_at, checkin.attempt, checkin.call_id, checkin.model_dump_json())


def _recency_key(checkin: CheckIn) -> tuple[date, int, datetime, str, str]:
    """Order check-ins of one household: latest date, highest attempt, then a total tie-break."""
    return (
        checkin.date,
        checkin.attempt,
        checkin.captured_at,
        checkin.call_id,
        checkin.model_dump_json(),
    )
