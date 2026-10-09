"""Voice notes to complaints (ARCHITECTURE.md §15.6), run asynchronously after a call.

Input: ``{"call_id", "recording_url", "recording_id"}`` from the IVR handler. Steps: fetch the
recording from Vobiz (authenticated, Vobiz hosts only), keep it in the evidence bucket under
``audio/`` (encrypted, 365-day lifecycle), delete Vobiz's copy, transcribe it with Sarvam, and let
the agent label it. A note from the missed-call menu opens or joins a complaint; a note left on a
daily call is attached to that day's answer and, if the household's water point has an open
complaint, to that complaint as a NOTE. The AI never closes or reopens anything.
"""

from __future__ import annotations

import time
from typing import Any, Final

from jalsakshi.agent.notes import NoteIssueKind, extract_note_details
from jalsakshi.agent.reader import read_intro
from jalsakshi.core.models import NoteIssue, Purpose, TicketOrigin, TicketReason
from jalsakshi.core.tickets import Denied
from jalsakshi.handlers import config, residents, speech
from jalsakshi.handlers.calls import CallRecord, load_call
from jalsakshi.handlers.common import activity, count, entrypoint, logger
from jalsakshi.store import Repository
from jalsakshi.voice.recordings import (
    RecordingError,
    archive_recording,
    delete_vobiz_recording,
    fetch_recording,
)
from jalsakshi.voice.stt import SttError, transcribe

CONFIDENCE: Final = {"high": 0.9, "medium": 0.7, "low": 0.3}
MIN_CONFIDENCE: Final = 0.6
INTRO_WAITS: Final = 4
INTRO_WAIT_S: Final = 2.0
ISSUE_REASONS: Final = {
    NoteIssueKind.NO_WATER: TicketReason.NO_SUPPLY,
    NoteIssueKind.LOW_PRESSURE: TicketReason.LOW_PRESSURE,
    NoteIssueKind.DIRTY: TicketReason.DIRTY,
    NoteIssueKind.LEAK: TicketReason.LEAK,
    NoteIssueKind.BROKEN: TicketReason.BROKEN,
    NoteIssueKind.OTHER: TicketReason.OTHER,
}


@entrypoint
def handler(event: Any, context: Any) -> dict[str, Any]:
    """Process one voice note end to end (best effort; failures are logged, not retried)."""
    payload = event if isinstance(event, dict) else {}
    repo = config.repository()
    loaded = load_call(repo, str(payload.get("call_id", "")))
    if loaded is None:
        return {"status": "ignored", "reason": "unknown call"}
    record = loaded.record
    flow = record.flow
    if not (flow.village_id and flow.household_id):
        return {"status": "ignored", "reason": "not a household call"}
    try:
        audio = fetch_recording(
            str(payload.get("recording_url", "")), speech.vobiz_auth(), config.http_client()
        )
    except RecordingError as exc:
        logger.warning("recording fetch failed", extra={"error": str(exc)})
        return {"status": "failed", "step": "fetch"}
    key = _archive(audio, flow.village_id, record.call_id)
    if key and payload.get("recording_id"):  # keep Vobiz's copy unless ours is safely stored
        delete_vobiz_recording(
            str(payload["recording_id"]), speech.vobiz_auth(), config.http_client()
        )
    transcript = _transcribe(audio)
    understand = transcript and record.flow.purpose is not Purpose.REGISTER
    issue = _understand(transcript) if understand else None
    result = _apply(repo, record, transcript, issue)
    count("VoiceNotes", outcome=result)
    return {"status": result, "audio_key": key, "issue": issue.issue if issue else None}


def _archive(audio: bytes, village_id: str, call_id: str) -> str | None:
    bucket = config.settings().evidence_bucket
    if not bucket:
        return None
    try:
        return archive_recording(
            audio, s3=config.client("s3"), bucket=bucket, village_id=village_id, call_id=call_id
        )
    except RecordingError as exc:
        logger.warning("recording not archived", extra={"error": str(exc)})
        return None


def _transcribe(audio: bytes) -> str | None:
    key = config.secrets.get(config.SARVAM_API_KEY_PARAM, required=False)
    if not key:
        logger.warning("no Sarvam key: note not transcribed")
        return None
    try:
        return transcribe(audio, "note.mp3", api_key=key, http=config.http_client()).text
    except SttError as exc:
        logger.warning("transcription failed", extra={"error": str(exc)})
        return None


def _understand(transcript: str) -> NoteIssue | None:
    found = extract_note_details(transcript)
    if found is None:
        return None
    extraction, model_id = found
    confidence = CONFIDENCE[extraction.confidence] if extraction.relevant else 0.2
    reason = ISSUE_REASONS[extraction.issue] if extraction.relevant else TicketReason.OTHER
    if confidence < MIN_CONFIDENCE:
        reason = TicketReason.OTHER
    return NoteIssue(
        issue=reason,
        summary_hi=transcript[:500],
        summary_en=(extraction.summary_en or "Resident left a voice note.")[:300],
        transcript=transcript[:1500],
        location_hint=extraction.location_hint,
        days_affected=extraction.days_affected,
        confidence=confidence,
        model_id=model_id,
    )


def _apply_intro(repo: Repository, record: CallRecord, transcript: str | None) -> str:
    """A first call's "name and mohalla": fill the family's name and area (never invented)."""
    flow = record.flow
    household = None
    for attempt in range(INTRO_WAITS):
        household = repo.get_household(flow.village_id or "", flow.household_id or "")
        if household is not None:
            break
        time.sleep(INTRO_WAIT_S * (attempt + 1))  # the call may still be finishing
    if household is None or not transcript:
        return "no_intro"
    intro = read_intro(transcript)
    update: dict[str, object] = {}
    if intro is not None and intro.name and not household.display_name:
        update["display_name"] = intro.name
    if intro is not None and intro.area and not household.hamlet:
        update["hamlet"] = intro.area
    if not update:
        return "no_intro"
    repo.put_household(household.model_copy(update=update))
    return "intro"


def _apply(
    repo: Repository, record: CallRecord, transcript: str | None, issue: NoteIssue | None
) -> str:
    flow = record.flow
    if flow.purpose is Purpose.REGISTER:
        return _apply_intro(repo, record, transcript)
    village = repo.get_village(flow.village_id or "")
    household = repo.get_household(flow.village_id or "", flow.household_id or "")
    if village is None or household is None:
        return "no_household"
    if flow.purpose is Purpose.REPORT:
        note = issue or NoteIssue(
            issue=TicketReason.OTHER,
            summary_hi=transcript or "",
            summary_en=(
                "Voice complaint (not labelled by AI): read the transcript."
                if transcript
                else "Voice complaint (not transcribed): listen to the recording."
            ),
            transcript=transcript or "",
            confidence=0.0,
        )
        ticket = residents.report_problem(
            repo, village, household, note.issue, origin=TicketOrigin.VOICE_NOTE, issue=note
        )
        activity(
            "ticket",
            village.id,
            f"Voice complaint #{ticket.number}: {note.summary_en} (AI-transcribed, unconfirmed)",
            f"आवाज़ से शिकायत क्रमांक {ticket.number}: {note.summary_hi[:120]}",
        )
        return "ticket"
    _attach_to_checkin(repo, record, transcript, issue)
    open_ticket = repo.get_open_ticket(village.id, household.water_point_id)
    if open_ticket is not None and transcript:
        detail = {
            "note": "voice_note",
            "household_id": household.id,
            "summary_en": issue.summary_en if issue else None,
            "transcript": transcript[:500],
        }
        result = residents.update_ticket(
            repo, open_ticket.id, lambda t: t, detail, "resident:voice-note"
        )
        if isinstance(result, Denied):
            logger.warning("note not attached", extra={"reason": result.reason})
    return "attached"


def _attach_to_checkin(
    repo: Repository, record: CallRecord, transcript: str | None, issue: NoteIssue | None
) -> None:
    flow = record.flow
    for checkin in repo.list_checkins(flow.village_id or "", record.day, flow.purpose):
        if checkin.call_id == record.call_id:
            repo.replace_checkin(
                checkin.model_copy(
                    update={
                        "note_transcript": transcript,
                        "note_issue": issue.issue.value if issue else None,
                    }
                )
            )
            return
