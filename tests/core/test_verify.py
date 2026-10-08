from datetime import timedelta

import pytest
from pydantic import ValidationError

from jalsakshi.core.models import CallOutcome, CheckIn, Purpose, WaterAnswer
from jalsakshi.core.tickets import TicketEventKind
from jalsakshi.core.verify import (
    VerifyOutcome,
    VerifyResult,
    evaluate_verification,
    ticket_event_for,
)

from .helpers import DAY, T0, answers, checkin, unreachable

YES, NO, PARTIAL = WaterAnswer.YES, WaterAnswer.NO, WaterAnswer.PARTIAL
VERIFY = Purpose.VERIFY


def verify_answers(*waters: WaterAnswer) -> list[CheckIn]:
    return answers(*waters, purpose=VERIFY)


def test_quorum_of_yes_closes() -> None:
    assert evaluate_verification(verify_answers(YES, YES), 2) == VerifyResult(
        outcome=VerifyOutcome.CLOSED_VERIFIED, yes=2, no=0, unreachable=0
    )


def test_any_no_reopens_even_with_a_yes_quorum() -> None:
    result = evaluate_verification(verify_answers(YES, YES, YES, NO), 2)
    assert (result.outcome, result.yes, result.no) == (VerifyOutcome.REOPENED, 3, 1)


def test_too_few_yes_stays_pending() -> None:
    result = evaluate_verification(
        [*verify_answers(YES), *unreachable("u0", "u1", purpose=VERIFY)], 2
    )
    assert result == VerifyResult(outcome=VerifyOutcome.PENDING, yes=1, no=0, unreachable=2)


def test_unreachable_and_declined_never_confirm() -> None:
    stray = [
        checkin("u0", YES, outcome=CallOutcome.UNREACHABLE, purpose=VERIFY),
        checkin("u1", YES, outcome=CallOutcome.DECLINED, purpose=VERIFY),
        checkin("u2", NO, outcome=CallOutcome.DECLINED, purpose=VERIFY),
    ]
    assert evaluate_verification(stray, 1) == VerifyResult(
        outcome=VerifyOutcome.PENDING, yes=0, no=0, unreachable=1
    )


def test_partial_neither_confirms_nor_reopens() -> None:
    assert evaluate_verification(verify_answers(PARTIAL, PARTIAL, YES), 2).outcome == (
        VerifyOutcome.PENDING
    )


def test_daily_answers_are_ignored() -> None:
    assert evaluate_verification(answers(YES, YES, YES), 2).outcome == VerifyOutcome.PENDING
    daily_no = [*answers(NO), *verify_answers(YES, YES)]
    assert evaluate_verification(daily_no, 2).outcome == VerifyOutcome.CLOSED_VERIFIED


def test_latest_attempt_per_household_decides() -> None:
    retry = [
        checkin("h0", NO, attempt=1, purpose=VERIFY),
        checkin("h0", YES, attempt=2, purpose=VERIFY),
        checkin("h1", YES, purpose=VERIFY),
    ]
    assert evaluate_verification(retry, 2).outcome == VerifyOutcome.CLOSED_VERIFIED
    assert evaluate_verification(retry[::-1], 2).outcome == VerifyOutcome.CLOSED_VERIFIED


def test_a_later_day_supersedes_an_earlier_day() -> None:
    yesterday = checkin("h0", NO, attempt=2, purpose=VERIFY, day=DAY - timedelta(days=1))
    today = checkin("h0", YES, attempt=1, purpose=VERIFY)
    assert evaluate_verification([today, yesterday], 1).outcome == VerifyOutcome.CLOSED_VERIFIED


def test_since_drops_answers_from_an_earlier_round() -> None:
    old_round = [checkin("h0", NO, purpose=VERIFY, captured_at=T0 - timedelta(hours=3))]
    new_round = [
        checkin(f"n{i}", YES, purpose=VERIFY, captured_at=T0 + timedelta(minutes=i))
        for i in range(2)
    ]
    rounds = [*old_round, *new_round]
    assert evaluate_verification(rounds, 2).outcome == VerifyOutcome.REOPENED
    assert evaluate_verification(rounds, 2, since=T0).outcome == VerifyOutcome.CLOSED_VERIFIED


def test_picked_up_without_answer_is_not_a_yes() -> None:
    silent = [checkin(f"s{i}", None, purpose=VERIFY) for i in range(3)]
    assert evaluate_verification(silent, 1).outcome == VerifyOutcome.PENDING


def test_bad_quorum_rejected() -> None:
    with pytest.raises(ValueError, match="quorum"):
        evaluate_verification([], 0)


def test_result_is_immutable() -> None:
    result = evaluate_verification([], 1)
    with pytest.raises(ValidationError):
        result.yes = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    ("outcome", "event"),
    [
        (VerifyOutcome.CLOSED_VERIFIED, TicketEventKind.VERIFIED_OK),
        (VerifyOutcome.REOPENED, TicketEventKind.VERIFY_FAILED),
        (VerifyOutcome.PENDING, None),
    ],
)
def test_ticket_event_for(outcome: VerifyOutcome, event: TicketEventKind | None) -> None:
    assert ticket_event_for(outcome) == event
