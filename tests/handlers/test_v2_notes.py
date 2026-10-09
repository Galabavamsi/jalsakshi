"""The notes Lambda (ARCHITECTURE.md §15.6): fetch the Vobiz recording, archive it, delete the
Vobiz copy, transcribe with Sarvam, let the agent label it, then open or join a complaint (REPORT)
or attach it to the day's answer (DAILY). The AI never decides more than the label."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from jalsakshi.agent.notes import NoteExtraction, NoteIssueKind
from jalsakshi.core.models import Purpose, TicketOrigin, TicketReason
from jalsakshi.core.tickets import new_ticket
from jalsakshi.handlers import config, notes, outbound, sfn_tasks
from jalsakshi.store import Repository

from .fakes import (
    BUCKET,
    DAY,
    NOTES_FN,
    NOW,
    PHONES,
    STAGE,
    VID,
    LambdaContext,
    V2Fakes,
    next_turn,
    run_call,
    v2_fakes,
    vobiz_post,
    water_point,
)

AUDIO = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
REC_URL = "https://media.vobiz.ai/recordings/rec-1.mp3"
DELETE_URL = "https://api.vobiz.ai/api/v1/Account/MA_TEST/Recording/rec-1/"
STT_URL = "https://api.sarvam.ai/speech-to-text"
TRANSCRIPT = "school ke paas pipe phoot gaya hai, do din se paani beh raha hai"


@pytest.fixture
def v2(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fakes]:
    yield from v2_fakes(monkeypatch)


class Vobiz:
    """MockTransport for the recording host, the Vobiz API and Sarvam STT."""

    def __init__(self, *, fetch: int = 200, stt: int = 200, transcript: str = TRANSCRIPT) -> None:
        self.fetch, self.stt, self.transcript = fetch, stt, transcript
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if request.method == "GET" and url == REC_URL:
            return httpx.Response(self.fetch, content=AUDIO if self.fetch == 200 else b"")
        if request.method == "DELETE" and url == DELETE_URL:
            return httpx.Response(204)
        if request.method == "POST" and url == STT_URL:
            if self.stt != 200:
                return httpx.Response(self.stt, json={"error": {"message": "overloaded"}})
            return httpx.Response(200, json={"transcript": self.transcript, "request_id": "r-1"})
        return httpx.Response(404)

    def sent(self, method: str, url: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and str(r.url) == url]


@pytest.fixture
def http(v2: V2Fakes, aws: dict[str, Any]) -> Vobiz:
    aws["ssm"].put_parameter(
        Name=f"/jalsakshi/{STAGE}/sarvam_api_key", Type="SecureString", Value="sk-test"
    )
    config.secrets.clear()
    transport = Vobiz()
    config.use_http_client(httpx.Client(transport=httpx.MockTransport(transport)))
    return transport


def agent_says(
    monkeypatch: pytest.MonkeyPatch,
    issue: NoteIssueKind = NoteIssueKind.LEAK,
    confidence: str = "high",
    *,
    relevant: bool = True,
) -> list[str]:
    seen: list[str] = []

    def fake(transcript: str) -> tuple[NoteExtraction, str]:
        seen.append(transcript)
        extraction = NoteExtraction(
            relevant=relevant,
            issue=issue,
            summary_en="Pipe burst near the school; water running for two days.",
            days_affected=2,
            location_hint="school",
            confidence=confidence,  # type: ignore[arg-type]
        )
        return extraction, "test-model"

    monkeypatch.setattr(notes, "extract_note_details", fake)
    return seen


def on_point(repo: Repository, wpid: str = "wp-a", *hids: str) -> None:
    repo.put_water_point(water_point(wpid))
    for hid in hids or ("h1", "h2"):
        household = repo.get_household(VID, hid)
        assert household is not None
        repo.put_household(household.model_copy(update={"water_point_id": wpid}))


def report_note(repo: Repository, v2: V2Fakes, phone: str = PHONES[0], tag: str = "m") -> dict:
    """A missed-call REPORT where the resident pressed 3 and spoke; returns the notes job."""
    call_id = outbound.callback(repo, phone, 0, tag)["call_id"]
    replies = run_call(call_id, ["3"])
    form = {"RecordUrl": REC_URL, "RecordingDuration": "9", "RecordingID": "rec-1"}
    vobiz_post("recording", {"call_id": call_id}, form)
    vobiz_post("digits", {"call_id": call_id, "turn": str(next_turn(replies[-1]))})
    return v2.lambdas.events(function=NOTES_FN)[-1]


def run_notes(job: dict) -> dict[str, Any]:
    return notes.handler(job, LambdaContext())


def test_report_note_opens_a_labelled_ticket(
    v2: V2Fakes, http: Vobiz, seeded: Repository, aws: dict[str, Any], monkeypatch: Any
) -> None:
    seen = agent_says(monkeypatch)
    on_point(seeded)
    job = report_note(seeded, v2)
    out = run_notes(job)
    key = f"audio/{VID}/{job['call_id']}.mp3"
    assert out == {"status": "ticket", "audio_key": key, "issue": "LEAK"}
    stored = aws["s3"].get_object(Bucket=BUCKET, Key=key)
    assert stored["Body"].read() == AUDIO and stored["ServerSideEncryption"] == "AES256"
    [fetch] = http.sent("GET", REC_URL)
    assert fetch.headers["X-Auth-ID"] == "MA_TEST"
    assert len(http.sent("DELETE", DELETE_URL)) == 1
    [stt] = http.sent("POST", STT_URL)
    assert stt.headers["api-subscription-key"] == "sk-test"
    assert seen == [TRANSCRIPT]

    ticket = seeded.get_open_ticket(VID, "wp-a", TicketReason.LEAK)
    assert ticket is not None and ticket.origin is TicketOrigin.VOICE_NOTE
    assert ticket.reporters == ["h1"] and ticket.number == 1 and ticket.quorum == 1
    issue = ticket.issue
    assert issue is not None
    assert (issue.issue, issue.confidence, issue.model_id) == (TicketReason.LEAK, 0.9, "test-model")
    assert issue.summary_en.startswith("Pipe burst") and issue.transcript == TRANSCRIPT
    assert (issue.location_hint, issue.days_affected) == ("school", 2)
    assert v2.sfn.names == [ticket.id]
    feed = seeded.list_activity(NOW.replace(hour=0))
    assert any("AI-transcribed, unconfirmed" in e.text_en for e in feed)


def test_second_note_about_the_same_leak_joins_the_ticket(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: Any
) -> None:
    agent_says(monkeypatch)
    on_point(seeded)
    run_notes(report_note(seeded, v2))
    run_notes(report_note(seeded, v2, PHONES[1], "m2"))
    [ticket] = seeded.list_open_tickets(VID)
    assert ticket.reporters == ["h1", "h2"] and ticket.quorum == 2
    assert ticket.events[-1].detail == {"note": "another_report", "household_id": "h2"}
    assert ticket.issue is not None and ticket.issue.issue is TicketReason.LEAK


@pytest.mark.parametrize(
    ("confidence", "relevant", "expected"),
    [("low", True, 0.3), ("medium", True, 0.7), ("high", False, 0.2)],
)
def test_unsure_or_irrelevant_notes_open_an_other_ticket_for_a_human(
    v2: V2Fakes,
    http: Vobiz,
    seeded: Repository,
    monkeypatch: Any,
    confidence: str,
    relevant: bool,
    expected: float,
) -> None:
    agent_says(monkeypatch, NoteIssueKind.DIRTY, confidence, relevant=relevant)
    out = run_notes(report_note(seeded, v2))
    reason = TicketReason.DIRTY if expected >= notes.MIN_CONFIDENCE else TicketReason.OTHER
    assert out["issue"] == reason.value
    [ticket] = seeded.list_open_tickets(VID)
    assert ticket.reason is reason and ticket.issue is not None
    assert ticket.issue.confidence == expected


def test_failed_transcription_opens_an_other_ticket_with_zero_confidence(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: Any
) -> None:
    seen = agent_says(monkeypatch)
    http.stt = 503
    out = run_notes(report_note(seeded, v2))
    assert out["status"] == "ticket" and out["issue"] is None
    [ticket] = seeded.list_open_tickets(VID)
    assert ticket.reason is TicketReason.OTHER and ticket.issue is not None
    assert ticket.issue.confidence == 0.0 and ticket.issue.transcript == ""
    assert "not transcribed" in ticket.issue.summary_en
    assert seen == []  # nothing to label


def test_note_the_agent_could_not_label_keeps_its_transcript(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: Any
) -> None:
    monkeypatch.setattr(notes, "extract_note_details", lambda transcript: None)
    run_notes(report_note(seeded, v2))
    [ticket] = seeded.list_open_tickets(VID)
    assert ticket.reason is TicketReason.OTHER and ticket.issue is not None
    assert ticket.issue.transcript == TRANSCRIPT and ticket.issue.confidence == 0.0
    assert "not transcribed" not in ticket.issue.summary_en


def test_without_a_sarvam_key_the_note_is_kept_but_not_transcribed(
    v2: V2Fakes, seeded: Repository, monkeypatch: Any
) -> None:
    transport = Vobiz()
    config.use_http_client(httpx.Client(transport=httpx.MockTransport(transport)))
    agent_says(monkeypatch)
    out = run_notes(report_note(seeded, v2))
    assert out["status"] == "ticket" and out["audio_key"]
    assert transport.sent("POST", STT_URL) == []
    [ticket] = seeded.list_open_tickets(VID)
    assert ticket.reason is TicketReason.OTHER


def test_failed_archive_keeps_the_vobiz_copy(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_says(monkeypatch)
    job = report_note(seeded, v2)
    monkeypatch.setenv("JALSAKSHI_EVIDENCE_BUCKET", "no-such-bucket")
    config.settings.cache_clear()
    out = run_notes(job)
    assert out["audio_key"] is None and out["status"] == "ticket"
    assert http.sent("DELETE", DELETE_URL) == []  # our copy failed, so Vobiz keeps theirs


@pytest.mark.parametrize("problem", ["http_404", "foreign_host"])
def test_unfetchable_recording_fails_without_a_ticket(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: Any, problem: str
) -> None:
    agent_says(monkeypatch)
    job = report_note(seeded, v2)
    if problem == "http_404":
        http.fetch = 404
    else:
        job = {**job, "recording_url": "https://evil.example.com/rec.mp3"}
    assert run_notes(job) == {"status": "failed", "step": "fetch"}
    assert seeded.list_open_tickets(VID) == []
    assert http.sent("DELETE", DELETE_URL) == []


def test_unknown_call_or_operator_call_is_ignored(
    v2: V2Fakes, http: Vobiz, seeded: Repository
) -> None:
    assert run_notes({"call_id": "nope", "recording_url": REC_URL}) == {
        "status": "ignored",
        "reason": "unknown call",
    }
    ticket = seeded.open_ticket_if_none(new_ticket(VID, TicketReason.NO_SUPPLY, NOW))
    assert ticket is not None
    sfn_tasks.notify_operator(
        {"task_token": "t", "input": {"ticket_id": ticket.id}}, LambdaContext()
    )
    call_id = f"operator-{ticket.id}-n1"
    out = run_notes({"call_id": call_id, "recording_url": REC_URL})
    assert out == {"status": "ignored", "reason": "not a household call"}


def test_daily_note_is_attached_to_the_answer_and_the_open_ticket(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: Any
) -> None:
    agent_says(monkeypatch, NoteIssueKind.LEAK)
    on_point(seeded)
    open_ticket = seeded.open_ticket_if_none(
        new_ticket(VID, TicketReason.NO_SUPPLY, NOW, water_point_id="wp-a", number=3)
    )
    assert open_ticket is not None
    item = {"village_id": VID, "household_id": "h1", "date": DAY.isoformat(), "purpose": "DAILY"}
    call_id = sfn_tasks.place_call({"task_token": "tok", "input": item}, LambdaContext())["call_id"]
    replies = run_call(call_id, ["2", "3"])  # no water, got none: then the note prompt
    form = {"RecordUrl": REC_URL, "RecordingDuration": "9", "RecordingID": "rec-1"}
    vobiz_post("recording", {"call_id": call_id}, form)
    vobiz_post("digits", {"call_id": call_id, "turn": str(next_turn(replies[-1]))})
    out = run_notes(v2.lambdas.events(function=NOTES_FN)[-1])
    assert out["status"] == "attached"

    [answer] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert answer.note_transcript == TRANSCRIPT and answer.note_issue == "LEAK"
    [ticket] = seeded.list_open_tickets(VID)
    assert ticket.id == open_ticket.id  # a daily note never opens a ticket of its own
    note = ticket.events[-1]
    assert note.kind == "NOTE" and note.actor == "resident:voice-note"
    assert note.detail["note"] == "voice_note" and note.detail["household_id"] == "h1"
    assert note.detail["transcript"] == TRANSCRIPT


def test_daily_note_without_an_open_ticket_only_updates_the_answer(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: Any
) -> None:
    agent_says(monkeypatch, NoteIssueKind.OTHER, relevant=False)
    item = {"village_id": VID, "household_id": "h1", "date": DAY.isoformat(), "purpose": "DAILY"}
    call_id = sfn_tasks.place_call({"task_token": "tok", "input": item}, LambdaContext())["call_id"]
    replies = run_call(call_id, ["1", "5", "1"])  # water came, 5 hours, clean: note prompt
    form = {"RecordUrl": REC_URL, "RecordingDuration": "4", "RecordingID": "rec-1"}
    vobiz_post("recording", {"call_id": call_id}, form)
    vobiz_post("digits", {"call_id": call_id, "turn": str(next_turn(replies[-1]))})
    assert run_notes(v2.lambdas.events(function=NOTES_FN)[-1])["status"] == "attached"
    [answer] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert answer.note_transcript == TRANSCRIPT and answer.note_issue == "OTHER"
    assert seeded.list_open_tickets(VID) == []


def test_note_from_a_household_that_withdrew_meanwhile_is_dropped(
    v2: V2Fakes, http: Vobiz, seeded: Repository, monkeypatch: Any
) -> None:
    agent_says(monkeypatch)
    job = report_note(seeded, v2)
    seeded.delete_household(VID, "h1")
    assert run_notes(job)["status"] == "no_household"
    assert seeded.list_open_tickets(VID) == []
