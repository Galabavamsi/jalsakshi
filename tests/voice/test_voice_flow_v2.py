"""v2 call flows: registration with consent, missed-call menu, stop, announcements (§15)."""

from __future__ import annotations

import pytest

from jalsakshi.core.models import (
    AccessKind,
    CallOutcome,
    CleanAnswer,
    Purpose,
    TicketReason,
    WaterAnswer,
)
from jalsakshi.voice.actions import Action, GetDigits, Play, Record
from jalsakshi.voice.catalog import default_catalog
from jalsakshi.voice.flow import (
    ConsentAnswer,
    FlowSession,
    FlowStep,
    ReportChoice,
    on_input,
    result_to_checkin_fields,
    result_to_registration,
    start,
    stop_requested,
)

TIMEOUT = "<timeout>"


def keys(actions: list[Action]) -> list[str]:
    out: list[str] = []
    for action in actions:
        if isinstance(action, Play):
            out.append(action.prompt_key)
        elif isinstance(action, GetDigits):
            out.extend(p.prompt_key for p in action.prompts)
    return out


def feed(session: FlowSession, *inputs: str) -> tuple[FlowSession, list[Action], bool]:
    session, actions = start(session)
    done = False
    for value in inputs:
        if value == TIMEOUT:
            session, actions, done = on_input(session, None, timeout=True)
        else:
            session, actions, done = on_input(session, value)
    return session, actions, done


def register() -> FlowSession:
    return FlowSession(call_id="r1", purpose=Purpose.REGISTER, household_id="h1")


def report() -> FlowSession:
    return FlowSession(
        call_id="m1",
        purpose=Purpose.REPORT,
        household_id="h1",
        message_text_hi="Aaj gaon mein paani aaya.",
    )


# --- REGISTER -------------------------------------------------------------------------------


def test_register_reads_the_notice_before_asking_anything() -> None:
    session, actions = start(register())
    assert keys(actions) == ["register.greet", "register.notice", "register.q_age"]
    assert session.step is FlowStep.Q_AGE


def test_register_happy_path_records_consent_source_and_name() -> None:
    session, actions, done = feed(register(), "1", "1", "3")
    assert not done
    assert keys(actions) == ["register.q_intro"]  # name and mohalla after the beep
    assert isinstance(actions[-1], Record) and actions[-1].max_s == 12
    session, actions, done = on_input(session, None, recording_url="https://media.vobiz.ai/n.mp3")
    assert done
    assert keys(actions) == ["register.done"]
    assert result_to_registration(session) == {
        "adult": True,
        "consent": ConsentAnswer.GRANTED,
        "consent_digits": "1",
        "access": AccessKind.HANDPUMP,
        "language": "hi",
    }


def test_first_call_asks_the_language_when_the_village_has_several() -> None:
    session = FlowSession(
        call_id="r2",
        purpose=Purpose.REGISTER,
        household_id="h1",
        language="hne",
        offered_languages=["hne", "hi"],
    )
    session, actions = start(session)
    assert session.step is FlowStep.Q_LANG
    assert keys(actions) == ["register.greet", "dyn.language_menu"]
    menu = actions[-1].prompts[0]  # type: ignore[union-attr]
    assert "छत्तीसगढ़ी" in menu.text_hi and "हिंदी" in menu.text_hi
    session, actions, _ = on_input(session, "2")
    assert session.language == "hi" and session.step is FlowStep.Q_AGE
    assert keys(actions) == ["register.notice", "register.q_age"]
    assert "Kripya" in actions[0].text_hi  # the Hindi notice


def test_chhattisgarhi_catalog_has_every_hindi_prompt() -> None:
    from jalsakshi.voice.catalog import catalog_for, default_catalog

    hne, hi = catalog_for("hne"), default_catalog()
    assert hne is not hi
    assert set(hne.template_keys()) == set(hi.template_keys())
    assert hne.text("operator.summary_dirty", households=2).endswith("दू।")


def test_register_can_hear_the_notice_again() -> None:
    session, actions, done = feed(register(), "1", "2")
    assert not done
    assert keys(actions) == ["register.notice", "register.q_consent"]
    session, actions, done = on_input(session, "1")
    assert session.step is FlowStep.Q_ACCESS


def test_notice_replays_are_limited_then_silence_is_no_consent() -> None:
    session, _, _ = feed(register(), "1", "2", "2")
    assert session.notice_plays == 3
    session, actions, done = on_input(session, "2")
    assert done
    assert session.answers.consent is None
    assert keys(actions) == ["register.no_answer"]


@pytest.mark.parametrize("inputs", [("1", TIMEOUT, TIMEOUT), ("1", "7", "8")])
def test_silence_or_wrong_keys_never_count_as_consent(inputs: tuple[str, ...]) -> None:
    session, actions, done = feed(register(), *inputs)
    assert done
    assert session.answers.consent is None
    assert keys(actions) == ["register.no_answer"]


def test_declining_ends_the_call_politely() -> None:
    session, actions, done = feed(register(), "1", "3")
    assert done
    assert session.answers.consent is ConsentAnswer.DECLINED
    assert keys(actions) == ["register.declined"]


def test_minors_are_not_asked_for_consent() -> None:
    session, actions, done = feed(register(), "2")
    assert done
    assert session.answers.adult is False
    assert keys(actions) == ["register.minor"]


# --- DAILY by source ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("access", "prompt"),
    [
        (AccessKind.HOUSE_TAP, "household.q_water_house_tap"),
        (AccessKind.HANDPUMP, "household.q_water_handpump"),
        (AccessKind.TANKER, "household.q_water_tanker"),
        (None, "household.q_water"),
    ],
)
def test_daily_question_names_the_familys_source(access: AccessKind | None, prompt: str) -> None:
    session = FlowSession(call_id="d1", purpose=Purpose.DAILY, access=access)
    _, actions = start(session)
    assert keys(actions)[-1] == prompt


def test_hours_are_asked_only_for_piped_water() -> None:
    pump = FlowSession(call_id="d1", purpose=Purpose.DAILY, access=AccessKind.HANDPUMP)
    session, _, _ = feed(pump, "1")
    assert session.step is FlowStep.Q_CLEAN
    tap = FlowSession(call_id="d2", purpose=Purpose.DAILY, access=AccessKind.STANDPOST)
    session, _, _ = feed(tap, "1")
    assert session.step is FlowStep.Q_HOURS


# --- stop -------------------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", [Purpose.DAILY, Purpose.VERIFY])
def test_nine_then_nine_stops_all_calls(purpose: Purpose) -> None:
    session, actions, done = feed(FlowSession(call_id="s", purpose=purpose), "9")
    assert not done
    assert keys(actions) == ["stop.q_confirm"]
    session, actions, done = on_input(session, "9")
    assert done
    assert stop_requested(session)
    assert keys(actions) == ["stop.done"]


def test_stop_can_be_cancelled() -> None:
    session, actions, done = feed(FlowSession(call_id="s", purpose=Purpose.DAILY), "9", "0")
    assert done
    assert not stop_requested(session)
    assert keys(actions) == ["stop.cancelled"]
    assert result_to_checkin_fields(session)["outcome"] is CallOutcome.UNREACHABLE


# --- REPORT (missed-call menu) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("digit", "choice", "water", "clean"),
    [
        ("1", ReportChoice.NO_WATER, WaterAnswer.NO, None),
        ("2", ReportChoice.DIRTY, WaterAnswer.YES, CleanAnswer.NO),
    ],
)
def test_report_menu_choices_become_answers(
    digit: str, choice: ReportChoice, water: WaterAnswer, clean: CleanAnswer | None
) -> None:
    session, actions, done = feed(report(), digit)
    assert done
    assert session.answers.report is choice
    assert keys(actions) == ["report.ack"]
    fields = result_to_checkin_fields(session)
    assert fields["outcome"] is CallOutcome.ANSWERED
    assert (fields["water"], fields["clean"]) == (water, clean)


def test_report_three_records_a_longer_note() -> None:
    session, actions, done = feed(report(), "3")
    assert not done
    assert keys(actions) == ["report.q_note"]
    assert isinstance(actions[-1], Record) and actions[-1].max_s == 25
    session, actions, done = on_input(session, None, recording_url="https://media.vobiz.ai/r.mp3")
    assert done
    assert keys(actions) == ["report.note_ack"]
    assert session.answers.note_recording_url == "https://media.vobiz.ai/r.mp3"
    assert result_to_checkin_fields(session)["outcome"] is CallOutcome.UNREACHABLE


def test_report_four_plays_status_then_the_menu_again() -> None:
    session, actions, done = feed(report(), "4")
    assert not done
    assert keys(actions) == ["dyn.report_status", "report.menu"]
    assert actions[0].text_hi == "Aaj gaon mein paani aaya."  # type: ignore[union-attr]
    session, actions, done = on_input(session, "4")
    assert done
    assert keys(actions) == ["dyn.report_status", "report.bye"]


def test_report_nine_offers_to_stop() -> None:
    _, actions, _ = feed(report(), "9")
    assert keys(actions) == ["stop.q_confirm"]


# --- BROADCAST / SUMMARY / OPERATOR extras --------------------------------------------------


def test_broadcast_plays_the_message_and_counts_heard() -> None:
    session = FlowSession(call_id="b", purpose=Purpose.BROADCAST, message_text_hi="Kal paani band.")
    session, actions = start(session)
    assert keys(actions) == ["broadcast.greet", "dyn.broadcast", "broadcast.q_heard"]
    session, actions, done = on_input(session, "2")
    assert keys(actions) == ["dyn.broadcast", "broadcast.q_heard"]
    session, actions, done = on_input(session, "1")
    assert done and session.answers.heard is True


def test_broadcast_needs_text() -> None:
    with pytest.raises(ValueError, match="message_text_hi"):
        FlowSession(call_id="b", purpose=Purpose.BROADCAST)


def test_operator_hears_the_complaint_number_and_place() -> None:
    session = FlowSession(
        call_id="o",
        purpose=Purpose.OPERATOR,
        ticket_reason=TicketReason.LEAK,
        reported_households=1,
        ticket_number=12,
        water_point_name="Kutelabhatha nal jal yojana",
    )
    _, actions = start(session)
    assert keys(actions)[:3] == ["operator.greet", "operator.summary_leak.n1", "operator.where"]
    where = actions[2]
    assert isinstance(where, Play)
    assert "kramank 12" in where.text_hi and "Kutelabhatha" in where.text_hi
    assert not default_catalog().has_audio(where.prompt_key)


@pytest.mark.parametrize("inputs", [("9",), ("1", "9"), ("1", "1", "9")])
def test_nine_on_the_consent_call_is_a_clear_no(inputs: tuple[str, ...]) -> None:
    session, actions, done = feed(register(), *inputs)
    assert done
    assert session.answers.consent is ConsentAnswer.DECLINED
    assert session.answers.consent_digits == "9"
    assert keys(actions) == ["register.declined"]
