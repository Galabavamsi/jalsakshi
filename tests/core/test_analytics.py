import json
from datetime import UTC, date, datetime, timedelta

import pytest

from jalsakshi.core.analytics import RULE_NOTE, VillageAnalytics, village_analytics
from jalsakshi.core.clock import IST
from jalsakshi.core.models import (
    BlockerCode,
    Broadcast,
    BroadcastKind,
    BroadcastState,
    CallOutcome,
    CheckIn,
    Consent,
    ConsentAction,
    ConsentEvent,
    ConsentStatus,
    DayCounts,
    DayStatus,
    DayStatusValue,
    Fallback,
    Freshness,
    Household,
    PointStatus,
    Purpose,
    QualityMethod,
    QualityResult,
    QualityTest,
    Ticket,
    TicketReason,
    TicketState,
    Village,
    WaterAnswer,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.core.tickets import Denied, TicketEventKind, new_ticket, transition

S = DayStatusValue
K = TicketEventKind
R = TicketReason

START, END = date(2026, 10, 3), date(2026, 10, 9)  # 7 days
NOW = datetime(2026, 10, 9, 18, 0, tzinfo=IST)
VILLAGE = Village(id="v1", name="Pathariya", block="Dhamdha", district="Durg", census_households=50)
WP1 = WaterPoint(id="wp1", village_id="v1", kind=WaterPointKind.PIPED, name="Main tap")
WP2 = WaterPoint(id="wp2", village_id="v1", kind=WaterPointKind.HANDPUMP, name="School handpump")
WP_OLD = WaterPoint(
    id="wp0", village_id="v1", kind=WaterPointKind.BOREWELL, name="Old borewell", active=False
)
POINTS = [WP1, WP2, WP_OLD]


def at(day: int, hour: int = 10, minute: int = 0) -> datetime:
    """An IST time in October 2026."""
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


def day_status(
    day: date,
    status: DayStatusValue,
    points: dict[str | None, DayStatusValue] | None = None,
    *,
    village_id: str = "v1",
    computed_at: datetime | None = None,
) -> DayStatus:
    return DayStatus(
        village_id=village_id,
        date=day,
        status=status,
        counts=DayCounts(),
        rule_version="r2",
        computed_at=computed_at or datetime.combine(day, datetime.min.time(), tzinfo=IST),
        points=[
            PointStatus(water_point_id=wid, status=value, counts=DayCounts())
            for wid, value in (points or {}).items()
        ],
    )


def week(statuses: list[DayStatusValue | None], wid: str = "wp1") -> list[DayStatus]:
    """One DayStatus per non-None entry, from START onward, for a single point."""
    return [
        day_status(START + timedelta(days=i), value, {wid: value})
        for i, value in enumerate(statuses)
        if value is not None
    ]


def step(ticket: Ticket, kind: K, when: datetime, **detail: object) -> Ticket:
    result = transition(ticket, kind, "tester", when, detail or None)
    assert not isinstance(result, Denied), result
    return result


def ticket(
    tid: str,
    opened: datetime,
    wid: str | None = "wp1",
    reason: TicketReason = R.NO_SUPPLY,
    number: int = 1,
) -> Ticket:
    base = new_ticket("v1", reason, opened, ticket_id=tid)
    return base.model_copy(update={"water_point_id": wid, "number": number})


def repaired(tid: str, opened: datetime, hours: float, wid: str | None = "wp1") -> Ticket:
    """A ticket confirmed fixed by households `hours` after it opened."""
    t = ticket(tid, opened, wid)
    t = step(t, K.NOTIFIED, opened + timedelta(minutes=5))
    t = step(t, K.OPERATOR_FIXED, opened + timedelta(minutes=10))
    t = step(t, K.VERIFY_STARTED, opened + timedelta(minutes=20))
    return step(t, K.VERIFIED_OK, opened + timedelta(hours=hours))


def analytics(**kwargs: object) -> VillageAnalytics:
    kwargs.setdefault("water_points", POINTS)
    return village_analytics(VILLAGE, START, END, NOW, **kwargs)  # type: ignore[arg-type]


def point(result: VillageAnalytics, wid: str | None):
    matches = [p for p in result.points if p.water_point_id == wid]
    assert len(matches) == 1, [p.water_point_id for p in result.points]
    return matches[0]


# --- day statuses and reliability ----------------------------------------------------------------


def test_reliability_excludes_unknown_days() -> None:
    days = week([S.SUPPLIED, S.SUPPLIED, S.NO_SUPPLY, S.UNVERIFIED, S.SUPPLIED, None, None])
    wp1 = point(analytics(days=days), "wp1")
    assert wp1.days_in_period == 7
    assert (wp1.observed, wp1.supplied, wp1.no_supply, wp1.unknown) == (4, 3, 1, 3)
    assert wp1.reliability_pct == 75.0


def test_counts_each_status_and_rounds_reliability() -> None:
    days = week([S.SUPPLIED, S.PARTIAL, S.DIRTY, S.NO_SUPPLY, S.SUPPLIED, S.SUPPLIED])
    wp1 = point(analytics(days=days), "wp1")
    assert (wp1.supplied, wp1.partial, wp1.dirty, wp1.no_supply) == (3, 1, 1, 1)
    assert wp1.observed == 6 and wp1.unknown == 1
    assert wp1.reliability_pct == 50.0
    two_of_three = point(analytics(days=week([S.SUPPLIED, S.SUPPLIED, S.PARTIAL])), "wp1")
    assert two_of_three.reliability_pct == 66.7


def test_point_with_no_observed_days_has_no_reliability() -> None:
    wp2 = point(analytics(days=week([S.SUPPLIED, S.SUPPLIED])), "wp2")
    assert wp2.observed == 0 and wp2.unknown == 7
    assert wp2.reliability_pct is None


def test_village_totals_use_the_village_status() -> None:
    days = [
        day_status(date(2026, 10, 3), S.NO_SUPPLY, {"wp1": S.SUPPLIED, "wp2": S.NO_SUPPLY}),
        day_status(date(2026, 10, 4), S.SUPPLIED, {"wp1": S.SUPPLIED, "wp2": S.UNVERIFIED}),
        day_status(date(2026, 10, 5), S.UNVERIFIED, {"wp1": S.UNVERIFIED}),
    ]
    result = analytics(days=days)
    totals = result.village
    assert totals.name == "Pathariya" and totals.water_point_id is None
    assert (totals.observed, totals.supplied, totals.no_supply, totals.unknown) == (2, 1, 1, 5)
    assert totals.reliability_pct == 50.0
    assert point(result, "wp2").no_supply == 1


def test_days_outside_period_or_other_village_are_ignored() -> None:
    days = [
        day_status(date(2026, 10, 2), S.SUPPLIED, {"wp1": S.SUPPLIED}),
        day_status(date(2026, 10, 10), S.SUPPLIED, {"wp1": S.SUPPLIED}),
        day_status(date(2026, 10, 5), S.SUPPLIED, {"wp1": S.SUPPLIED}, village_id="v2"),
        day_status(date(2026, 10, 9), S.NO_SUPPLY, {"wp1": S.NO_SUPPLY}),
    ]
    wp1 = point(analytics(days=days), "wp1")
    assert (wp1.observed, wp1.no_supply, wp1.supplied) == (1, 1, 0)


def test_a_recomputed_day_replaces_the_earlier_one() -> None:
    early = day_status(START, S.NO_SUPPLY, {"wp1": S.NO_SUPPLY}, computed_at=at(3, 11))
    late = day_status(START, S.SUPPLIED, {"wp1": S.SUPPLIED}, computed_at=at(3, 20))
    for days in ([early, late], [late, early]):
        wp1 = point(analytics(days=days), "wp1")
        assert (wp1.observed, wp1.supplied, wp1.no_supply) == (1, 1, 0)


# --- groups --------------------------------------------------------------------------------------


def test_points_follow_the_given_order_and_skip_inactive_ones() -> None:
    result = analytics(water_points=[WP2, WP_OLD, WP1])
    assert [p.water_point_id for p in result.points] == ["wp2", "wp1"]
    assert result.points[0].name == "School handpump"
    assert result.points[0].kind == WaterPointKind.HANDPUMP


def test_no_none_group_when_nothing_lacks_a_point() -> None:
    result = analytics(days=week([S.SUPPLIED]), tickets=[ticket("t1", at(4))])
    assert None not in [p.water_point_id for p in result.points]


def test_none_group_from_day_points_without_a_water_point() -> None:
    days = [day_status(START, S.NO_SUPPLY, {"wp1": S.SUPPLIED, None: S.NO_SUPPLY})]
    result = analytics(days=days)
    assert [p.water_point_id for p in result.points] == ["wp1", "wp2", None]
    none_group = point(result, None)
    assert none_group.name is None and none_group.kind is None
    assert (none_group.observed, none_group.no_supply) == (1, 1)


def test_legacy_day_without_points_counts_for_the_none_group_only() -> None:
    days = [
        day_status(date(2026, 10, 3), S.SUPPLIED),  # r1 item: no per-point detail
        day_status(date(2026, 10, 4), S.NO_SUPPLY, {"wp1": S.NO_SUPPLY}),
    ]
    result = analytics(days=days)
    none_group, wp1 = point(result, None), point(result, "wp1")
    assert (none_group.observed, none_group.supplied, none_group.unknown) == (1, 1, 6)
    assert (wp1.observed, wp1.no_supply, wp1.unknown) == (1, 1, 6)
    assert result.village.observed == 2


def test_none_group_from_a_ticket_without_a_water_point() -> None:
    result = analytics(tickets=[ticket("t1", at(5), wid=None)])
    none_group = point(result, None)
    assert none_group.complaints_by_reason == {"NO_SUPPLY": 1}
    assert none_group.observed == 0 and none_group.reliability_pct is None


def test_inactive_or_unknown_point_with_period_data_still_gets_a_group() -> None:
    tickets = [ticket("t1", at(5), wid="wp0"), ticket("t2", at(6), wid="wp9", number=2)]
    result = analytics(tickets=tickets)
    assert [p.water_point_id for p in result.points] == ["wp1", "wp2", "wp0", "wp9"]
    assert point(result, "wp0").name == "Old borewell"
    assert point(result, "wp9").name is None


def test_old_closed_ticket_does_not_create_a_group() -> None:
    old = repaired("t1", at(1), 5, wid=None)  # opened and closed before the period
    assert None not in [p.water_point_id for p in analytics(tickets=[old]).points]


# --- tickets -------------------------------------------------------------------------------------


def test_complaints_by_reason_count_tickets_opened_in_the_period_by_ist_date() -> None:
    tickets = [
        ticket("t1", datetime(2026, 10, 2, 19, 0, tzinfo=UTC)),  # 3 Oct 00:30 IST: in
        ticket("t2", datetime(2026, 10, 2, 18, 0, tzinfo=UTC)),  # 2 Oct 23:30 IST: out
        ticket("t3", at(9, 17, 59), reason=R.DIRTY),
        ticket("t4", at(5), reason=R.DIRTY),
        ticket("t5", at(5), wid="wp2", reason=R.LEAK),
    ]
    result = analytics(tickets=tickets)
    assert point(result, "wp1").complaints_by_reason == {"DIRTY": 2, "NO_SUPPLY": 1}
    assert point(result, "wp2").complaints_by_reason == {"LEAK": 1}
    assert result.tickets_opened == 4


def test_repair_time_median_and_worst_over_repairs_confirmed_in_the_period() -> None:
    tickets = [
        repaired("t1", at(3, 9), 10),
        repaired("t2", at(4, 9), 40),
        repaired("t3", at(5, 9), 20),
        repaired("t4", at(1, 9), 12),  # confirmed 1 Oct: before the period
        repaired("t5", at(2, 20), 30),  # opened before, confirmed 4 Oct: counts
        repaired("t6", at(6, 9), 5, wid="wp2"),
    ]
    result = analytics(tickets=tickets)
    wp1 = point(result, "wp1")
    assert wp1.repairs_closed == 4
    assert wp1.median_repair_hours == 25.0  # median of 10, 20, 30, 40
    assert wp1.worst_repair_hours == 40.0
    assert point(result, "wp2").median_repair_hours == 5.0
    assert result.tickets_closed_verified == 5
    assert result.median_repair_hours == 20.0  # median of 5, 10, 20, 30, 40
    assert result.village.worst_repair_hours == 40.0


def test_repair_time_is_none_without_confirmed_repairs() -> None:
    t = step(ticket("t1", at(4)), K.NOTIFIED, at(4, 11))
    t = step(t, K.OPERATOR_FIXED, at(4, 12))  # operator says fixed: not a confirmed repair
    wp1 = point(analytics(tickets=[t]), "wp1")
    assert wp1.repairs_closed == 0
    assert wp1.median_repair_hours is None and wp1.worst_repair_hours is None


def test_closed_ticket_without_event_log_uses_updated_at() -> None:
    seeded = ticket("t1", at(4, 8)).model_copy(
        update={"state": TicketState.CLOSED_VERIFIED, "updated_at": at(4, 20)}
    )
    wp1 = point(analytics(tickets=[seeded]), "wp1")
    assert wp1.repairs_closed == 1 and wp1.median_repair_hours == 12.0


def test_reopened_counts_verify_failed_events_in_the_period() -> None:
    t = ticket("t1", at(1))
    t = step(t, K.NOTIFIED, at(1, 11))
    t = step(t, K.OPERATOR_FIXED, at(1, 12))
    t = step(t, K.VERIFY_STARTED, at(1, 13))
    t = step(t, K.VERIFY_FAILED, at(2, 10))  # before the period: not counted
    for day in (4, 6):
        t = step(t, K.NOTIFIED, at(day, 11))
        t = step(t, K.OPERATOR_FIXED, at(day, 12))
        t = step(t, K.VERIFY_STARTED, at(day, 13))
        t = step(t, K.VERIFY_FAILED, at(day, 18))
    result = analytics(tickets=[t])
    assert point(result, "wp1").reopened == 2
    assert point(result, "wp1").complaints_by_reason == {}  # opened before the period
    assert result.village.reopened == 2


def test_blockers_count_operator_reason_notes_in_the_period() -> None:
    t = ticket("t1", at(1))
    t = step(t, K.NOTE, at(2), note="operator_reason", code="NO_POWER")  # before period
    t = step(t, K.NOTE, at(4), note="operator_reason", code="PARTS_NEEDED")
    t = step(t, K.NOTE, at(5), note="operator_reason", code="NO_POWER")
    t = step(t, K.NOTE, at(6), note="operator_reason", code="NO_POWER")
    t = step(t, K.NOTE, at(6, 12), note="another_report")
    t = step(t, K.NOTE, at(7), note="operator_reason")  # no code: ignored
    t = t.model_copy(update={"blocker": BlockerCode.NO_POWER})
    other = step(
        ticket("t2", at(5), wid="wp2"), K.NOTE, at(5), note="operator_reason", code="NOT_MINE"
    )
    result = analytics(tickets=[t, other])
    assert point(result, "wp1").blockers == {"NO_POWER": 2, "PARTS_NEEDED": 1}
    assert point(result, "wp2").blockers == {"NOT_MINE": 1}
    assert result.village.blockers == {"NOT_MINE": 1, "NO_POWER": 2, "PARTS_NEEDED": 1}
    assert point(result, "wp1").open_tickets[0].blocker == "NO_POWER"


def test_open_tickets_are_aged_from_now_oldest_first() -> None:
    tickets = [
        ticket("t-new", at(9, 6), number=3),
        ticket("t-old", at(2, 17, 54), number=1),  # opened before the period, still open
        repaired("t-done", at(5), 4),
        ticket("t-future", at(10), number=9),  # opened after the period
    ]
    wp1 = point(analytics(tickets=tickets), "wp1")
    assert [o.ticket_id for o in wp1.open_tickets] == ["t-old", "t-new"]
    oldest = wp1.open_tickets[0]
    assert oldest.age_hours == 168.1  # 7 days and 6 minutes
    assert oldest.number == 1 and oldest.reason == R.NO_SUPPLY and oldest.state == TicketState.OPEN
    assert wp1.open_tickets[1].age_hours == 12.0


# --- quality -------------------------------------------------------------------------------------


def quality_test(qid: str, when: datetime, wid: str | None = "wp1", safe: bool = True):
    return QualityTest(
        id=qid,
        village_id="v1",
        water_point_id=wid,
        tested_at=when,
        method=QualityMethod.FTK,
        result=QualityResult.SAFE if safe else QualityResult.UNSAFE,
        entered_by="secretary",
    )


def test_last_quality_is_the_latest_test_up_to_the_end_of_the_period() -> None:
    tests = [
        quality_test("q1", at(1), safe=True),
        quality_test("q2", at(5), safe=False),
        quality_test("q3", at(11), safe=True),  # after the period
        quality_test("q4", at(8), wid="wp2"),
    ]
    result = analytics(quality=tests)
    last = point(result, "wp1").last_quality
    assert last is not None
    assert (last.result, last.method, last.tested_at) == (
        QualityResult.UNSAFE,
        QualityMethod.FTK,
        at(5),
    )
    assert result.village.last_quality is not None
    assert result.village.last_quality.tested_at == at(8)


def test_no_quality_test_gives_none() -> None:
    assert point(analytics(), "wp1").last_quality is None


def test_dirty_without_test_flags_open_dirty_ticket_with_no_test_since_opening() -> None:
    dirty = ticket("t1", at(5), reason=R.DIRTY)
    assert point(analytics(tickets=[dirty]), "wp1").dirty_without_test is True
    before = [quality_test("q1", at(4))]
    assert point(analytics(tickets=[dirty], quality=before), "wp1").dirty_without_test is True
    other_point = [quality_test("q1", at(6), wid="wp2")]
    flagged = analytics(tickets=[dirty], quality=other_point)
    assert point(flagged, "wp1").dirty_without_test is True
    assert flagged.village.dirty_without_test is True
    after = [quality_test("q1", at(6))]
    tested = analytics(tickets=[dirty], quality=after)
    assert point(tested, "wp1").dirty_without_test is False
    assert tested.village.dirty_without_test is False


def test_dirty_without_test_ignores_closed_and_non_dirty_tickets() -> None:
    closed_dirty = repaired("t1", at(5), 6).model_copy(update={"reason": R.DIRTY})
    open_no_supply = ticket("t2", at(5), number=2)
    wp1 = point(analytics(tickets=[closed_dirty, open_no_supply]), "wp1")
    assert wp1.dirty_without_test is False


# --- households ----------------------------------------------------------------------------------


def household(hid: str, status: ConsentStatus | None, *, active: bool = True, **kw) -> Household:
    return Household(
        id=hid,
        village_id=kw.pop("village_id", "v1"),
        phone_e164="+919800000000",
        consent_status=status,
        active=active,
        **kw,
    )


def test_household_consent_breakdown_and_coverage() -> None:
    households = [
        household("h1", ConsentStatus.GRANTED),
        household("h2", ConsentStatus.GRANTED),
        household("h3", ConsentStatus.GRANTED, active=False),
        household("h4", None, consent=Consent(given_at=at(1), channel="voice")),  # pre-v2
        household("h5", ConsentStatus.WITHDRAWN, active=False),
        household("h6", ConsentStatus.DECLINED),
        household("h7", ConsentStatus.NONE),
        household("h8", None),
        household("x1", ConsentStatus.GRANTED, village_id="v2"),
    ]
    hh = analytics(households=households).households
    assert hh.registered == 8
    assert (hh.consented, hh.withdrawn, hh.declined, hh.pending) == (3, 1, 1, 2)
    assert hh.census_households == 50
    assert hh.coverage_pct == 6.0


@pytest.mark.parametrize("census", [None, 0])
def test_coverage_is_none_without_census_households(census: int | None) -> None:
    village = VILLAGE.model_copy(update={"census_households": census})
    result = village_analytics(
        village, START, END, NOW, households=[household("h1", ConsentStatus.GRANTED)]
    )
    assert result.households.consented == 1
    assert result.households.coverage_pct is None
    assert result.households.census_households == census


def call(
    hid: str,
    day: int,
    outcome: CallOutcome,
    water: WaterAnswer | None = None,
    *,
    attempt: int = 1,
    purpose: Purpose = Purpose.DAILY,
    fallback: Fallback | None = None,
) -> CheckIn:
    return CheckIn(
        village_id="v1",
        date=date(2026, 10, day),
        household_id=hid,
        attempt=attempt,
        call_id=f"c-{hid}-{day}-{attempt}-{purpose}",
        purpose=purpose,
        outcome=outcome,
        water=water,
        fallback=fallback,
        captured_at=at(day, 10, attempt),
    )


def test_answer_rate_uses_the_latest_attempt_per_household_and_day() -> None:
    A, U = CallOutcome.ANSWERED, CallOutcome.UNREACHABLE
    checkins = [
        call("h1", 4, U),
        call("h1", 4, A, WaterAnswer.YES, attempt=2),  # answered on retry: counts
        call("h2", 4, A, WaterAnswer.YES),
        call("h2", 4, U, attempt=2),  # latest attempt unreachable: not answered
        call("h3", 4, A, None),  # picked up, no water answer: not answered
        call("h1", 5, A, WaterAnswer.NO),  # same household, another day: called again
        call("h4", 5, CallOutcome.DECLINED),
        call("h5", 5, A, WaterAnswer.YES, purpose=Purpose.VERIFY),  # not a daily call
        call("h6", 2, A, WaterAnswer.YES),  # before the period
    ]
    hh = analytics(checkins=checkins).households
    assert (hh.called, hh.answered) == (5, 2)
    assert hh.answer_rate_pct == 40.0


def test_answer_rate_is_none_when_nobody_was_called() -> None:
    hh = analytics().households
    assert (hh.called, hh.answered, hh.answer_rate_pct) == (0, 0, None)


def test_fallbacks_reports_and_consent_events_in_the_period() -> None:
    A = CallOutcome.ANSWERED
    checkins = [
        call("h1", 4, A, WaterAnswer.NO, fallback=Fallback.BOUGHT),
        call("h2", 4, A, WaterAnswer.NO, fallback=Fallback.OTHER_SOURCE),
        call("h3", 5, A, WaterAnswer.NO, fallback=Fallback.BOUGHT),
        call("h4", 1, A, WaterAnswer.NO, fallback=Fallback.NONE),  # before the period
        call("h5", 6, A, WaterAnswer.NO, purpose=Purpose.REPORT, fallback=Fallback.NONE),
        call("h6", 6, A, WaterAnswer.NO, purpose=Purpose.REPORT),
    ]

    def consent(hid: str, action: ConsentAction, when: datetime) -> ConsentEvent:
        return ConsentEvent(
            village_id="v1",
            household_id=hid,
            phone_masked="+91******0000",
            action=action,
            notice_version="hi-1",
            notice_sha256="0" * 64,
            channel="ivr_keypad",
            at=when,
        )

    consents = [
        consent("h1", ConsentAction.GRANTED, at(3)),
        consent("h2", ConsentAction.GRANTED, at(4)),
        consent("h3", ConsentAction.WITHDRAWN, at(8)),
        consent("h4", ConsentAction.GRANTED, at(1)),  # before the period
    ]
    hh = analytics(checkins=checkins, consents=consents).households
    assert hh.fallback_counts == {"BOUGHT": 2, "NONE": 1, "OTHER_SOURCE": 1}
    assert hh.reports_by_resident == 2
    assert hh.consent_events == {"GRANTED": 2, "WITHDRAWN": 1}


# --- broadcasts ----------------------------------------------------------------------------------


def broadcast(bid: str, state: BroadcastState, sent_at: datetime | None, n: int) -> Broadcast:
    return Broadcast(
        id=bid,
        village_id="v1",
        kind=BroadcastKind.SUPPLY_CHANGE,
        text_hi="Kal paani nahi aayega.",
        state=state,
        created_by="secretary",
        created_at=at(1),
        sent_at=sent_at,
        recipients=n,
        delivered=n - 1,
        heard=n - 2,
    )


def test_broadcasts_count_those_sent_in_the_period() -> None:
    broadcasts = [
        broadcast("b1", BroadcastState.SENT, at(4), 10),
        broadcast("b2", BroadcastState.SENT, at(8), 6),
        broadcast("b3", BroadcastState.SENT, at(1), 50),  # before the period
        broadcast("b4", BroadcastState.APPROVED, None, 2),
        broadcast("b5", BroadcastState.CANCELLED, None, 2),
    ]
    sent = analytics(broadcasts=broadcasts).broadcasts
    assert (sent.sent, sent.recipients, sent.delivered, sent.heard) == (2, 16, 14, 12)


# --- whole result --------------------------------------------------------------------------------


def test_empty_inputs_do_not_crash() -> None:
    result = village_analytics(VILLAGE, START, END, NOW)
    assert result.points == []
    assert result.village.unknown == 7 and result.village.reliability_pct is None
    assert result.village.open_tickets == [] and result.village.last_quality is None
    assert result.households.registered == 0 and result.households.coverage_pct == 0.0
    assert result.broadcasts.sent == 0
    assert (result.tickets_opened, result.tickets_closed_verified) == (0, 0)
    assert result.median_repair_hours is None
    assert result.rule_note == RULE_NOTE
    json.loads(result.model_dump_json())


def test_single_day_period() -> None:
    result = village_analytics(VILLAGE, END, END, NOW, water_points=[WP1])
    assert result.points[0].days_in_period == 1 and result.points[0].unknown == 1


def test_source_tag_and_metadata() -> None:
    days = week([S.SUPPLIED, S.SUPPLIED])
    result = analytics(days=days, freshness=Freshness.SIMULATED)
    assert (result.village_id, result.start, result.end) == ("v1", START, END)
    assert result.generated_at == NOW
    assert result.source.freshness == Freshness.SIMULATED
    assert result.source.fetched_at == NOW
    assert result.source.observed_at == max(d.computed_at for d in days)
    assert analytics().source.freshness == Freshness.DAILY
    assert analytics().source.observed_at is None


def test_rejects_a_reversed_period_and_a_naive_now() -> None:
    with pytest.raises(ValueError, match="before it starts"):
        village_analytics(VILLAGE, END, START, NOW)
    with pytest.raises(ValueError, match="naive"):
        village_analytics(VILLAGE, START, END, datetime(2026, 10, 9, 18))


def test_same_inputs_in_any_order_give_the_same_result() -> None:
    days = week([S.SUPPLIED, S.NO_SUPPLY, S.UNVERIFIED, S.PARTIAL])
    days.append(day_status(END, S.DIRTY, {"wp1": S.SUPPLIED, None: S.DIRTY}))
    tickets = [
        repaired("t1", at(3, 9), 10),
        repaired("t2", at(4, 9), 40, wid="wp2"),
        ticket("t3", at(6), reason=R.DIRTY, number=3),
        ticket("t4", at(6), wid=None, number=4),
    ]
    tests = [quality_test("q1", at(4)), quality_test("q2", at(7), wid="wp2")]
    forward = analytics(days=days, tickets=tickets, quality=tests)
    backward = analytics(days=days[::-1], tickets=tickets[::-1], quality=tests[::-1])
    assert forward.model_dump_json() == backward.model_dump_json()
    assert forward == backward


def test_other_villages_records_are_ignored() -> None:
    foreign = ticket("t1", at(5)).model_copy(update={"village_id": "v2"})
    result = analytics(tickets=[foreign], households=[household("x", None, village_id="v2")])
    assert result.tickets_opened == 0 and result.households.registered == 0
    assert all(p.open_tickets == [] for p in result.points)
