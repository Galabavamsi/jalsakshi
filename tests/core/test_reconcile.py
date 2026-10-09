from datetime import timedelta

import pytest

from jalsakshi.core.models import (
    CallOutcome,
    CheckIn,
    CleanAnswer,
    DayCounts,
    DayStatusValue,
    Purpose,
    TicketReason,
    WaterAnswer,
)
from jalsakshi.core.reconcile import (
    RULE_VERSION,
    count_answers,
    latest_attempts,
    reconcile_day,
    should_open_ticket,
    status_for,
)

from .helpers import DAY, T0, VILLAGE, answers, checkin, unreachable

YES, NO, PARTIAL = WaterAnswer.YES, WaterAnswer.NO, WaterAnswer.PARTIAL
DIRTY_WATER = CleanAnswer.NO
S = DayStatusValue


def status(checkins: list[CheckIn], quorum: int = 2) -> DayStatusValue:
    village = VILLAGE.model_copy(update={"quorum": quorum})
    return reconcile_day(checkins, village, DAY, T0).status


# --- rule table, one test per row (quorum 2 unless stated) -------------------------------------


@pytest.mark.parametrize(
    "checkins",
    [
        [],
        answers(YES),
        answers(NO) + unreachable("u1", "u2", "u3"),
        answers(YES) + [checkin("d1", outcome=CallOutcome.DECLINED)] * 3,
    ],
    ids=["nobody", "one-yes", "one-no-plus-unreachable", "one-yes-plus-declined"],
)
def test_row1_unverified_when_answered_below_quorum(checkins: list[CheckIn]) -> None:
    assert status(checkins) == S.UNVERIFIED


def test_row1_boundary_answered_equal_to_quorum_is_verified() -> None:
    assert status(answers(YES, YES)) == S.SUPPLIED
    assert status(answers(YES, YES), quorum=3) == S.UNVERIFIED
    assert status(answers(YES, YES, YES), quorum=3) == S.SUPPLIED


@pytest.mark.parametrize(
    "waters",
    [(NO, NO), (NO, NO, NO), (NO, NO, YES, PARTIAL), (NO, NO, NO, YES, YES)],
    ids=["two-no", "three-no", "no-equals-yes-plus-partial", "no-majority"],
)
def test_row2_no_supply(waters: tuple[WaterAnswer, ...]) -> None:
    assert status(answers(*waters)) == S.NO_SUPPLY


def test_row2_needs_no_to_reach_quorum() -> None:
    # 1 NO with quorum 2: not NO_SUPPLY even though NO is the only answer besides a PARTIAL.
    assert status(answers(NO, PARTIAL)) == S.PARTIAL


def test_row2_needs_no_to_outweigh_yes_plus_partial() -> None:
    assert status(answers(NO, NO, YES, YES, PARTIAL)) == S.PARTIAL


def test_row2_beats_row3_when_both_hold() -> None:
    dirty_yes = [checkin(f"d{i}", YES, clean=DIRTY_WATER) for i in range(2)]
    assert status(answers(NO, NO) + dirty_yes) == S.NO_SUPPLY


def test_row3_dirty() -> None:
    dirty = [checkin(f"d{i}", YES, clean=DIRTY_WATER) for i in range(2)]
    assert status(dirty) == S.DIRTY


def test_row3_beats_row4() -> None:
    mixed = [checkin("d0", PARTIAL, clean=DIRTY_WATER), checkin("d1", YES, clean=DIRTY_WATER)]
    assert status(mixed) == S.DIRTY


def test_row3_needs_dirty_to_reach_quorum() -> None:
    mixed = [checkin("d0", YES, clean=DIRTY_WATER), checkin("d1", YES, clean=CleanAnswer.YES)]
    assert status(mixed) == S.SUPPLIED


@pytest.mark.parametrize(
    "waters",
    [(YES, PARTIAL), (PARTIAL, PARTIAL), (YES, YES, NO), (YES, NO, PARTIAL)],
    ids=["one-partial", "all-partial", "single-no", "no-and-partial"],
)
def test_row4_partial(waters: tuple[WaterAnswer, ...]) -> None:
    assert status(answers(*waters)) == S.PARTIAL


@pytest.mark.parametrize("waters", [(YES, YES), (YES, YES, YES, YES)])
def test_row5_supplied(waters: tuple[WaterAnswer, ...]) -> None:
    assert status(answers(*waters)) == S.SUPPLIED


def test_status_for_rejects_bad_quorum() -> None:
    with pytest.raises(ValueError, match="quorum"):
        status_for(DayCounts(), 0)


# --- what counts --------------------------------------------------------------------------------


def test_counts_and_metadata() -> None:
    checkins = [
        checkin("h0", YES, clean=CleanAnswer.YES),
        checkin("h1", PARTIAL, clean=DIRTY_WATER),
        checkin("h2", NO),
        checkin("h3", outcome=CallOutcome.UNREACHABLE),
        checkin("h4", outcome=CallOutcome.DECLINED),
        checkin("h5", None, outcome=CallOutcome.ANSWERED),
    ]
    day = reconcile_day(checkins, VILLAGE, DAY, T0)
    assert day.counts == DayCounts(answered=3, yes=1, no=1, partial=1, dirty=1, unreachable=1)
    assert (day.village_id, day.date, day.rule_version, day.computed_at) == (
        "v1",
        DAY,
        RULE_VERSION,
        T0,
    )
    assert RULE_VERSION == "r2"


def test_unanswered_calls_never_count_even_with_stray_answers() -> None:
    stray = [
        checkin("u0", YES, outcome=CallOutcome.UNREACHABLE),
        checkin("u1", YES, clean=CleanAnswer.YES, outcome=CallOutcome.DECLINED),
        checkin("u2", NO, outcome=CallOutcome.UNREACHABLE),
    ]
    day = reconcile_day(stray, VILLAGE, DAY, T0)
    assert day.status == S.UNVERIFIED
    assert day.counts == DayCounts(unreachable=2)


def test_picked_up_without_a_water_answer_is_not_evidence() -> None:
    silent = [checkin(f"s{i}", None) for i in range(3)]
    assert status(silent) == S.UNVERIFIED


def test_only_daily_purpose_for_this_village_and_day_counts() -> None:
    others = [
        *answers(NO, NO, purpose=Purpose.VERIFY),
        checkin("x0", NO, village_id="v2"),
        checkin("x1", NO, village_id="v2"),
        checkin("x2", NO, day=DAY - timedelta(days=1)),
        checkin("x3", NO, day=DAY - timedelta(days=1)),
    ]
    assert status(others) == S.UNVERIFIED
    assert status([*others, *answers(YES, YES)]) == S.SUPPLIED


# --- latest attempt per household ---------------------------------------------------------------


def test_retry_after_unreachable_counts() -> None:
    checkins = [
        checkin("h0", outcome=CallOutcome.UNREACHABLE, attempt=1),
        checkin("h0", YES, attempt=2),
        checkin("h1", YES),
    ]
    day = reconcile_day(checkins, VILLAGE, DAY, T0)
    assert day.status == S.SUPPLIED
    assert day.counts.unreachable == 0


def test_latest_attempt_wins_regardless_of_input_order() -> None:
    first, second = checkin("h0", NO, attempt=1), checkin("h0", YES, attempt=2)
    assert latest_attempts([first, second]) == [second]
    assert latest_attempts([second, first]) == [second]


def test_same_attempt_tie_breaks_on_capture_time() -> None:
    early = checkin("h0", NO, captured_at=T0)
    late = checkin("h0", YES, captured_at=T0 + timedelta(seconds=1))
    assert latest_attempts([late, early]) == [late]
    assert latest_attempts([early, late]) == [late]


def test_exact_duplicates_collapse() -> None:
    dup = checkin("h0", NO)
    assert latest_attempts([dup, dup, dup]) == [dup]
    assert count_answers(latest_attempts([dup] * 5)).no == 1


def test_latest_attempts_sorted_by_household() -> None:
    result = latest_attempts([checkin("h2", YES), checkin("h0", YES), checkin("h1", YES)])
    assert [c.household_id for c in result] == ["h0", "h1", "h2"]


# --- ticket trigger -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day_status", "has_open", "expected"),
    [
        (S.NO_SUPPLY, False, TicketReason.NO_SUPPLY),
        (S.DIRTY, False, TicketReason.DIRTY),
        (S.NO_SUPPLY, True, None),
        (S.DIRTY, True, None),
        *[(s, o, None) for s in (S.SUPPLIED, S.PARTIAL, S.UNVERIFIED) for o in (False, True)],
    ],
)
def test_should_open_ticket(
    day_status: DayStatusValue, has_open: bool, expected: TicketReason | None
) -> None:
    assert should_open_ticket(day_status, has_open) == expected
