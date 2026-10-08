"""IVR state machine: every flow path, re-prompts, timeouts and result mapping."""

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from jalsakshi.core.models import (
    CallOutcome,
    CheckIn,
    CleanAnswer,
    Purpose,
    TicketReason,
    WaterAnswer,
)
from jalsakshi.voice.actions import Action, GetDigits, Hangup, Play, Record
from jalsakshi.voice.catalog import default_catalog
from jalsakshi.voice.flow import (
    FlowSession,
    FlowStep,
    current_actions,
    on_input,
    result_to_checkin_fields,
    result_to_operator,
    start,
    with_recording,
)

TIMEOUT = "<timeout>"


def daily() -> FlowSession:
    return FlowSession(call_id="call-1", purpose=Purpose.DAILY, household_id="hh-1")


def verify() -> FlowSession:
    return FlowSession(call_id="call-2", purpose=Purpose.VERIFY, household_id="hh-1")


def operator(reason: TicketReason = TicketReason.NO_SUPPLY, households: int = 3) -> FlowSession:
    return FlowSession(
        call_id="call-3",
        purpose=Purpose.OPERATOR,
        operator_id="op-1",
        ticket_id="t-1",
        ticket_reason=reason,
        reported_households=households,
    )


def feed(session: FlowSession, *inputs: str) -> tuple[FlowSession, list[Action], bool]:
    """Start the call, then apply inputs ("<timeout>" means a timeout)."""
    session, actions = start(session)
    done = False
    for value in inputs:
        if value == TIMEOUT:
            session, actions, done = on_input(session, None, timeout=True)
        else:
            session, actions, done = on_input(session, value)
    return session, actions, done


def keys(actions: list[Action]) -> list[str]:
    """Prompt keys in play order, including prompts nested in GetDigits."""
    out: list[str] = []
    for action in actions:
        if isinstance(action, Play):
            out.append(action.prompt_key)
        elif isinstance(action, GetDigits):
            out.extend(p.prompt_key for p in action.prompts)
    return out


def asked(actions: list[Action]) -> str:
    """The question a GetDigits batch is asking."""
    last = actions[-1]
    assert isinstance(last, GetDigits)
    return last.prompts[-1].prompt_key


# --- DAILY ---------------------------------------------------------------------------------


def test_daily_start_greets_then_asks_water() -> None:
    session, actions = start(daily())
    assert session.step is FlowStep.Q_WATER
    assert keys(actions) == ["household.greet", "household.q_water"]
    gather = actions[-1]
    assert isinstance(gather, GetDigits)
    assert gather.num_digits == 1
    assert gather.timeout_s == 10


@pytest.mark.parametrize("digit", ["1", "3"])
def test_daily_water_came_asks_hours(digit: str) -> None:
    session, actions, done = feed(daily(), digit)
    assert session.step is FlowStep.Q_HOURS
    assert asked(actions) == "household.q_hours"
    assert not done


def test_daily_no_water_skips_to_note() -> None:
    session, actions, done = feed(daily(), "2")
    assert session.step is FlowStep.Q_NOTE
    assert session.answers.water is WaterAnswer.NO
    assert keys(actions) == ["household.q_note"]
    assert isinstance(actions[-1], Record)
    assert actions[-1].max_s == 15
    assert not done


@pytest.mark.parametrize("hours", range(10))
def test_daily_hours_every_key(hours: int) -> None:
    session, actions, _ = feed(daily(), "1", str(hours))
    assert session.answers.hours == hours
    assert asked(actions) == "household.q_clean"


@pytest.mark.parametrize(("digit", "clean"), [("1", CleanAnswer.YES), ("2", CleanAnswer.NO)])
def test_daily_clean_keys(digit: str, clean: CleanAnswer) -> None:
    session, actions, _ = feed(daily(), "3", "4", digit)
    assert session.answers.clean is clean
    assert session.step is FlowStep.Q_NOTE
    assert isinstance(actions[-1], Record)


@pytest.mark.parametrize(
    ("water_key", "water"),
    [("1", WaterAnswer.YES), ("2", WaterAnswer.NO), ("3", WaterAnswer.PARTIAL)],
)
def test_daily_water_keys(water_key: str, water: WaterAnswer) -> None:
    session, _, _ = feed(daily(), water_key)
    assert session.answers.water is water


def test_daily_full_path_with_note_skip() -> None:
    session, actions, done = feed(daily(), "1", "6", "1", "#")
    assert done and session.done
    assert keys(actions) == ["household.bye"]
    assert isinstance(actions[-1], Hangup)
    assert result_to_checkin_fields(session) == {
        "outcome": CallOutcome.ANSWERED,
        "water": WaterAnswer.YES,
        "hours": 6,
        "clean": CleanAnswer.YES,
    }


def test_daily_note_recording_is_kept() -> None:
    session, _, _ = feed(daily(), "2")
    session, actions, done = on_input(session, None, recording_url="https://rec/1.mp3")
    assert done
    assert session.answers.note_recording_url == "https://rec/1.mp3"
    assert isinstance(actions[-1], Hangup)


def test_daily_note_timeout_finishes() -> None:
    session, actions, done = feed(daily(), "2", TIMEOUT)
    assert done
    assert session.answers.note_recording_url is None
    assert keys(actions) == ["household.bye"]


def test_daily_no_water_result_leaves_hours_and_clean_unasked() -> None:
    session, _, _ = feed(daily(), "2", "#")
    assert result_to_checkin_fields(session) == {
        "outcome": CallOutcome.ANSWERED,
        "water": WaterAnswer.NO,
        "hours": None,
        "clean": None,
    }


# --- re-prompts and timeouts ---------------------------------------------------------------


@pytest.mark.parametrize("bad", ["4", "0", "9", "*", "#", "12", "", "  ", "x", TIMEOUT])
def test_invalid_or_timeout_reprompts_once(bad: str) -> None:
    session, actions, done = feed(daily(), bad)
    assert not done
    assert session.step is FlowStep.Q_WATER
    assert session.retries == 1
    assert keys(actions) == ["household.invalid", "household.q_water"]


@pytest.mark.parametrize("bad", ["4", TIMEOUT])
def test_second_failure_moves_on_with_none(bad: str) -> None:
    session, actions, done = feed(daily(), bad, bad)
    assert session.answers.water is None
    assert session.step is FlowStep.Q_NOTE
    assert session.retries == 0
    assert isinstance(actions[-1], Record)
    assert not done
    session, _, done = on_input(session, "#")
    assert done
    assert result_to_checkin_fields(session)["outcome"] is CallOutcome.UNREACHABLE


def test_mixed_invalid_then_timeout_also_skips() -> None:
    session, _, _ = feed(daily(), "7", TIMEOUT)
    assert session.answers.water is None
    assert session.step is FlowStep.Q_NOTE


def test_invalid_then_valid_records_answer_and_resets_retries() -> None:
    session, actions, _ = feed(daily(), "5", "3")
    assert session.answers.water is WaterAnswer.PARTIAL
    assert session.retries == 0
    assert asked(actions) == "household.q_hours"


def test_retries_are_per_question() -> None:
    session, actions, _ = feed(daily(), "5", "1", "x")
    assert session.step is FlowStep.Q_HOURS
    assert session.retries == 1
    assert keys(actions) == ["household.invalid", "household.q_hours"]


def test_hours_skipped_still_asks_clean() -> None:
    session, actions, _ = feed(daily(), "1", TIMEOUT, TIMEOUT)
    assert session.answers.hours is None
    assert asked(actions) == "household.q_clean"


def test_clean_skipped_goes_to_note() -> None:
    session, actions, _ = feed(daily(), "1", "2", "8", "8")
    assert session.answers.clean is None
    assert session.step is FlowStep.Q_NOTE
    assert isinstance(actions[-1], Record)


def test_timeout_flag_beats_digits() -> None:
    session, _ = start(daily())
    session, actions, _ = on_input(session, "1", timeout=True)
    assert session.answers.water is None
    assert keys(actions)[0] == "household.invalid"


def test_digits_are_stripped() -> None:
    session, _, _ = feed(daily(), " 1 ")
    assert session.answers.water is WaterAnswer.YES


# --- VERIFY --------------------------------------------------------------------------------


def test_verify_start() -> None:
    session, actions = start(verify())
    assert keys(actions) == ["verify.greet", "verify.q_water"]
    assert session.step is FlowStep.Q_WATER


@pytest.mark.parametrize(("digit", "water"), [("1", WaterAnswer.YES), ("2", WaterAnswer.NO)])
def test_verify_answers_then_bye(digit: str, water: WaterAnswer) -> None:
    session, actions, done = feed(verify(), digit)
    assert done
    assert session.answers.water is water
    assert keys(actions) == ["verify.bye"]
    assert isinstance(actions[-1], Hangup)
    fields = result_to_checkin_fields(session)
    assert fields["outcome"] is CallOutcome.ANSWERED
    assert fields["hours"] is None and fields["clean"] is None


def test_verify_partial_key_is_invalid() -> None:
    _, actions, done = feed(verify(), "3")
    assert not done
    assert keys(actions) == ["household.invalid", "verify.q_water"]


def test_verify_two_timeouts_end_unreachable() -> None:
    session, actions, done = feed(verify(), TIMEOUT, TIMEOUT)
    assert done
    assert keys(actions) == ["verify.bye"]
    assert result_to_checkin_fields(session)["outcome"] is CallOutcome.UNREACHABLE


# --- OPERATOR ------------------------------------------------------------------------------


def test_operator_start_plays_summary_variant() -> None:
    session, actions = start(operator(TicketReason.NO_SUPPLY, 3))
    assert session.step is FlowStep.Q_FIXED
    assert keys(actions) == [
        "operator.greet",
        "operator.summary_no_supply.n3",
        "operator.q_fixed",
    ]
    summary = actions[1]
    assert isinstance(summary, Play)
    assert "sankhya: teen" in summary.text_hi


def test_operator_dirty_summary() -> None:
    _, actions = start(operator(TicketReason.DIRTY, 2))
    assert keys(actions)[1] == "operator.summary_dirty.n2"


@pytest.mark.parametrize("households", [0, 10, 25])
def test_operator_summary_without_clip_uses_base_key(households: int) -> None:
    _, actions = start(operator(TicketReason.NO_SUPPLY, households))
    summary = actions[1]
    assert isinstance(summary, Play)
    assert summary.prompt_key == "operator.summary_no_supply"
    assert not default_catalog().has_audio(summary.prompt_key)


def test_operator_fixed() -> None:
    session, actions, done = feed(operator(), "1")
    assert done
    assert result_to_operator(session) == {"fixed": True}
    assert keys(actions) == ["operator.ack_fixed"]
    assert isinstance(actions[-1], Hangup)


def test_operator_not_fixed() -> None:
    session, actions, done = feed(operator(), "2")
    assert done
    assert result_to_operator(session) == {"fixed": False}
    assert keys(actions) == ["operator.ack_pending"]


def test_operator_reprompt_then_unknown() -> None:
    session, actions, done = feed(operator(), "9")
    assert not done
    assert keys(actions) == ["household.invalid", "operator.q_fixed"]
    session, actions, done = on_input(session, None, timeout=True)
    assert done
    assert result_to_operator(session) == {"fixed": None}
    assert keys(actions) == ["operator.ack_pending"]


def test_operator_needs_ticket_details() -> None:
    with pytest.raises(ValidationError, match="ticket_reason"):
        FlowSession(call_id="c", purpose=Purpose.OPERATOR, operator_id="op-1")


def test_result_functions_reject_wrong_purpose() -> None:
    with pytest.raises(ValueError):
        result_to_checkin_fields(operator())
    with pytest.raises(ValueError):
        result_to_operator(daily())


# --- engine properties ---------------------------------------------------------------------


def test_start_is_idempotent_once_started() -> None:
    session, _ = start(daily())
    again, actions = start(session)
    assert again == session
    assert keys(actions) == ["household.q_water"]


def test_input_before_start_starts_the_call() -> None:
    session, actions, done = on_input(daily(), "1")
    assert not done
    assert session.step is FlowStep.Q_WATER
    assert keys(actions)[0] == "household.greet"


def test_input_after_done_just_hangs_up() -> None:
    session, _, _ = feed(verify(), "1")
    again, actions, done = on_input(session, "2")
    assert done and again == session
    assert actions == [Hangup()]


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [((), ["household.greet", "household.q_water"]), (("1",), ["household.q_hours"])],
)
def test_current_actions_replays_step(inputs: tuple[str, ...], expected: list[str]) -> None:
    session = daily()
    if inputs:
        session, _, _ = feed(session, *inputs)
    assert keys(current_actions(session)) == expected


def test_current_actions_for_note_and_done() -> None:
    session, _, _ = feed(daily(), "2")
    assert isinstance(current_actions(session)[-1], Record)
    session, _, _ = on_input(session, "#")
    assert isinstance(current_actions(session)[-1], Hangup)


def test_turn_counts_every_engine_step() -> None:
    session, _ = start(daily())
    assert session.turn == 1
    session, _, _ = on_input(session, "x")
    assert session.turn == 2
    session, _, _ = on_input(session, "1")
    assert session.turn == 3


def test_engine_does_not_mutate_input() -> None:
    session, _ = start(daily())
    before = session.model_dump()
    on_input(session, "1")
    on_input(session, "x")
    assert session.model_dump() == before


def test_with_recording_after_done() -> None:
    session, _, _ = feed(daily(), "2", "#")
    updated = with_recording(session, "https://rec/late.mp3")
    assert updated.answers.note_recording_url == "https://rec/late.mp3"
    assert updated.step is FlowStep.DONE


def test_session_roundtrip_as_dict() -> None:
    session, _, _ = feed(operator(), "5")
    item = session.to_item()
    assert item["purpose"] == "OPERATOR"
    assert item["step"] == "Q_FIXED"
    assert FlowSession.from_item(item) == session


def test_session_accepts_dynamodb_decimals() -> None:
    session, _, _ = feed(daily(), "1", "7")
    item = session.to_item()
    item.update(turn=Decimal(item["turn"]), retries=Decimal(0))
    item["answers"]["hours"] = Decimal(7)
    restored = FlowSession.from_item(item)
    assert restored == session


def test_checkin_fields_build_a_checkin() -> None:
    session, _, _ = feed(daily(), "3", "2", "2", "#")
    checkin = CheckIn(
        village_id="v-1",
        date="2026-10-09",
        household_id="hh-1",
        call_id=session.call_id,
        captured_at="2026-10-09T10:31:00+05:30",
        **result_to_checkin_fields(session),
    )
    assert checkin.water is WaterAnswer.PARTIAL
    assert checkin.clean is CleanAnswer.NO


def test_every_prompt_key_exists_in_catalog() -> None:
    cat = default_catalog()
    sessions = [daily(), verify(), operator(), operator(TicketReason.DIRTY, 14)]
    scripts = [("1", "x", "x", "2", "#"), ("3", "1", "1", "#"), ("2",), ("x", "x")]
    for session in sessions:
        for script in scripts:
            state, actions = start(session)
            seen = keys(actions)
            for value in script:
                if state.done:
                    break
                state, actions, _ = on_input(state, value)
                seen += keys(actions)
            for key in seen:
                assert cat.has_audio(key) or key in cat.template_keys(), key


_INPUTS = st.one_of(
    st.sampled_from(["0", "1", "2", "3", "4", "9", "#", "*", "", "12", TIMEOUT]),
    st.text(max_size=3),
)
_SESSIONS = st.sampled_from([daily(), verify(), operator(), operator(TicketReason.DIRTY, 1)])


@settings(max_examples=200, deadline=None)
@given(session=_SESSIONS, inputs=st.lists(_INPUTS, min_size=12, max_size=12))
def test_any_input_sequence_ends_cleanly(session: FlowSession, inputs: list[str]) -> None:
    """Every call ends within 9 inputs, each batch ends in input or hangup, answers are valid."""
    state, actions = start(session)
    used = 0
    done = False
    for value in inputs:
        if done:
            break
        assert isinstance(actions[-1], GetDigits | Record)
        timeout = value == TIMEOUT
        state, actions, done = on_input(state, None if timeout else value, timeout=timeout)
        used += 1
    assert done and used <= 9
    assert isinstance(actions[-1], Hangup)
    assert state.answers.hours is None or 0 <= state.answers.hours <= 9
    if session.purpose is Purpose.VERIFY:
        assert state.answers.water is not WaterAnswer.PARTIAL
