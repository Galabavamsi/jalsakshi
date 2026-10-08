"""Vobiz webhooks: path token, allowlist, signature, XML turns, replays and hangups."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from jalsakshi.core.models import CallOutcome, CapturedVia, Purpose, WaterAnswer
from jalsakshi.handlers import calls, config, ivr_vobiz, sfn_tasks
from jalsakshi.store import Repository
from jalsakshi.voice.adapters.vobiz import compute_signature

from .fakes import DAY, DOMAIN, IVR_TOKEN, VID, FakeSfn, HttpEvent, LambdaContext, call

BASE = f"/ivr/vobiz/{IVR_TOKEN}"


def place(token: str = "tok-1", hid: str = "h1") -> str:
    item = {"village_id": VID, "household_id": hid, "date": DAY.isoformat(), "purpose": "DAILY"}
    out = sfn_tasks.place_call({"task_token": token, "input": item}, LambdaContext())
    return str(out["call_id"])


def hook(
    action: str, query: dict[str, str], form: dict[str, str] | None = None, **extra: Any
) -> tuple[int, str]:
    fields = {"CallUUID": "vobiz-call-1", "RequestUUID": "req-1", **(form or {})}
    event = HttpEvent("POST", f"{BASE}/{action}", query=query, form=fields, **extra)
    status, body, headers = call(ivr_vobiz.handler, event)
    if status == 200:
        assert headers["Content-Type"] == "application/xml"
    return status, body


def gather_turn(xml: str) -> int:
    redirect = ET.fromstring(xml.split("\n", 1)[1]).find("Redirect")
    assert redirect is not None and redirect.text is not None
    query = parse_qs(urlsplit(redirect.text).query)
    return int(query["turn"][0])


def test_wrong_token_is_404(seeded: Repository) -> None:
    event = HttpEvent("POST", "/ivr/vobiz/wrong/answer", form={"CallUUID": "x"})
    status, body, _ = call(ivr_vobiz.handler, event)
    assert status == 404 and body == "not found"


def test_answer_renders_greeting_and_gather(seeded: Repository) -> None:
    call_id = place()
    status, xml = hook("answer", {"call_id": call_id})
    assert status == 200
    root = ET.fromstring(xml.split("\n", 1)[1])
    assert [child.tag for child in root] == ["Play", "Gather", "Redirect"]
    assert root[0].text == "https://cdn.example.test/prompts/hi/household.greet.mp3"
    gather = root[1]
    assert gather.get("action", "").startswith(f"https://{DOMAIN}{BASE}/digits?")
    assert gather_turn(xml) == 1
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None and loaded.record.provider_call_uuid == "vobiz-call-1"


def test_unknown_call_hangs_up(seeded: Repository) -> None:
    status, xml = hook("answer", {"call_id": "nope"})
    assert status == 200 and "<Hangup" in xml


def test_full_call_writes_checkin_and_resumes_workflow(
    seeded: Repository, sfn_fake: FakeSfn
) -> None:
    call_id = place("tok-9")
    hook("answer", {"call_id": call_id})
    _, xml = hook("digits", {"call_id": call_id, "turn": "1"}, {"Digits": "2"})
    assert "<Record" in xml
    recording = ET.fromstring(xml.split("\n", 1)[1]).find("Record")
    assert recording is not None and "/recording?call_id=" in recording.get("action", "")
    _, xml = hook("digits", {"call_id": call_id, "turn": "2"})
    assert "<Hangup" in xml
    [stored] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert (stored.outcome, stored.water, stored.captured_via) == (
        CallOutcome.ANSWERED,
        WaterAnswer.NO,
        CapturedVia.DTMF,
    )
    assert sfn_fake.outputs_for("tok-9")[0]["answered"] is True
    hook("status", {"call_id": call_id}, {"Event": "Hangup", "CallStatus": "completed"})
    assert len(sfn_fake.successes) == 1


def test_stale_and_duplicate_turns_replay_without_applying(seeded: Repository) -> None:
    call_id = place()
    hook("answer", {"call_id": call_id})
    _, stale = hook("digits", {"call_id": call_id, "turn": "7"}, {"Digits": "1"})
    assert gather_turn(stale) == 1
    _, first = hook("digits", {"call_id": call_id, "turn": "1"}, {"Digits": "1"})
    assert gather_turn(first) == 2
    _, duplicate = hook("digits", {"call_id": call_id, "turn": "1"}, {"Digits": "3"})
    assert gather_turn(duplicate) == 2
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None and loaded.record.flow.answers.water is WaterAnswer.YES


def test_hangup_before_answering_is_unreachable(seeded: Repository, sfn_fake: FakeSfn) -> None:
    call_id = place("tok-2")
    hook("status", {"call_id": call_id}, {"Event": "Hangup", "CallStatus": "no-answer"})
    [stored] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert stored.outcome is CallOutcome.UNREACHABLE
    assert sfn_fake.outputs_for("tok-2")[0]["answered"] is False


def test_recording_is_kept_on_the_session(seeded: Repository) -> None:
    call_id = place()
    form = {"RecordUrl": "https://media.vobiz.example/rec.mp3", "RecordingDuration": "6"}
    status, xml = hook("recording", {"call_id": call_id}, form)
    assert status == 200 and "<Response" in xml
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None
    assert loaded.record.flow.answers.note_recording_url == "https://media.vobiz.example/rec.mp3"


def test_source_ip_allowlist(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JALSAKSHI_IVR_ALLOWED_CIDRS", "198.51.100.0/24")
    config.settings.cache_clear()
    call_id = place()
    status, _ = hook("answer", {"call_id": call_id})
    assert status == 404
    status, _ = hook("answer", {"call_id": call_id}, source_ip="198.51.100.20")
    assert status == 200


def test_signature_check_when_enabled(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JALSAKSHI_VOBIZ_VERIFY_SIGNATURE", "true")
    config.settings.cache_clear()
    call_id = place()
    status, _ = hook("answer", {"call_id": call_id})
    assert status == 404
    url = f"https://{DOMAIN}{BASE}/answer"
    signature = compute_signature(url, "nonce-1", "vobiz-token")
    headers = {"X-Vobiz-Signature-V3": signature, "X-Vobiz-Signature-V3-Nonce": "nonce-1"}
    status, _ = hook("answer", {"call_id": call_id}, headers=headers)
    assert status == 200


def test_missing_call_uuid_is_400(seeded: Repository) -> None:
    event = HttpEvent("POST", f"{BASE}/answer", form={"Digits": "1"})
    status, _, _ = call(ivr_vobiz.handler, event)
    assert status == 400


def test_internal_error_hangs_up_politely(
    seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("store down")

    monkeypatch.setattr(ivr_vobiz, "load_call", boom)
    status, xml = hook("answer", {"call_id": "x"})
    assert status == 200 and "<Hangup" in xml
