"""Provider-agnostic Hindi IVR flow: a pure state machine over ``FlowSession`` (ARCHITECTURE §9).

Flows (each question is one keypad digit):

- DAILY household: greet, q_water (1 yes / 2 no / 3 partly), q_hours (0-9) and q_clean
  (1 clean / 2 dirty) only after 1 or 3, an optional spoken note (``#`` skips), bye.
- VERIFY household: greet, q_water (1 yes / 2 no), bye.
- OPERATOR: greet, ticket summary, q_fixed (1 fixed / 2 not yet), acknowledgement.

A question is re-prompted once on an invalid key or a timeout; after that the answer is ``None``
and the flow moves on. A missing answer is never guessed. ``turn`` grows by one on every step the
engine produces, so a handler can put it in the provider's action URL and drop duplicate webhooks.

The engine does no I/O: the session goes in, a new session plus actions come out.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from jalsakshi.core.models import CallOutcome, CleanAnswer, Purpose, TicketReason, WaterAnswer
from jalsakshi.voice.actions import Action, GetDigits, Hangup, Play, Record
from jalsakshi.voice.catalog import PromptCatalog, default_catalog

MAX_RETRIES = 1
QUESTION_TIMEOUT_S = 10
NOTE_MAX_S = 15
INVALID_PROMPT = "household.invalid"
NOTE_PROMPT = "household.q_note"


class FlowStep(StrEnum):
    """Where a call is: the input the engine is waiting for, or START / DONE."""

    START = "START"
    Q_WATER = "Q_WATER"
    Q_HOURS = "Q_HOURS"
    Q_CLEAN = "Q_CLEAN"
    Q_NOTE = "Q_NOTE"
    Q_FIXED = "Q_FIXED"
    DONE = "DONE"


class FlowAnswers(BaseModel):
    """Answers so far. ``None`` means not asked, or asked twice without a valid key."""

    water: WaterAnswer | None = None
    hours: int | None = Field(default=None, ge=0, le=24)
    clean: CleanAnswer | None = None
    fixed: bool | None = None
    note_recording_url: str | None = None


class FlowSession(BaseModel):
    """One call's IVR state; stored as a dict on the ``CALL#{call_id}`` item."""

    call_id: str = Field(min_length=1)
    purpose: Purpose
    step: FlowStep = FlowStep.START
    answers: FlowAnswers = Field(default_factory=FlowAnswers)
    retries: int = Field(default=0, ge=0)
    turn: int = Field(default=0, ge=0)
    village_id: str | None = None
    household_id: str | None = None
    operator_id: str | None = None
    ticket_id: str | None = None
    ticket_reason: TicketReason | None = None
    reported_households: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _operator_needs_ticket(self) -> Self:
        if self.purpose is Purpose.OPERATOR and (
            self.ticket_reason is None or self.reported_households is None
        ):
            raise ValueError("an OPERATOR call needs ticket_reason and reported_households")
        return self

    @property
    def done(self) -> bool:
        """True once the closing prompt and hangup have been issued."""
        return self.step is FlowStep.DONE

    def to_item(self) -> dict[str, Any]:
        """JSON-safe dict for storage."""
        return self.model_dump(mode="json")

    @classmethod
    def from_item(cls, item: Mapping[str, Any]) -> FlowSession:
        """Rebuild from a stored dict (DynamoDB numbers may arrive as Decimal)."""
        return cls.model_validate(dict(item))


@dataclass(frozen=True, slots=True)
class _Question:
    prompt_key: str
    field: str
    choices: Mapping[str, object]


_WATER_DAILY = {"1": WaterAnswer.YES, "2": WaterAnswer.NO, "3": WaterAnswer.PARTIAL}
_WATER_VERIFY = {"1": WaterAnswer.YES, "2": WaterAnswer.NO}
_HOURS = {str(hours): hours for hours in range(10)}
_CLEAN = {"1": CleanAnswer.YES, "2": CleanAnswer.NO}
_FIXED = {"1": True, "2": False}

_QUESTIONS: dict[tuple[Purpose, FlowStep], _Question] = {
    (Purpose.DAILY, FlowStep.Q_WATER): _Question("household.q_water", "water", _WATER_DAILY),
    (Purpose.DAILY, FlowStep.Q_HOURS): _Question("household.q_hours", "hours", _HOURS),
    (Purpose.DAILY, FlowStep.Q_CLEAN): _Question("household.q_clean", "clean", _CLEAN),
    (Purpose.VERIFY, FlowStep.Q_WATER): _Question("verify.q_water", "water", _WATER_VERIFY),
    (Purpose.OPERATOR, FlowStep.Q_FIXED): _Question("operator.q_fixed", "fixed", _FIXED),
}
_FIRST_STEP = {
    Purpose.DAILY: FlowStep.Q_WATER,
    Purpose.VERIFY: FlowStep.Q_WATER,
    Purpose.OPERATOR: FlowStep.Q_FIXED,
}
_SUMMARY_PROMPT = {
    TicketReason.NO_SUPPLY: "operator.summary_no_supply",
    TicketReason.DIRTY: "operator.summary_dirty",
}
_WATER_CAME = frozenset({WaterAnswer.YES, WaterAnswer.PARTIAL})


def start(
    session: FlowSession, catalog: PromptCatalog | None = None
) -> tuple[FlowSession, list[Action]]:
    """Begin the call: greeting plus the first question. Replays the current step if started."""
    cat = catalog or default_catalog()
    if session.step is not FlowStep.START:
        return session, current_actions(session, cat)
    first = session.model_copy(
        update={"step": _FIRST_STEP[session.purpose], "retries": 0, "turn": session.turn + 1}
    )
    return first, [*_intro(first, cat), *_step_actions(first, cat)]


def on_input(
    session: FlowSession,
    digits: str | None,
    timeout: bool = False,
    recording_url: str | None = None,
    catalog: PromptCatalog | None = None,
) -> tuple[FlowSession, list[Action], bool]:
    """Apply one keypad result (or timeout, or finished recording); return the next actions."""
    cat = catalog or default_catalog()
    if session.step is FlowStep.START:
        started, actions = start(session, cat)
        return started, actions, False
    if session.step is FlowStep.DONE:
        return session, [Hangup()], True
    if session.step is FlowStep.Q_NOTE:
        return _finish_note(session, recording_url, cat)
    question = _QUESTIONS[(session.purpose, session.step)]
    key = _normalise(digits)
    if not timeout and key in question.choices:
        return _advance(session, question.field, question.choices[key], cat)
    if session.retries < MAX_RETRIES:
        again = session.model_copy(
            update={"retries": session.retries + 1, "turn": session.turn + 1}
        )
        return again, [_play(cat, INVALID_PROMPT), *_question_actions(question, cat)], False
    return _advance(session, question.field, None, cat)


def current_actions(session: FlowSession, catalog: PromptCatalog | None = None) -> list[Action]:
    """Actions for the step the session is waiting on (for replaying a duplicate webhook)."""
    cat = catalog or default_catalog()
    if session.step is FlowStep.START:
        return start(session, cat)[1]
    return _step_actions(session, cat)


def with_recording(session: FlowSession, recording_url: str) -> FlowSession:
    """Attach a note recording that arrived after the flow moved on (provider callback)."""
    answers = session.answers.model_copy(update={"note_recording_url": recording_url})
    return session.model_copy(update={"answers": answers})


def result_to_checkin_fields(session: FlowSession) -> dict[str, Any]:
    """CheckIn fields from a household call: ``outcome``, ``water``, ``hours``, ``clean``.

    A pickup without a usable water answer is ``UNREACHABLE``, so it can never help a quorum.
    Works on unfinished sessions too (caller hung up mid-flow).
    """
    if session.purpose is Purpose.OPERATOR:
        raise ValueError("operator calls do not produce a CheckIn")
    answers = session.answers
    outcome = CallOutcome.ANSWERED if answers.water is not None else CallOutcome.UNREACHABLE
    return {
        "outcome": outcome,
        "water": answers.water,
        "hours": answers.hours,
        "clean": answers.clean,
    }


def result_to_operator(session: FlowSession) -> dict[str, bool | None]:
    """Operator's report: ``{"fixed": True | False | None}``."""
    if session.purpose is not Purpose.OPERATOR:
        raise ValueError("only operator calls report a fix")
    return {"fixed": session.answers.fixed}


def _advance(
    session: FlowSession, field: str, value: object, cat: PromptCatalog
) -> tuple[FlowSession, list[Action], bool]:
    answers = session.answers.model_copy(update={field: value})
    answered = session.model_copy(update={"answers": answers})
    moved = answered.model_copy(
        update={"step": _next_step(answered), "retries": 0, "turn": session.turn + 1}
    )
    return moved, _step_actions(moved, cat), moved.done


def _finish_note(
    session: FlowSession, recording_url: str | None, cat: PromptCatalog
) -> tuple[FlowSession, list[Action], bool]:
    noted = with_recording(session, recording_url) if recording_url else session
    done = noted.model_copy(update={"step": FlowStep.DONE, "retries": 0, "turn": session.turn + 1})
    return done, _step_actions(done, cat), True


def _next_step(session: FlowSession) -> FlowStep:
    match (session.purpose, session.step):
        case (Purpose.DAILY, FlowStep.Q_WATER):
            came = session.answers.water in _WATER_CAME
            return FlowStep.Q_HOURS if came else FlowStep.Q_NOTE
        case (Purpose.DAILY, FlowStep.Q_HOURS):
            return FlowStep.Q_CLEAN
        case (Purpose.DAILY, FlowStep.Q_CLEAN):
            return FlowStep.Q_NOTE
        case _:
            return FlowStep.DONE


def _step_actions(session: FlowSession, cat: PromptCatalog) -> list[Action]:
    if session.step is FlowStep.Q_NOTE:
        return [_play(cat, NOTE_PROMPT), Record(max_s=NOTE_MAX_S)]
    if session.step is FlowStep.DONE:
        return [_play(cat, _closing_prompt(session)), Hangup()]
    return _question_actions(_QUESTIONS[(session.purpose, session.step)], cat)


def _question_actions(question: _Question, cat: PromptCatalog) -> list[Action]:
    prompt = _play(cat, question.prompt_key)
    return [GetDigits(num_digits=1, timeout_s=QUESTION_TIMEOUT_S, prompts=[prompt])]


def _intro(session: FlowSession, cat: PromptCatalog) -> list[Action]:
    if session.purpose is Purpose.DAILY:
        return [_play(cat, "household.greet")]
    if session.purpose is Purpose.VERIFY:
        return [_play(cat, "verify.greet")]
    if session.ticket_reason is None or session.reported_households is None:
        raise ValueError("an OPERATOR call needs ticket_reason and reported_households")
    summary_key = _SUMMARY_PROMPT[session.ticket_reason]
    summary = _play(cat, summary_key, households=session.reported_households)
    return [_play(cat, "operator.greet"), summary]


def _closing_prompt(session: FlowSession) -> str:
    if session.purpose is Purpose.DAILY:
        return "household.bye"
    if session.purpose is Purpose.VERIFY:
        return "verify.bye"
    return "operator.ack_fixed" if session.answers.fixed is True else "operator.ack_pending"


def _play(cat: PromptCatalog, key: str, **variables: object) -> Play:
    clip = cat.audio_key(key, **variables)
    return Play(prompt_key=clip or key, text_hi=cat.text(key, **variables))


def _normalise(digits: str | None) -> str | None:
    if digits is None:
        return None
    cleaned = digits.strip()
    return cleaned or None
