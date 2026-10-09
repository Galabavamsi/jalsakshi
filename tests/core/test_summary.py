import re
from datetime import date, datetime, timedelta

import pytest

from jalsakshi.core.analytics import (
    BroadcastAnalytics,
    HouseholdAnalytics,
    OpenTicketAge,
    PointAnalytics,
    VillageAnalytics,
    village_analytics,
)
from jalsakshi.core.clock import IST
from jalsakshi.core.models import (
    ConsentStatus,
    DayCounts,
    DayStatus,
    DayStatusValue,
    Freshness,
    Household,
    PointStatus,
    SourceTag,
    TicketReason,
    TicketState,
    Village,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.core.summary import (
    CLOSING_EN,
    CLOSING_HI,
    MAX_CHARS_HI,
    WeeklySummary,
    weekly_summary_text,
)
from jalsakshi.core.tickets import Denied, TicketEventKind, new_ticket, transition

S = DayStatusValue
START, END = date(2026, 10, 5), date(2026, 10, 11)
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=IST)
VILLAGE = Village(
    id="v1",
    name="Pathariya",
    name_hi="Pathariya",
    block="Dhamdha",
    district="Durg",
    census_households=50,
)
WP1 = WaterPoint(
    id="wp1", village_id="v1", kind=WaterPointKind.PIPED, name="Main tap", name_hi="Mukhya nal"
)
WP2 = WaterPoint(id="wp2", village_id="v1", kind=WaterPointKind.HANDPUMP, name="School handpump")
WP3 = WaterPoint(
    id="wp3", village_id="v1", kind=WaterPointKind.PIPED, name="Ward tap", name_hi="Ward nal"
)
WP4 = WaterPoint(
    id="wp4",
    village_id="v1",
    kind=WaterPointKind.BOREWELL,
    name="Temple well",
    name_hi="Mandir kuan",
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def point(wid: str | None, **overrides: object) -> PointAnalytics:
    """A point with 7 days: by default 4 supplied, 1 no supply, 2 unknown."""
    fields: dict[str, object] = {
        "water_point_id": wid,
        "name": None,
        "kind": None,
        "days_in_period": 7,
        "observed": 5,
        "supplied": 4,
        "partial": 0,
        "no_supply": 1,
        "dirty": 0,
        "unknown": 2,
        "reliability_pct": 80.0,
        "complaints_by_reason": {},
        "open_tickets": [],
        "repairs_closed": 0,
        "median_repair_hours": None,
        "worst_repair_hours": None,
        "reopened": 0,
        "blockers": {},
        "last_quality": None,
        "dirty_without_test": False,
    }
    fields.update(overrides)
    return PointAnalytics.model_validate(fields)


def open_ticket(number: int, age_hours: float) -> OpenTicketAge:
    return OpenTicketAge(
        ticket_id=f"t{number}",
        number=number,
        reason=TicketReason.NO_SUPPLY,
        state=TicketState.ASSIGNED,
        age_hours=age_hours,
    )


def made(
    points: list[PointAnalytics],
    *,
    open_tickets: list[OpenTicketAge] | None = None,
    closed: int = 0,
    median: float | None = None,
    registered: int = 40,
    consented: int = 32,
    freshness: Freshness = Freshness.DAILY,
) -> VillageAnalytics:
    """Analytics built by hand, so each test controls the numbers exactly."""
    return VillageAnalytics(
        village_id="v1",
        start=START,
        end=END,
        generated_at=NOW,
        source=SourceTag(source="test", fetched_at=NOW, freshness=freshness),
        rule_note="",
        points=points,
        village=point(None, name="Pathariya", open_tickets=open_tickets or []),
        households=HouseholdAnalytics(
            registered=registered,
            consented=consented,
            withdrawn=0,
            declined=0,
            pending=0,
            census_households=50,
            coverage_pct=None,
            called=0,
            answered=0,
            answer_rate_pct=None,
            fallback_counts={},
            reports_by_resident=0,
            consent_events={},
        ),
        broadcasts=BroadcastAnalytics(sent=0, recipients=0, delivered=0, heard=0),
        tickets_opened=0,
        tickets_closed_verified=closed,
        median_repair_hours=median,
    )


def summary(analytics: VillageAnalytics, points: list[WaterPoint] | None = None) -> WeeklySummary:
    return weekly_summary_text(
        VILLAGE, analytics, [WP1, WP2, WP3, WP4] if points is None else points
    )


def numbers_in(text: str) -> set[float]:
    return {float(n) for n in NUMBER.findall(text)}


def assert_numbers_covered(result: WeeklySummary) -> None:
    known = {float(v) for v in result.numbers.values() if v is not None}
    assert numbers_in(result.text_hi) <= known, (result.text_hi, result.numbers)
    assert numbers_in(result.text_en) <= known, (result.text_en, result.numbers)


def sentences(text: str) -> int:
    return text.count(".")


def realistic() -> VillageAnalytics:
    """Analytics computed from records, end to end."""

    def day(offset: int, wp1: DayStatusValue, wp2: DayStatusValue) -> DayStatus:
        return DayStatus(
            village_id="v1",
            date=START + timedelta(days=offset),
            status=S.SUPPLIED,
            counts=DayCounts(),
            rule_version="r2",
            computed_at=NOW,
            points=[
                PointStatus(water_point_id="wp1", status=wp1, counts=DayCounts()),
                PointStatus(water_point_id="wp2", status=wp2, counts=DayCounts()),
            ],
        )

    days = [
        day(0, S.SUPPLIED, S.NO_SUPPLY),
        day(1, S.SUPPLIED, S.NO_SUPPLY),
        day(2, S.PARTIAL, S.SUPPLIED),
        day(3, S.NO_SUPPLY, S.UNVERIFIED),
        day(5, S.SUPPLIED, S.DIRTY),
    ]
    opened = datetime(2026, 10, 6, 9, 0, tzinfo=IST)
    fixed = new_ticket("v1", TicketReason.NO_SUPPLY, opened, ticket_id="t1")
    for kind, hours in [
        (TicketEventKind.NOTIFIED, 1),
        (TicketEventKind.OPERATOR_FIXED, 10),
        (TicketEventKind.VERIFY_STARTED, 11),
        (TicketEventKind.VERIFIED_OK, 26),
    ]:
        step = transition(fixed, kind, "tester", opened + timedelta(hours=hours))
        assert not isinstance(step, Denied)
        fixed = step
    still_open = new_ticket(
        "v1", TicketReason.DIRTY, datetime(2026, 10, 9, 8, tzinfo=IST), ticket_id="t2"
    ).model_copy(update={"water_point_id": "wp2", "number": 2})
    households = [
        Household(
            id=f"h{i}",
            village_id="v1",
            phone_e164=f"+9198000000{i:02d}",
            consent_status=ConsentStatus.GRANTED if i < 9 else ConsentStatus.NONE,
        )
        for i in range(12)
    ]
    return village_analytics(
        VILLAGE,
        START,
        END,
        NOW,
        water_points=[WP1, WP2],
        days=days,
        tickets=[fixed.model_copy(update={"water_point_id": "wp1", "number": 1}), still_open],
        households=households,
    )


# --- the whole text ------------------------------------------------------------------------------


def test_every_number_in_the_text_is_in_numbers() -> None:
    result = summary(realistic(), [WP1, WP2])
    assert_numbers_covered(result)
    assert result.numbers["households_registered"] == 12
    assert result.numbers["households_consented"] == 9
    assert result.numbers["open_complaints"] == 1
    assert result.numbers["closed_verified"] == 1
    assert result.numbers["median_repair_hours"] == 26
    assert result.numbers["days"] == 7


def test_realistic_text_reads_as_expected() -> None:
    result = summary(realistic(), [WP1, WP2])
    assert result.text_hi == (
        "Namaste, Pathariya gaon ki saptahik JalSakshi report: 12 ghar jude hain, "
        "9 ne sahmati di hai. "
        "Pichhle 7 din mein School handpump: 1 din paani aaya, 2 din nahi aaya, "
        "1 din gandla paani, 3 din ki jaankari nahi. "
        "Pichhle 7 din mein Mukhya nal: 3 din paani aaya, 1 din nahi aaya, 1 din thoda aaya, "
        "2 din ki jaankari nahi. "
        "1 shikayat 3 din se khuli hai. "
        "1 shikayat gharon ki pushti ke baad band hui, marammat mein aam taur par 26 ghante lage. "
        "Poori report JalSakshi console par hai."
    )
    assert result.text_en.startswith("Namaste, weekly JalSakshi report for Pathariya: ")
    assert "Last 7 days at School handpump: water came on 1 day, did not come on 2" in (
        result.text_en
    )
    assert result.text_en.endswith(CLOSING_EN)


def test_same_input_gives_the_same_text() -> None:
    first, second = summary(realistic()), summary(realistic())
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_length_and_sentence_count_with_three_points() -> None:
    analytics = made(
        [
            point("wp1", reliability_pct=80.0),
            point("wp2", reliability_pct=50.0),
            point("wp3", reliability_pct=60.0),
        ],
        open_tickets=[open_ticket(1, 30)],
        closed=2,
        median=12.0,
    )
    result = summary(analytics)
    assert len(result.text_hi) <= MAX_CHARS_HI
    assert 5 <= sentences(result.text_hi) <= 7
    assert sentences(result.text_hi) == sentences(result.text_en) == 7
    assert_numbers_covered(result)


def test_metadata_is_copied_from_the_analytics() -> None:
    analytics = made([point("wp1")])
    result = summary(analytics)
    assert (result.village_id, result.start, result.end) == ("v1", START, END)
    assert result.source == analytics.source


# --- greeting and closing ------------------------------------------------------------------------


def test_greeting_names_the_village_and_its_households() -> None:
    village = VILLAGE.model_copy(update={"name_hi": "पथरिया"})
    result = weekly_summary_text(village, made([point("wp1")], registered=40, consented=32), [WP1])
    assert result.text_hi.startswith(
        "Namaste, पथरिया gaon ki saptahik JalSakshi report: 40 ghar jude hain, 32 ne sahmati"
    )
    assert "report for Pathariya: 40 households registered, 32 consented." in result.text_en
    assert result.text_hi.endswith(CLOSING_HI)


def test_greeting_falls_back_to_the_english_village_name() -> None:
    village = VILLAGE.model_copy(update={"name_hi": None, "name": "Kutelabhatha"})
    result = weekly_summary_text(village, made([point("wp1")]), [WP1])
    assert result.text_hi.startswith("Namaste, Kutelabhatha gaon ki")


@pytest.mark.parametrize("freshness", [Freshness.SIMULATED, Freshness.REPLAY])
def test_demo_data_is_labelled(freshness: Freshness) -> None:
    result = summary(made([point("wp1")], freshness=freshness))
    assert f"JalSakshi report, {freshness.value} data se:" in result.text_hi
    assert f"for Pathariya, from {freshness.value} data:" in result.text_en
    assert "data" not in summary(made([point("wp1")])).text_hi


# --- points --------------------------------------------------------------------------------------


def test_point_sentence_follows_the_template() -> None:
    result = summary(made([point("wp1")]))
    assert (
        "Pichhle 7 din mein Mukhya nal: 4 din paani aaya, 1 din nahi aaya, 2 din ki jaankari nahi."
    ) in result.text_hi
    assert (
        "Last 7 days at Main tap: water came on 4 days, did not come on 1, no information for 2."
    ) in result.text_en


def test_point_uses_name_hi_else_name() -> None:
    result = summary(made([point("wp1"), point("wp2")]))
    assert "Mukhya nal:" in result.text_hi and "School handpump:" in result.text_hi
    assert "Main tap:" in result.text_en and "School handpump:" in result.text_en


def test_point_missing_from_water_points_uses_its_analytics_name_or_id() -> None:
    analytics = made([point("wp7", name="Pond pump"), point("wp8")])
    result = summary(analytics, [])
    assert "Pond pump:" in result.text_hi and "wp8:" in result.text_hi


def test_partial_and_dirty_days_are_spoken_when_present() -> None:
    p = point("wp1", observed=7, supplied=3, partial=2, dirty=1, no_supply=1, unknown=0)
    result = summary(made([p]))
    assert (
        "3 din paani aaya, 1 din nahi aaya, 2 din thoda aaya, 1 din gandla paani, "
        "0 din ki jaankari nahi."
    ) in result.text_hi
    assert "partly on 2, dirty on 1" in result.text_en
    assert_numbers_covered(result)


def test_point_with_no_observed_days_says_no_information() -> None:
    p = point("wp2", observed=0, supplied=0, no_supply=0, unknown=7, reliability_pct=None)
    result = summary(made([p]))
    assert "Pichhle 7 din mein School handpump ki jaankari nahi mili." in result.text_hi
    assert "Last 7 days at School handpump: no information received." in result.text_en
    assert "wp2.supplied" not in result.numbers


def test_points_worst_reliability_first_at_most_three() -> None:
    points = [
        point("wp1", reliability_pct=90.0),
        point("wp2", reliability_pct=40.0),
        point("wp3", observed=0, supplied=0, no_supply=0, unknown=7, reliability_pct=None),
        point("wp4", reliability_pct=70.0),
    ]
    text = summary(made(points)).text_hi
    order = [text.find(name) for name in ("School handpump", "Mandir kuan", "Mukhya nal")]
    assert -1 not in order and order == sorted(order)
    assert "Ward nal" not in text  # no data: ranked last, beyond the three


def test_reliability_ties_put_more_no_supply_days_first() -> None:
    points = [point("wp1", reliability_pct=50.0), point("wp2", reliability_pct=50.0, no_supply=3)]
    text = summary(made(points)).text_hi
    assert text.find("School handpump") < text.find("Mukhya nal")


def test_long_names_drop_the_best_points_to_fit_the_budget() -> None:
    long = [
        wp.model_copy(update={"name_hi": wp.name + " " + "lambi gali ke paas wala nal " * 4})
        for wp in (WP1, WP2, WP3)
    ]
    points = [
        point("wp1", reliability_pct=90.0),
        point("wp2", reliability_pct=10.0, supplied=1),
        point("wp3", reliability_pct=50.0),
    ]
    result = summary(made(points), long)
    assert "School handpump" in result.text_hi  # the worst point is always kept
    assert "Main tap" not in result.text_hi
    assert "wp1.supplied" not in result.numbers
    assert result.numbers["wp2.supplied"] == 1


def test_none_group_is_the_rest_of_the_village_next_to_named_points() -> None:
    points = [point("wp1", reliability_pct=90.0), point(None, reliability_pct=20.0)]
    result = summary(made(points))
    assert "Pichhle 7 din mein baaki gaon: 4 din paani aaya" in result.text_hi
    assert "Last 7 days at the rest of the village:" in result.text_en


def test_none_group_alone_is_the_village() -> None:
    result = summary(made([point(None)]))
    assert "Pichhle 7 din mein Pathariya gaon: 4 din paani aaya" in result.text_hi
    assert result.numbers["village.supplied"] == 4


# --- complaints ----------------------------------------------------------------------------------


def test_open_complaints_with_the_oldest_age_in_days() -> None:
    result = summary(made([point("wp1")], open_tickets=[open_ticket(1, 5), open_ticket(2, 80.5)]))
    assert "2 shikayat khuli hain, sabse purani 3 din se." in result.text_hi
    assert "2 complaints are open; the oldest for 3 days." in result.text_en
    assert result.numbers["open_complaints"] == 2
    assert result.numbers["oldest_open_days"] == 3


@pytest.mark.parametrize(
    ("age", "hindi", "english"),
    [
        (5.9, "1 shikayat 5 ghante se khuli hai.", "1 complaint is open, for 5 hours."),
        (0.4, "1 shikayat kuch der se khuli hai.", "1 complaint is open, for under an hour."),
        (24.0, "1 shikayat 1 din se khuli hai.", "1 complaint is open, for 1 day."),
    ],
)
def test_one_open_complaint(age: float, hindi: str, english: str) -> None:
    result = summary(made([point("wp1")], open_tickets=[open_ticket(1, age)]))
    assert hindi in result.text_hi
    assert english in result.text_en
    assert_numbers_covered(result)


def test_no_open_complaints() -> None:
    result = summary(made([point("wp1")]))
    assert "Abhi koi shikayat khuli nahi hai." in result.text_hi
    assert result.numbers["open_complaints"] == 0


def test_closed_complaints_with_median_repair_time() -> None:
    result = summary(made([point("wp1")], closed=3, median=20.5))
    assert (
        "3 shikayat gharon ki pushti ke baad band hui, marammat mein aam taur par 21 ghante lage."
    ) in result.text_hi
    assert "3 complaints closed after households confirmed water was back; median repair " in (
        result.text_en
    )
    assert result.numbers["closed_verified"] == 3
    assert result.numbers["median_repair_hours"] == 21


def test_closed_complaint_repaired_within_the_hour() -> None:
    result = summary(made([point("wp1")], closed=1, median=0.3))
    assert "ek ghante se kam laga." in result.text_hi
    assert "median_repair_hours" not in result.numbers
    assert_numbers_covered(result)


def test_no_closed_complaints() -> None:
    result = summary(made([point("wp1")]))
    assert "Is dauran koi shikayat gharon ki pushti se band nahi hui." in result.text_hi
    assert result.numbers["closed_verified"] == 0


# --- empty ---------------------------------------------------------------------------------------


def test_empty_analytics_does_not_crash() -> None:
    analytics = village_analytics(VILLAGE, START, END, NOW)
    result = weekly_summary_text(VILLAGE, analytics, [])
    assert "Pichhle 7 din mein Pathariya gaon ki jaankari nahi mili." in result.text_hi
    assert "0 ghar jude hain, 0 ne sahmati di hai." in result.text_hi
    assert sentences(result.text_hi) == 5
    assert_numbers_covered(result)
