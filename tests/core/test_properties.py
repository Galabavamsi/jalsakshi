"""Property tests for the reconciler and verification (ARCHITECTURE.md §4)."""

from __future__ import annotations

from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from jalsakshi.core.models import (
    CheckIn,
    CleanAnswer,
    DayStatus,
    DayStatusValue,
    Purpose,
    WaterAnswer,
)
from jalsakshi.core.reconcile import is_answered, latest_answers, latest_attempts, reconcile_day
from jalsakshi.core.verify import VerifyOutcome, VerifyResult, evaluate_verification

from .helpers import (
    ANY_CLEAN,
    DAY,
    HOUSEHOLDS,
    NOT_ANSWERED,
    SEVERITY_RANK,
    T0,
    VILLAGE,
    checkin,
    checkins,
)

PROPERTY = settings(max_examples=300, deadline=None)
QUORUMS = st.integers(min_value=1, max_value=4)
CHECKIN_LISTS = st.lists(checkins(), max_size=24)
OUTSIDERS = st.sampled_from([f"u{i}" for i in range(6)])  # never in HOUSEHOLDS


def day_of(checkins: list[CheckIn], quorum: int) -> DayStatus:
    return reconcile_day(checkins, VILLAGE.model_copy(update={"quorum": quorum}), DAY, T0)


def verify_of(checkins: list[CheckIn], quorum: int) -> VerifyResult:
    return evaluate_verification(checkins, quorum)


def next_attempt(checkins: list[CheckIn], household_id: str) -> int:
    """An attempt number that supersedes every existing one for this household (same day)."""
    return max((c.attempt for c in checkins if c.household_id == household_id), default=0) + 1


def later_than(checkins: list[CheckIn], household_id: str) -> datetime:
    """A capture time after every existing answer of this household (r2 orders by time)."""
    times = [c.captured_at for c in checkins if c.household_id == household_id]
    return max(times, default=T0) + timedelta(minutes=1)


# --- unreachable households never create a quorum -----------------------------------------------


@PROPERTY
@given(st.lists(checkins(outcomes=NOT_ANSWERED), max_size=30), QUORUMS)
def test_unanswered_calls_alone_never_reach_quorum(checkins: list[CheckIn], quorum: int) -> None:
    day = day_of(checkins, quorum)
    assert day.status == DayStatusValue.UNVERIFIED
    assert day.counts.answered == day.counts.yes == day.counts.no == 0
    result = verify_of(checkins, quorum)
    assert result.outcome == VerifyOutcome.PENDING
    assert result.yes == result.no == 0


@PROPERTY
@given(CHECKIN_LISTS, st.lists(checkins(household_ids=OUTSIDERS, outcomes=NOT_ANSWERED)), QUORUMS)
def test_adding_unreachable_households_changes_no_decision(
    base: list[CheckIn], extra: list[CheckIn], quorum: int
) -> None:
    before, after = day_of(base, quorum), day_of([*base, *extra], quorum)
    assert after.status == before.status
    ignore_unreachable = {"unreachable": 0}
    assert after.counts.model_copy(update=ignore_unreachable) == before.counts.model_copy(
        update=ignore_unreachable
    )
    assert verify_of([*base, *extra], quorum).outcome == verify_of(base, quorum).outcome


# --- adding a NO answer never improves the status -----------------------------------------------


@PROPERTY
@given(CHECKIN_LISTS, QUORUMS, ANY_CLEAN, st.data())
def test_adding_a_no_answer_never_improves_the_day(
    base: list[CheckIn], quorum: int, clean: CleanAnswer | None, data: st.DataObject
) -> None:
    daily = [c for c in base if c.purpose == Purpose.DAILY]
    silent = sorted(c.household_id for c in latest_answers(daily) if not is_answered(c))
    target = data.draw(st.sampled_from([*silent, "new-household"]), label="household")
    added = checkin(
        target,
        WaterAnswer.NO,
        clean=clean,
        attempt=next_attempt(daily, target),
        captured_at=later_than(base, target),
    )

    before, after = day_of(base, quorum).status, day_of([*base, added], quorum).status

    assert after != DayStatusValue.SUPPLIED  # a household without water rules out SUPPLIED
    if before != DayStatusValue.UNVERIFIED:
        assert after != DayStatusValue.UNVERIFIED
        assert SEVERITY_RANK[after] <= SEVERITY_RANK[before], (before, after)


@PROPERTY
@given(CHECKIN_LISTS, QUORUMS, st.data())
def test_any_no_answer_reopens_verification(
    base: list[CheckIn], quorum: int, data: st.DataObject
) -> None:
    verify = [c for c in base if c.purpose == Purpose.VERIFY]
    target = data.draw(st.sampled_from([*HOUSEHOLDS, "new-household"]), label="household")
    added = checkin(
        target,
        WaterAnswer.NO,
        purpose=Purpose.VERIFY,
        attempt=next_attempt(verify, target),
    )
    assert verify_of([*base, added], quorum).outcome == VerifyOutcome.REOPENED


# --- order and replays do not matter ------------------------------------------------------------


@PROPERTY
@given(CHECKIN_LISTS, QUORUMS, st.data())
def test_result_is_invariant_to_input_order(
    base: list[CheckIn], quorum: int, data: st.DataObject
) -> None:
    shuffled = data.draw(st.permutations(base), label="shuffled")
    assert latest_attempts(shuffled) == latest_attempts(base)
    assert day_of(shuffled, quorum) == day_of(base, quorum)
    assert verify_of(shuffled, quorum) == verify_of(base, quorum)


@PROPERTY
@given(st.lists(checkins(), min_size=1, max_size=24), QUORUMS, st.data())
def test_replayed_checkins_change_nothing(
    base: list[CheckIn], quorum: int, data: st.DataObject
) -> None:
    replays = data.draw(st.lists(st.sampled_from(base), max_size=12), label="replays")
    combined = [*base, *(c.model_copy(deep=True) for c in replays)]
    combined = data.draw(st.permutations(combined), label="combined")
    assert day_of(combined, quorum) == day_of(base, quorum)
    assert verify_of(combined, quorum) == verify_of(base, quorum)


# --- invariants ---------------------------------------------------------------------------------


@PROPERTY
@given(CHECKIN_LISTS, QUORUMS)
def test_counts_are_consistent(base: list[CheckIn], quorum: int) -> None:
    counts = day_of(base, quorum).counts
    households = {c.household_id for c in base if c.purpose == Purpose.DAILY}
    assert counts.answered == counts.yes + counts.no + counts.partial
    assert counts.answered + counts.unreachable <= len(households)
    assert counts.dirty <= counts.answered


@PROPERTY
@given(CHECKIN_LISTS, QUORUMS)
def test_verification_outcome_matches_its_counts(base: list[CheckIn], quorum: int) -> None:
    result = verify_of(base, quorum)
    if result.outcome == VerifyOutcome.CLOSED_VERIFIED:
        assert result.no == 0 and result.yes >= quorum
    elif result.outcome == VerifyOutcome.REOPENED:
        assert result.no > 0
    else:
        assert result.no == 0 and result.yes < quorum
