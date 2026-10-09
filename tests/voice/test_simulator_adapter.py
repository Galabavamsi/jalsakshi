"""Simulator adapter: /sim request parsing and action JSON for the console keypad."""

import json

import pytest
from pydantic import ValidationError

from jalsakshi.core.models import CapturedVia, Purpose, TicketReason
from jalsakshi.voice.actions import GetDigits, Hangup, Play, actions_from_json
from jalsakshi.voice.adapters.simulator import (
    CAPTURED_VIA,
    SimInput,
    from_json,
    input_response,
    parse_start,
    start_response,
    to_json,
)
from jalsakshi.voice.flow import FlowSession, on_input, start

AUDIO = "https://cdn.example/prompts/hi"


def test_to_json_shapes_match_contract() -> None:
    _, actions = start(FlowSession(call_id="sim-1", purpose=Purpose.DAILY))
    data = to_json(actions)
    assert data == [
        {
            "type": "play",
            "prompt_key": "household.greet",
            "text_hi": data[0]["text_hi"],
            "audio_url": None,
        },
        {
            "type": "get_digits",
            "num_digits": 1,
            "timeout_s": 15,
            "prompts": [
                {
                    "type": "play",
                    "prompt_key": "household.q_water",
                    "text_hi": data[1]["prompts"][0]["text_hi"],
                    "audio_url": None,
                }
            ],
        },
    ]
    assert data[0]["text_hi"].startswith("Namaste")
    json.dumps(data)


def test_to_json_fills_audio_urls_for_clips_only() -> None:
    session = FlowSession(
        call_id="sim-2",
        purpose=Purpose.OPERATOR,
        operator_id="op-1",
        ticket_reason=TicketReason.NO_SUPPLY,
        reported_households=11,
    )
    _, actions = start(session)
    data = to_json(actions, AUDIO)
    assert data[0]["audio_url"] == f"{AUDIO}/operator.greet.mp3"
    assert data[1]["prompt_key"] == "operator.summary_no_supply"
    assert data[1]["audio_url"] is None
    assert data[2]["prompts"][0]["audio_url"] == f"{AUDIO}/operator.q_fixed.mp3"


def test_record_and_hangup_json() -> None:
    session, _ = start(FlowSession(call_id="sim-3", purpose=Purpose.DAILY))
    session, _, _ = on_input(session, "2")
    session, actions, _ = on_input(session, "1")
    assert to_json(actions)[-1] == {"type": "record", "max_s": 15}
    _, actions, done = on_input(session, "#")
    assert done
    assert to_json(actions)[-1] == {"type": "hangup"}


def test_json_roundtrip() -> None:
    actions = [
        Play(prompt_key="household.greet", text_hi="Namaste"),
        GetDigits(prompts=[Play(prompt_key="household.q_water", text_hi="?")]),
    ]
    assert actions_from_json(to_json(actions)) == actions
    assert actions_from_json(to_json([Hangup()])) == [Hangup()]


def test_unknown_action_type_rejected() -> None:
    with pytest.raises(ValidationError):
        actions_from_json([{"type": "dial", "number": "+91"}])


@pytest.mark.parametrize(
    ("payload", "digits", "timeout"),
    [
        ({"digits": "2"}, "2", False),
        ('{"digits": "#"}', "#", False),
        (b'{"timeout": true}', None, True),
        ({"digits": ""}, None, False),
        ({}, None, False),
        (None, None, False),
        ("", None, False),
    ],
)
def test_from_json(payload: object, digits: str | None, timeout: bool) -> None:
    parsed = from_json(payload)
    assert parsed == SimInput(digits=digits, timeout=timeout)


@pytest.mark.parametrize("payload", [{"digits": "a"}, {"digits": "123456789"}, {"pin": "1"}])
def test_from_json_rejects_bad_input(payload: dict) -> None:
    with pytest.raises(ValidationError):
        from_json(payload)


def test_from_json_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        from_json("[1, 2]")


@pytest.mark.parametrize(
    "payload",
    [
        {"household_id": "hh-1", "purpose": "DAILY"},
        {"household_id": "hh-1", "purpose": "VERIFY"},
        '{"operator_id": "op-1", "purpose": "OPERATOR"}',
    ],
)
def test_parse_start_valid(payload: object) -> None:
    request = parse_start(payload)
    assert request.purpose in set(Purpose)


@pytest.mark.parametrize(
    "payload",
    [
        {"purpose": "DAILY"},
        {"household_id": "hh-1", "operator_id": "op-1", "purpose": "DAILY"},
        {"operator_id": "op-1", "purpose": "DAILY"},
        {"household_id": "hh-1", "purpose": "OPERATOR"},
        {"household_id": "hh-1", "purpose": "WEEKLY"},
        {"household_id": "", "purpose": "DAILY"},
    ],
)
def test_parse_start_invalid(payload: dict) -> None:
    with pytest.raises(ValidationError):
        parse_start(payload)


def test_response_envelopes() -> None:
    _, actions = start(FlowSession(call_id="sim-4", purpose=Purpose.VERIFY))
    started = start_response("sim-4", actions, AUDIO)
    assert started["call_id"] == "sim-4"
    assert started["actions"][0]["audio_url"] == f"{AUDIO}/verify.greet.mp3"
    reply = input_response([Hangup()], True)
    assert reply == {"actions": [{"type": "hangup"}], "done": True}


def test_simulated_call_end_to_end() -> None:
    session, _ = start(FlowSession(call_id="sim-5", purpose=Purpose.DAILY))
    done = False
    for body in ({"digits": "1"}, {"timeout": True}, {"digits": "7"}, {"digits": "1"}, {}):
        sim = from_json(body)
        session, actions, done = on_input(session, sim.digits, timeout=sim.timeout)
        if done:
            break
    assert done
    assert session.answers.hours == 7
    assert input_response(actions, done)["done"] is True
    assert CAPTURED_VIA is CapturedVia.SIMULATOR
