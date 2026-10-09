"""Village analytics for a period: water points, complaints, households, announcements (§15.10).

Pure and deterministic: no I/O, no clock reads (`now` is passed in), no LLM. The same inputs give
the same output in any order, so the console, the public page and the weekly summary agree.

Rules:
- Reliability is supplied ÷ observed days. A day with no `DayStatus`, or an UNVERIFIED one, is
  *unknown*: it is excluded from reliability and reported separately, never guessed.
- A `DayStatus` written before r2 has no `points`; its village status counts for the point-less
  group (`water_point_id` None), and every named point is unknown that day.
- Tickets, events, consents, broadcasts and tests are "in period" by their IST calendar date;
  check-ins by their own `date`. Open tickets are a snapshot at `now` (any opened on or before
  `end`, aged from `now`).
- A repair runs from `opened_at` to the first VERIFIED_OK event: a complaint counts as closed
  only once households confirmed water, never on the operator's word alone.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from jalsakshi.core.clock import to_ist
from jalsakshi.core.models import (
    Broadcast,
    BroadcastState,
    CheckIn,
    ConsentEvent,
    ConsentStatus,
    DayStatus,
    DayStatusValue,
    Freshness,
    Household,
    Purpose,
    QualityMethod,
    QualityResult,
    QualityTest,
    SourceTag,
    Ticket,
    TicketReason,
    TicketState,
    Village,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.core.reconcile import is_answered, latest_attempts
from jalsakshi.core.tickets import TicketEventKind, is_open

RULE_NOTE = (
    "Unknown days are excluded from reliability and shown separately; "
    "resident-reported, not a household census."
)
SOURCE_NAME = "JalSakshi household check-ins (resident-reported)"
OPERATOR_REASON_NOTE = "operator_reason"
"""`TicketEvent.detail["note"]` of an operator's reason code (§15.7)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class OpenTicketAge(_Frozen):
    """A complaint still open at `now`, how long it has been open, and the operator's blocker."""

    ticket_id: str
    number: int | None
    reason: TicketReason
    state: TicketState
    age_hours: float
    blocker: str | None = None


class QualitySnapshot(_Frozen):
    """The latest water-quality test of a point."""

    result: QualityResult
    method: QualityMethod
    tested_at: datetime


class PointAnalytics(_Frozen):
    """One water point over the period (`water_point_id` None = households with no point)."""

    water_point_id: str | None
    name: str | None
    kind: WaterPointKind | None
    days_in_period: int
    observed: int
    supplied: int
    partial: int
    no_supply: int
    dirty: int
    unknown: int
    reliability_pct: float | None
    complaints_by_reason: dict[str, int]
    open_tickets: list[OpenTicketAge]
    repairs_closed: int
    median_repair_hours: float | None
    worst_repair_hours: float | None
    reopened: int
    blockers: dict[str, int]
    last_quality: QualitySnapshot | None
    dirty_without_test: bool


class HouseholdAnalytics(_Frozen):
    """Who is registered and consented, and how often the daily call got an answer."""

    registered: int
    consented: int
    withdrawn: int
    declined: int
    pending: int
    census_households: int | None
    coverage_pct: float | None
    called: int
    answered: int
    answer_rate_pct: float | None
    fallback_counts: dict[str, int]
    reports_by_resident: int
    consent_events: dict[str, int]


class BroadcastAnalytics(_Frozen):
    """Announcements sent in the period and how many households heard them."""

    sent: int
    recipients: int
    delivered: int
    heard: int


class VillageAnalytics(_Frozen):
    """Everything `GET /api/villages/{vid}/analytics` returns for one period."""

    village_id: str
    start: date
    end: date
    generated_at: datetime
    source: SourceTag
    rule_note: str
    points: list[PointAnalytics]
    village: PointAnalytics
    households: HouseholdAnalytics
    broadcasts: BroadcastAnalytics
    tickets_opened: int
    tickets_closed_verified: int
    median_repair_hours: float | None


@dataclass(frozen=True, slots=True)
class _Period:
    """An inclusive range of IST calendar dates."""

    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def has_day(self, day: date) -> bool:
        return self.start <= day <= self.end

    def contains(self, at: datetime) -> bool:
        return self.has_day(_ist_date(at))


def village_analytics(
    village: Village,
    start: date,
    end: date,
    now: datetime,
    *,
    water_points: Sequence[WaterPoint] = (),
    days: Sequence[DayStatus] = (),
    tickets: Sequence[Ticket] = (),
    households: Sequence[Household] = (),
    consents: Sequence[ConsentEvent] = (),
    checkins: Sequence[CheckIn] = (),
    broadcasts: Sequence[Broadcast] = (),
    quality: Sequence[QualityTest] = (),
    freshness: Freshness = Freshness.DAILY,
) -> VillageAnalytics:
    """Analytics for `village` over the IST dates `start`..`end` (inclusive), as of `now`.

    Records of other villages are ignored. `freshness` labels the result's `SourceTag`; pass
    SIMULATED or REPLAY for demo data. Raises ValueError for a naive `now` or `end < start`.
    """
    to_ist(now)
    if end < start:
        raise ValueError(f"period ends ({end}) before it starts ({start})")
    period = _Period(start, end)
    vid = village.id
    day_map = _latest_days(d for d in days if d.village_id == vid and period.has_day(d.date))
    own_tickets = [t for t in tickets if t.village_id == vid]
    tests = [q for q in quality if q.village_id == vid]
    known = {p.id: p for p in water_points if p.village_id == vid}
    by_point: dict[str | None, list[Ticket]] = defaultdict(list)
    for ticket in own_tickets:
        by_point[ticket.water_point_id].append(ticket)

    points = [
        _point_analytics(
            wid,
            known[wid].name if wid in known else None,
            known[wid].kind if wid in known else None,
            _point_statuses(day_map, wid),
            by_point.get(wid, []),
            [q for q in tests if q.water_point_id == wid],
            period,
            now,
        )
        for wid in _group_ids(water_points, vid, day_map, own_tickets, period, now)
    ]
    totals = _point_analytics(
        None,
        village.name,
        None,
        [d.status for d in day_map.values()],
        own_tickets,
        tests,
        period,
        now,
    )
    return VillageAnalytics(
        village_id=vid,
        start=start,
        end=end,
        generated_at=now,
        source=SourceTag(
            source=SOURCE_NAME,
            observed_at=max((d.computed_at for d in day_map.values()), default=None),
            fetched_at=now,
            freshness=freshness,
        ),
        rule_note=RULE_NOTE,
        points=points,
        village=totals,
        households=_household_analytics(
            village,
            period,
            [h for h in households if h.village_id == vid],
            [e for e in consents if e.village_id == vid],
            [c for c in checkins if c.village_id == vid],
        ),
        broadcasts=_broadcast_analytics([b for b in broadcasts if b.village_id == vid], period),
        tickets_opened=sum(totals.complaints_by_reason.values()),
        tickets_closed_verified=totals.repairs_closed,
        median_repair_hours=totals.median_repair_hours,
    )


# --- days ----------------------------------------------------------------------------------------


def _latest_days(days: Iterable[DayStatus]) -> dict[date, DayStatus]:
    """One `DayStatus` per date: the latest computed (a recompute replaces the earlier one)."""
    latest: dict[date, DayStatus] = {}
    for day in days:
        current = latest.get(day.date)
        if current is None or _day_key(day) > _day_key(current):
            latest[day.date] = day
    return dict(sorted(latest.items()))


def _day_key(day: DayStatus) -> tuple[datetime, str, str]:
    return (day.computed_at, day.rule_version, day.model_dump_json())


def _point_statuses(day_map: Mapping[date, DayStatus], wid: str | None) -> list[DayStatusValue]:
    """The group's status on each recorded day; a day without its `PointStatus` is unknown."""
    statuses: list[DayStatusValue] = []
    for day in day_map.values():
        if not day.points:
            if wid is None:
                statuses.append(day.status)
            continue
        statuses.extend(p.status for p in day.points if p.water_point_id == wid)
    return statuses


def _group_ids(
    water_points: Sequence[WaterPoint],
    vid: str,
    day_map: Mapping[date, DayStatus],
    tickets: Sequence[Ticket],
    period: _Period,
    now: datetime,
) -> list[str | None]:
    """Active points in the given order, then other points the data mentions, then None."""
    ids: list[str | None] = []
    for point in water_points:
        if point.village_id == vid and point.active and point.id not in ids:
            ids.append(point.id)
    mentioned: set[str | None] = set()
    for day in day_map.values():
        if not day.points:
            mentioned.add(None)
        mentioned.update(p.water_point_id for p in day.points)
    mentioned.update(t.water_point_id for t in tickets if _touches(t, period, now))
    ids += sorted(wid for wid in mentioned if wid is not None and wid not in ids)
    if None in mentioned:
        ids.append(None)
    return ids


# --- tickets -------------------------------------------------------------------------------------


def _point_analytics(
    wid: str | None,
    name: str | None,
    kind: WaterPointKind | None,
    statuses: Sequence[DayStatusValue],
    tickets: Sequence[Ticket],
    tests: Sequence[QualityTest],
    period: _Period,
    now: datetime,
) -> PointAnalytics:
    counts = Counter(statuses)
    observed = sum(n for status, n in counts.items() if status is not DayStatusValue.UNVERIFIED)
    supplied = counts[DayStatusValue.SUPPLIED]
    open_now = _open_tickets(tickets, period, now)
    repairs = sorted(hours for t in tickets if (hours := _repair_hours(t, period)) is not None)
    return PointAnalytics(
        water_point_id=wid,
        name=name,
        kind=kind,
        days_in_period=period.days,
        observed=observed,
        supplied=supplied,
        partial=counts[DayStatusValue.PARTIAL],
        no_supply=counts[DayStatusValue.NO_SUPPLY],
        dirty=counts[DayStatusValue.DIRTY],
        unknown=period.days - observed,
        reliability_pct=_pct(supplied, observed),
        complaints_by_reason=_tally(
            t.reason.value for t in tickets if period.contains(t.opened_at)
        ),
        open_tickets=[_age(t, now) for t in open_now],
        repairs_closed=len(repairs),
        median_repair_hours=round(statistics.median(repairs), 1) if repairs else None,
        worst_repair_hours=round(repairs[-1], 1) if repairs else None,
        reopened=sum(
            event.kind == TicketEventKind.VERIFY_FAILED and period.contains(event.at)
            for t in tickets
            for event in t.events
        ),
        blockers=_tally(_blocker_codes(tickets, period)),
        last_quality=_last_quality(tests, period),
        dirty_without_test=any(_untested_dirty(t, tests) for t in open_now),
    )


def _touches(ticket: Ticket, period: _Period, now: datetime) -> bool:
    """True when the ticket feeds any metric: opened or acted on in the period, or open now."""
    if period.contains(ticket.opened_at) or _listed_open(ticket, period, now):
        return True
    return any(period.contains(event.at) for event in ticket.events)


def _listed_open(ticket: Ticket, period: _Period, now: datetime) -> bool:
    """Still open at `now`, and opened by the end of the period (and not in the future)."""
    return is_open(ticket) and ticket.opened_at <= now and _ist_date(ticket.opened_at) <= period.end


def _open_tickets(tickets: Iterable[Ticket], period: _Period, now: datetime) -> list[Ticket]:
    """The open-ticket snapshot (see `_listed_open`), oldest first."""
    found = [t for t in tickets if _listed_open(t, period, now)]
    return sorted(found, key=lambda t: (t.opened_at, t.number or 0, t.id))


def _age(ticket: Ticket, now: datetime) -> OpenTicketAge:
    return OpenTicketAge(
        ticket_id=ticket.id,
        number=ticket.number,
        reason=ticket.reason,
        state=ticket.state,
        age_hours=round(_hours(now - ticket.opened_at), 1),
        blocker=ticket.blocker.value if ticket.blocker is not None else None,
    )


def _verified_at(ticket: Ticket) -> datetime | None:
    """When households confirmed the repair (first VERIFIED_OK), or None if never.

    A CLOSED_VERIFIED ticket with no event log (seeded data) falls back to `updated_at`.
    """
    for event in ticket.events:
        if event.kind == TicketEventKind.VERIFIED_OK:
            return event.at
    return ticket.updated_at if ticket.state is TicketState.CLOSED_VERIFIED else None


def _repair_hours(ticket: Ticket, period: _Period) -> float | None:
    """Hours from opening to confirmed repair, for a ticket confirmed within the period."""
    verified = _verified_at(ticket)
    if verified is None or not period.contains(verified):
        return None
    return _hours(verified - ticket.opened_at)


def _blocker_codes(tickets: Iterable[Ticket], period: _Period) -> list[str]:
    """Operator reason codes (§15.7) noted on the tickets during the period."""
    return [
        str(event.detail["code"])
        for t in tickets
        for event in t.events
        if event.kind == TicketEventKind.NOTE
        and event.detail.get("note") == OPERATOR_REASON_NOTE
        and event.detail.get("code")
        and period.contains(event.at)
    ]


def _last_quality(tests: Iterable[QualityTest], period: _Period) -> QualitySnapshot | None:
    dated = [q for q in tests if _ist_date(q.tested_at) <= period.end]
    if not dated:
        return None
    latest = max(dated, key=lambda q: (q.tested_at, q.id))
    return QualitySnapshot(result=latest.result, method=latest.method, tested_at=latest.tested_at)


def _untested_dirty(ticket: Ticket, tests: Iterable[QualityTest]) -> bool:
    """An open DIRTY complaint whose point has had no quality test since it opened."""
    if ticket.reason is not TicketReason.DIRTY or not is_open(ticket):
        return False
    return not any(
        q.water_point_id == ticket.water_point_id and q.tested_at >= ticket.opened_at for q in tests
    )


# --- households and broadcasts -------------------------------------------------------------------


def _household_analytics(
    village: Village,
    period: _Period,
    households: Sequence[Household],
    consents: Sequence[ConsentEvent],
    checkins: Sequence[CheckIn],
) -> HouseholdAnalytics:
    consent = Counter(h.effective_consent for h in households)
    consented = sum(h.effective_consent == ConsentStatus.GRANTED and h.active for h in households)
    in_period = [c for c in checkins if period.has_day(c.date)]
    by_date: dict[date, list[CheckIn]] = defaultdict(list)
    for checkin in in_period:
        if checkin.purpose == Purpose.DAILY:
            by_date[checkin.date].append(checkin)
    latest = [c for day in sorted(by_date) for c in latest_attempts(by_date[day])]
    answered = sum(is_answered(c) for c in latest)
    census = village.census_households
    return HouseholdAnalytics(
        registered=len(households),
        consented=consented,
        withdrawn=consent[ConsentStatus.WITHDRAWN],
        declined=consent[ConsentStatus.DECLINED],
        pending=consent[ConsentStatus.NONE],
        census_households=census,
        coverage_pct=_pct(consented, census or 0),
        called=len(latest),
        answered=answered,
        answer_rate_pct=_pct(answered, len(latest)),
        fallback_counts=_tally(c.fallback.value for c in in_period if c.fallback is not None),
        reports_by_resident=sum(c.purpose == Purpose.REPORT for c in in_period),
        consent_events=_tally(e.action.value for e in consents if period.contains(e.at)),
    )


def _broadcast_analytics(broadcasts: Iterable[Broadcast], period: _Period) -> BroadcastAnalytics:
    sent = [
        b
        for b in broadcasts
        if b.state == BroadcastState.SENT and b.sent_at is not None and period.contains(b.sent_at)
    ]
    return BroadcastAnalytics(
        sent=len(sent),
        recipients=sum(b.recipients for b in sent),
        delivered=sum(b.delivered for b in sent),
        heard=sum(b.heard for b in sent),
    )


# --- small helpers -------------------------------------------------------------------------------


def _ist_date(at: datetime) -> date:
    return to_ist(at).date()


def _hours(delta: timedelta) -> float:
    """A duration in hours, never negative (clock skew between writers must not go below 0)."""
    return max(0.0, delta.total_seconds() / 3600)


def _pct(part: int, whole: int) -> float | None:
    """`part` as a percentage of `whole`, 1 decimal; None when `whole` is 0 (nothing to divide)."""
    return round(part / whole * 100, 1) if whole > 0 else None


def _tally(keys: Iterable[str]) -> dict[str, int]:
    """Count keys into a dict sorted by key, so the JSON is stable."""
    return dict(sorted(Counter(keys).items()))
