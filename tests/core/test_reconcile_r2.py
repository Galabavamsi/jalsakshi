"""Reconciler r2: water points, resident reports and the village's worst status (§15.2)."""

from __future__ import annotations

from datetime import timedelta

from jalsakshi.core.models import (
    CheckIn,
    CleanAnswer,
    DayStatusValue,
    Purpose,
    TicketReason,
    WaterAnswer,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.core.reconcile import reconcile_day, tickets_to_open, worst_status

from .helpers import DAY, T0, VILLAGE, checkin

TAP = WaterPoint(id="wp-tap", village_id="v1", kind=WaterPointKind.PIPED, name="Piped supply")
PUMP = WaterPoint(id="wp-hp", village_id="v1", kind=WaterPointKind.HANDPUMP, name="Handpump 1")


def at(point: str | None, household: str, water: WaterAnswer, **kw: object) -> CheckIn:
    base = checkin(household, water, **kw)  # type: ignore[arg-type]
    return base.model_copy(update={"water_point_id": point})


def test_each_point_gets_its_own_status_and_the_village_takes_the_worst() -> None:
    checkins = [
        at("wp-tap", "h1", WaterAnswer.NO),
        at("wp-tap", "h2", WaterAnswer.NO),
        at("wp-hp", "h3", WaterAnswer.YES),
        at("wp-hp", "h4", WaterAnswer.YES),
    ]
    day = reconcile_day(checkins, VILLAGE, DAY, T0, [TAP, PUMP])
    by_point = {p.water_point_id: p.status for p in day.points}
    assert by_point == {"wp-tap": DayStatusValue.NO_SUPPLY, "wp-hp": DayStatusValue.SUPPLIED}
    assert day.status is DayStatusValue.NO_SUPPLY
    assert day.counts.answered == 4
    assert day.rule_version == "r2"


def test_points_without_answers_are_unverified_and_do_not_decide_the_village() -> None:
    checkins = [at("wp-tap", "h1", WaterAnswer.YES), at("wp-tap", "h2", WaterAnswer.YES)]
    day = reconcile_day(checkins, VILLAGE, DAY, T0, [TAP, PUMP])
    assert [p.status for p in day.points] == [DayStatusValue.SUPPLIED, DayStatusValue.UNVERIFIED]
    assert day.status is DayStatusValue.SUPPLIED


def test_no_evidence_anywhere_is_unverified() -> None:
    day = reconcile_day([at("wp-tap", "h1", WaterAnswer.NO)], VILLAGE, DAY, T0, [TAP])
    assert day.status is DayStatusValue.UNVERIFIED


def test_a_later_resident_report_overrides_the_morning_call() -> None:
    morning = at("wp-tap", "h1", WaterAnswer.YES)
    report = at(
        "wp-tap",
        "h1",
        WaterAnswer.NO,
        purpose=Purpose.REPORT,
        captured_at=T0 + timedelta(hours=5),
    )
    other = at("wp-tap", "h2", WaterAnswer.NO)
    day = reconcile_day([morning, report, other], VILLAGE, DAY, T0, [TAP])
    assert day.status is DayStatusValue.NO_SUPPLY
    assert day.counts.no == 2


def test_verify_answers_do_not_describe_the_day() -> None:
    verify = at("wp-tap", "h1", WaterAnswer.NO, purpose=Purpose.VERIFY)
    day = reconcile_day([verify], VILLAGE.model_copy(update={"quorum": 1}), DAY, T0, [TAP])
    assert day.status is DayStatusValue.UNVERIFIED


def test_households_without_a_point_form_their_own_group() -> None:
    checkins = [at(None, "h1", WaterAnswer.NO), at(None, "h2", WaterAnswer.NO)]
    day = reconcile_day(checkins, VILLAGE, DAY, T0)
    assert [(p.water_point_id, p.status) for p in day.points] == [(None, DayStatusValue.NO_SUPPLY)]
    assert day.status is DayStatusValue.NO_SUPPLY


def test_point_quorum_overrides_the_village_quorum() -> None:
    lone = PUMP.model_copy(update={"quorum": 1})
    day = reconcile_day([at("wp-hp", "h3", WaterAnswer.NO)], VILLAGE, DAY, T0, [lone])
    assert day.status is DayStatusValue.NO_SUPPLY


def test_tickets_to_open_skips_points_with_an_open_ticket() -> None:
    checkins = [
        at("wp-tap", "h1", WaterAnswer.NO),
        at("wp-tap", "h2", WaterAnswer.NO),
        at("wp-hp", "h3", WaterAnswer.YES, clean=CleanAnswer.NO),
        at("wp-hp", "h4", WaterAnswer.YES, clean=CleanAnswer.NO),
    ]
    day = reconcile_day(checkins, VILLAGE, DAY, T0, [TAP, PUMP])
    assert tickets_to_open(day, []) == [
        ("wp-tap", TicketReason.NO_SUPPLY),
        ("wp-hp", TicketReason.DIRTY),
    ]
    assert tickets_to_open(day, [("wp-tap", TicketReason.NO_SUPPLY)]) == [
        ("wp-hp", TicketReason.DIRTY)
    ]


def test_worst_status_order() -> None:
    assert worst_status([]) is DayStatusValue.UNVERIFIED
    assert (
        worst_status([DayStatusValue.SUPPLIED, DayStatusValue.DIRTY, DayStatusValue.PARTIAL])
        is DayStatusValue.DIRTY
    )
