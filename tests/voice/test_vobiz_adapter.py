"""Vobiz adapter: XML rendering, webhook parsing, call request building, signatures."""

import base64
import hashlib
import hmac
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlencode

import pytest

from jalsakshi.core.models import Purpose
from jalsakshi.voice.actions import GetDigits, Hangup, Play, Record
from jalsakshi.voice.adapters.vobiz import (
    API_BASE,
    CONTENT_TYPE,
    EMPTY_RESPONSE,
    VobizAuth,
    compute_signature,
    parse_form,
    parse_webhook,
    place_call_request,
    render_xml,
    validate_signature,
)
from jalsakshi.voice.catalog import PromptCatalog
from jalsakshi.voice.flow import FlowSession, on_input, start

ACTION = "https://api.example/ivr/vobiz/tok123/digits?turn=3"
RECORDING = "https://api.example/ivr/vobiz/tok123/recording"
AUDIO = "https://cdn.example/prompts/hi"
AUTH = VobizAuth(auth_id="MA_TEST", auth_token="secret-token")

# Sample payloads shaped like the examples in the Vobiz docs (form fields as strings).
ANSWER_FORM = {
    "CallUUID": "c-123",
    "RequestUUID": "c-123",
    "From": "+918000000001",
    "To": "+919000000002",
    "Direction": "outbound",
    "Event": "StartApp",
    "CallStatus": "in-progress",
}
GATHER_FORM = {**ANSWER_FORM, "Event": "", "InputType": "dtmf", "Digits": "3", "Speech": ""}
GATHER_TIMEOUT_FORM = {**GATHER_FORM, "Digits": ""}
REDIRECT_FORM = {**ANSWER_FORM, "Event": "Redirect"}
RECORD_STOP_FORM = {
    "Event": "RecordStop",
    "CallUUID": "c-123",
    "RecordingID": "rec-9",
    "RecordFile": "https://media.vobiz.ai/recordings/rec-9.mp3",
    "RecordingDuration": "12",
    "RecordingDurationMs": "12120",
    "RecordingEndReason": "FinishedOnKey",
}
HANGUP_FORM = {
    **ANSWER_FORM,
    "Event": "Hangup",
    "CallStatus": "completed",
    "HangupCause": "NORMAL_CLEARING",
    "Duration": "48",
    "BillDuration": "45",
}
NO_ANSWER_FORM = {**HANGUP_FORM, "CallStatus": "no-answer", "HangupCause": "NO_ANSWER"}


def parse(xml: str) -> ET.Element:
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    return ET.fromstring(xml.split("\n", 1)[1])


def play(key: str = "household.greet", text: str = "Namaste", url: str | None = None) -> Play:
    return Play(prompt_key=key, text_hi=text, audio_url=url)


# --- render_xml ----------------------------------------------------------------------------


def test_play_uses_prerendered_audio() -> None:
    root = parse(render_xml([play(), Hangup()], ACTION, AUDIO))
    assert root.tag == "Response"
    assert [child.tag for child in root] == ["Play", "Hangup"]
    assert root[0].text == f"{AUDIO}/household.greet.mp3"


def test_explicit_audio_url_wins() -> None:
    root = parse(render_xml([play(url="https://other/x.mp3"), Hangup()], ACTION, AUDIO))
    assert root[0].text == "https://other/x.mp3"


def test_speak_fallback_without_base_url() -> None:
    root = parse(render_xml([play(text="Namaste ji"), Hangup()], ACTION, None))
    speak = root[0]
    assert speak.tag == "Speak"
    assert speak.attrib == {"voice": "WOMAN", "language": "hi-IN"}
    assert speak.text == "Namaste ji"


def test_speak_fallback_for_prompt_without_clip() -> None:
    summary = play("operator.summary_no_supply", "Aaj gaon ke 12 gharon ne bataya")
    root = parse(render_xml([summary, Hangup()], ACTION, AUDIO))
    assert root[0].tag == "Speak"
    assert "12 gharon" in root[0].text


def test_text_is_escaped() -> None:
    cat = PromptCatalog({"x": {"amp": "Paani & <bijli>"}})
    xml = render_xml(
        [Play(prompt_key="x.amp", text_hi="Paani & <bijli>")], ACTION, None, catalog=cat
    )
    assert "&amp;" in xml and "&lt;bijli&gt;" in xml
    assert parse(xml)[0].text == "Paani & <bijli>"


def test_get_digits_renders_gather_then_redirect() -> None:
    action = GetDigits(num_digits=1, timeout_s=10, prompts=[play("household.q_water", "Aaj?")])
    root = parse(render_xml([play(), action], ACTION, AUDIO))
    assert [child.tag for child in root] == ["Play", "Gather", "Redirect"]
    gather = root[1]
    assert gather.attrib == {
        "action": ACTION,
        "method": "POST",
        "inputType": "dtmf",
        "numDigits": "1",
        "executionTimeout": "10",
        "redirect": "true",
    }
    assert [child.tag for child in gather] == ["Play"]
    assert gather[0].text == f"{AUDIO}/household.q_water.mp3"
    assert root[2].text == ACTION
    assert root[2].attrib == {"method": "POST"}


@pytest.mark.parametrize(("timeout_s", "rendered"), [(1, "5"), (5, "5"), (30, "30"), (60, "60")])
def test_gather_timeout_clamped_to_vobiz_range(timeout_s: int, rendered: str) -> None:
    action = GetDigits(timeout_s=timeout_s, prompts=[play()])
    gather = parse(render_xml([action], ACTION, AUDIO))[0]
    assert gather.attrib["executionTimeout"] == rendered


def test_record_renders_with_callbacks_then_redirect() -> None:
    root = parse(
        render_xml(
            [play("household.q_note"), Record(max_s=15)], ACTION, AUDIO, recording_url=RECORDING
        )
    )
    assert [child.tag for child in root] == ["Play", "Record", "Redirect"]
    record = root[1]
    assert record.attrib["callbackUrl"] == RECORDING
    assert record.attrib["action"] == RECORDING
    assert record.attrib["redirect"] == "false"
    assert record.attrib["maxLength"] == "15"
    assert record.attrib["finishOnKey"] == "#"
    assert record.attrib["fileFormat"] == "mp3"
    assert record.attrib["playBeep"] == "true"
    assert root[2].text == ACTION


def test_record_needs_recording_url() -> None:
    with pytest.raises(ValueError, match="recording_url"):
        render_xml([Record()], ACTION, AUDIO)


def test_hangup_alone() -> None:
    root = parse(render_xml([Hangup()], ACTION, AUDIO))
    assert [child.tag for child in root] == ["Hangup"]
    assert len(root[0]) == 0 and not root[0].attrib


@pytest.mark.parametrize(
    "actions",
    [
        [Hangup(), play()],
        [GetDigits(prompts=[play()]), play()],
        [Record(), Hangup()],
    ],
)
def test_input_and_hangup_must_be_last(actions: list) -> None:
    with pytest.raises(ValueError, match="last action"):
        render_xml(actions, ACTION, AUDIO, recording_url=RECORDING)


def test_empty_actions_rejected() -> None:
    with pytest.raises(ValueError, match="no actions"):
        render_xml([], ACTION, AUDIO)


def test_full_daily_call_renders_well_formed_xml() -> None:
    session, actions = start(FlowSession(call_id="c-1", purpose=Purpose.DAILY))
    batches = [actions]
    for digits in ("1", "4", "1", "#"):
        session, actions, _ = on_input(session, digits)
        batches.append(actions)
    for batch in batches:
        root = parse(render_xml(batch, ACTION, AUDIO, recording_url=RECORDING))
        assert root[-1].tag in {"Redirect", "Hangup"}
        assert all(el.tag != "Speak" for el in root.iter())


def test_empty_response_is_valid_xml() -> None:
    root = parse(EMPTY_RESPONSE)
    assert root.tag == "Response" and len(root) == 0
    assert CONTENT_TYPE == "application/xml"


# --- parse_webhook -------------------------------------------------------------------------


def test_parse_answer_webhook() -> None:
    event = parse_webhook(ANSWER_FORM)
    assert event.call_uuid == "c-123"
    assert event.request_uuid == "c-123"
    assert event.event == "StartApp"
    assert event.call_status == "in-progress"
    assert event.from_number == "+918000000001"
    assert event.direction == "outbound"
    assert not event.is_hangup and not event.is_recording


def test_parse_gather_digits() -> None:
    event = parse_webhook(GATHER_FORM)
    assert event.digits == "3"
    assert event.input_type == "dtmf"
    assert event.event is None
    assert not event.is_timeout


def test_parse_gather_timeout() -> None:
    event = parse_webhook(GATHER_TIMEOUT_FORM)
    assert event.digits is None
    assert event.is_timeout


def test_parse_redirect_after_gather_is_timeout() -> None:
    event = parse_webhook(REDIRECT_FORM)
    assert event.event == "Redirect"
    assert event.is_timeout


def test_parse_record_stop() -> None:
    event = parse_webhook(RECORD_STOP_FORM)
    assert event.is_recording
    assert event.recording_id == "rec-9"
    assert event.recording_url == "https://media.vobiz.ai/recordings/rec-9.mp3"
    assert event.recording_duration_s == 12
    assert event.recording_end_reason == "FinishedOnKey"


def test_parse_record_url_alias() -> None:
    form = {"CallUUID": "c", "RecordUrl": "https://x/r.mp3", "RecordingDuration": "nan"}
    event = parse_webhook(form)
    assert event.recording_url == "https://x/r.mp3"
    assert event.recording_duration_s is None


def test_parse_hangup() -> None:
    event = parse_webhook(HANGUP_FORM)
    assert event.is_hangup
    assert not event.unanswered
    assert event.hangup_cause == "NORMAL_CLEARING"
    assert event.duration_s == 48


@pytest.mark.parametrize("status", ["no-answer", "busy", "failed", "timeout", "cancel"])
def test_parse_unanswered_hangup(status: str) -> None:
    event = parse_webhook({**NO_ANSWER_FORM, "CallStatus": status})
    assert event.unanswered and event.is_hangup


def test_parse_list_valued_form() -> None:
    form = parse_qs(urlencode(GATHER_FORM), keep_blank_values=True)
    assert parse_webhook(form).digits == "3"


def test_parse_requires_call_uuid() -> None:
    with pytest.raises(ValueError, match="CallUUID"):
        parse_webhook({"Digits": "1"})
    with pytest.raises(ValueError):
        parse_webhook({"CallUUID": "  "})


def test_parse_form_body() -> None:
    body = urlencode(GATHER_TIMEOUT_FORM)
    assert parse_form(body)["Digits"] == ""
    assert parse_form(body.encode())["CallUUID"] == "c-123"
    encoded = base64.b64encode(body.encode()).decode()
    assert parse_form(encoded, base64_encoded=True) == parse_form(body)
    assert parse_form(None) == {} and parse_form("") == {}


def test_gather_webhook_drives_engine() -> None:
    session, _ = start(FlowSession(call_id="c-123", purpose=Purpose.DAILY))
    event = parse_webhook(GATHER_FORM)
    session, actions, _ = on_input(session, event.digits, timeout=event.is_timeout)
    assert session.answers.water == "PARTIAL"
    assert actions[-1].type == "get_digits"


# --- place_call_request --------------------------------------------------------------------


def test_place_call_request() -> None:
    method, url, headers, body = place_call_request(
        "+919000000002", "+918000000001", "https://a/answer", "https://a/hangup", AUTH
    )
    assert method == "POST"
    assert url == f"{API_BASE}/Account/MA_TEST/Call/"
    assert url == "https://api.vobiz.ai/api/v1/Account/MA_TEST/Call/"
    assert headers == {
        "X-Auth-ID": "MA_TEST",
        "X-Auth-Token": "secret-token",
        "Content-Type": "application/json",
    }
    assert body == {
        "from": "+918000000001",
        "to": "+919000000002",
        "answer_url": "https://a/answer",
        "answer_method": "POST",
        "hangup_url": "https://a/hangup",
        "hangup_method": "POST",
        "time_limit": 300,
        "ring_timeout": 45,
    }


def test_place_call_request_with_ring_url() -> None:
    *_, body = place_call_request(
        "+919000000002", "+918000000001", "https://a/x", "https://a/y", AUTH, ring_url="https://a/r"
    )
    assert body["ring_url"] == "https://a/r"
    assert body["ring_method"] == "POST"


@pytest.mark.parametrize(
    ("to", "from_"),
    [
        ("9000000002", "+918000000001"),
        ("+919000000002<+919000000003", "+918000000001"),
        ("+919000000002", "08000000001"),
        ("+91 90000 00002", "+918000000001"),
    ],
)
def test_place_call_request_rejects_bad_numbers(to: str, from_: str) -> None:
    with pytest.raises(ValueError, match=r"E\.164"):
        place_call_request(to, from_, "https://a/x", "https://a/y", AUTH)


def test_auth_token_not_in_repr() -> None:
    assert "secret-token" not in repr(AUTH)


# --- signatures ----------------------------------------------------------------------------


def _doc_signature(base_url: str, nonce: str, token: str, sep: str) -> str:
    digest = hmac.new(token.encode(), (base_url + sep + nonce).encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_compute_signature_matches_documented_algorithm() -> None:
    url = "https://api.example/ivr/vobiz/tok/digits?turn=2"
    base = "https://api.example/ivr/vobiz/tok/digits"
    nonce = "12345678901234567890"
    assert compute_signature(url, nonce, "secret-token", "v2") == _doc_signature(
        base, nonce, "secret-token", ""
    )
    assert compute_signature(url, nonce, "secret-token", "v3") == _doc_signature(
        base, nonce, "secret-token", "."
    )
    with pytest.raises(ValueError):
        compute_signature(url, nonce, "secret-token", "v1")


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_validate_signature_accepts_valid(version: str) -> None:
    nonce = "98765432109876543210"
    headers = {
        f"X-Vobiz-Signature-{version.upper()}": compute_signature(
            ACTION, nonce, "secret-token", version
        ),
        f"X-Vobiz-Signature-{version.upper()}-Nonce": nonce,
    }
    assert validate_signature(ACTION, headers, "secret-token")
    lowered = {key.lower(): value for key, value in headers.items()}
    assert validate_signature(ACTION, lowered, "secret-token")


def test_validate_signature_rejects_wrong_token_and_missing_headers() -> None:
    nonce = "11111111111111111111"
    headers = {
        "X-Vobiz-Signature-V3": compute_signature(ACTION, nonce, "other-token", "v3"),
        "X-Vobiz-Signature-V3-Nonce": nonce,
    }
    assert not validate_signature(ACTION, headers, "secret-token")
    assert not validate_signature(ACTION, {}, "secret-token")
    assert not validate_signature(ACTION, {"X-Vobiz-Signature-V2": "abc"}, "secret-token")


def test_validate_signature_rejects_other_path() -> None:
    nonce = "22222222222222222222"
    headers = {
        "X-Vobiz-Signature-V2": compute_signature(ACTION, nonce, "secret-token", "v2"),
        "X-Vobiz-Signature-V2-Nonce": nonce,
    }
    assert not validate_signature(RECORDING, headers, "secret-token")
