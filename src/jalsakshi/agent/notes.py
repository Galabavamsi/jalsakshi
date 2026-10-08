"""Spoken note to structured issue (docs/ARCHITECTURE.md section 10).

The keypad answers stay the record. This only adds an optional, best-effort label: empty input,
an irrelevant or low-confidence note, or any failure returns ``None``.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, Field

from jalsakshi.agent import models as agent_models
from jalsakshi.agent.prompts import NOTE_SYSTEM_PROMPT, note_user_prompt

if TYPE_CHECKING:
    from strands import Agent
    from strands.models.model import Model

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS: Final = 1500
MAX_LOCATION_CHARS: Final = 80
MAX_DAYS: Final = 365
NOTE_MAX_TOKENS: Final = 512
NOTE_READ_TIMEOUT_S: Final = 30


class NoteIssueKind(StrEnum):
    NO_WATER = "NO_WATER"
    LOW_PRESSURE = "LOW_PRESSURE"
    DIRTY = "DIRTY"
    LEAK = "LEAK"
    OTHER = "OTHER"


class NoteIssue(BaseModel):
    """The issue a household described in its optional voice note."""

    issue: NoteIssueKind
    days_affected: int | None = Field(default=None, ge=0, le=MAX_DAYS)
    location_hint: str | None = Field(default=None, max_length=MAX_LOCATION_CHARS)


class NoteExtraction(BaseModel):
    """Classification of a household's voice note about its tap water."""

    relevant: bool = Field(description="True only if the note reports a tap-water problem.")
    issue: NoteIssueKind = Field(description="Kind of problem described.")
    days_affected: int | None = Field(
        default=None, ge=0, description="Days the problem lasted, only if stated; else null."
    )
    location_hint: str | None = Field(
        default=None, description="Short place mention from the note, max 60 chars; else null."
    )
    confidence: Literal["high", "medium", "low"] = Field(description="Certainty about the issue.")


def extract_note_issue(
    transcript_hi: str,
    *,
    model_factory: agent_models.ModelFactory | None = None,
) -> NoteIssue | None:
    """Classify a Hindi note transcript; ``None`` when empty, unclear or anything fails."""
    transcript = _clean_transcript(transcript_hi)
    if not transcript:
        return None
    factory = model_factory or partial(
        agent_models.make_model, max_tokens=NOTE_MAX_TOKENS, read_timeout_s=NOTE_READ_TIMEOUT_S
    )
    try:
        extraction, model_id = agent_models.run_with_fallback(
            _build_note_agent,
            partial(_extract, transcript=transcript),
            model_factory=factory,
        )
        issue = to_note_issue(extraction)
    except Exception as exc:  # any failure means "no label"; the keypad answers stand
        logger.warning("note extraction failed", extra={"error_type": type(exc).__name__})
        return None
    logger.info("note extracted", extra={"model_id": model_id, "found": issue is not None})
    return issue


def to_note_issue(extraction: NoteExtraction) -> NoteIssue | None:
    """Keep only relevant, confident extractions, with bounded fields."""
    if not extraction.relevant or extraction.confidence == "low":
        return None
    days = extraction.days_affected
    location = (extraction.location_hint or "").strip()[:MAX_LOCATION_CHARS] or None
    return NoteIssue(
        issue=extraction.issue,
        days_affected=days if days is not None and days <= MAX_DAYS else None,
        location_hint=location,
    )


def _clean_transcript(transcript: str | None) -> str:
    """Trim, bound the length and neutralise tag characters in an untrusted transcript."""
    text = " ".join((transcript or "").split())
    return text.replace("<", "(").replace(">", ")")[:MAX_TRANSCRIPT_CHARS]


def _build_note_agent(model: Model) -> Agent:
    return agent_models.new_agent(model, name="jalsakshi-notes", system_prompt=NOTE_SYSTEM_PROMPT)


def _extract(agent: Agent, *, transcript: str) -> NoteExtraction:
    result = agent(note_user_prompt(transcript), structured_output_model=NoteExtraction)
    output = result.structured_output
    if not isinstance(output, NoteExtraction):
        raise TypeError("agent returned no NoteExtraction")
    return output
