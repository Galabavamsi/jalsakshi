"""Provider-agnostic Hindi IVR flow: a pure state machine over ``FlowSession`` (ARCHITECTURE §9).

Flows (each question is one keypad digit; 9 on the first question of a household call asks to
stop all calls):

- DAILY household: greet, q_water named after the family's own source (1 yes / 2 no / 3 partly),
  q_hours (piped water only) and q_clean after 1 or 3, q_fallback after 2 (where did you get
  water instead), an optional spoken note (``#`` skips), bye.
- VERIFY household: greet, q_water (1 yes / 2 no), bye.
- OPERATOR: greet, ticket summary (and where / which complaint), q_fixed (1 fixed, or 2-7 the
  reason it is not: parts, no electricity, broken pipe, not my job, 6 something else, 7 needs
  the Panchayat); after 6 or 7 a spoken note (``#`` ends it), acknowledgement.
- REGISTER: greet, the consent notice, q_age (18+), q_consent (1 agree / 2 hear again / 3 no),
  q_access (which source the family uses), confirmation. Silence never counts as consent.
- REPORT (call-back after a missed call): q_menu (1 no water / 2 dirty / 3 speak a complaint /
  4 hear today's status / 9 stop calls), acknowledgement.
- BROADCAST, SUMMARY and ALERT (a complaint sent to the Sarpanch): intro, the message (text
  given by the caller), q_heard (1 heard / 2 repeat once), bye.

A question is re-prompted once on an invalid key or a timeout; after that the answer is ``None``
and the flow moves on. A missing answer is never guessed. ``turn`` grows by one on every step the
engine produces, so a handler can put it in the provider's action URL and drop duplicate webhooks.

The engine does no I/O: the session goes in, a new session plus actions come out. Prompts whose
text is only known at call time (a water point's name, an announcement) are emitted as ``Play``
actions without a pre-rendered clip; the handler renders them with runtime TTS.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from jalsakshi.core.models import (
    AccessKind,
    BlockerCode,
    CallOutcome,
    CleanAnswer,
    Fallback,
    Purpose,
    TicketReason,
    WaterAnswer,
)
from jalsakshi.voice.actions import Action, GetDigits, Hangup, Play, Record
from jalsakshi.voice.catalog import PromptCatalog, catalog_for

MAX_RETRIES = 1
QUESTION_TIMEOUT_S = 15
NOTE_MAX_S = 15
REPORT_NOTE_MAX_S = 25
OPERATOR_NOTE_MAX_S = 30
MAX_NOTICE_PLAYS = 3
MAX_MENU_LOOPS = 2
MAX_MESSAGE_REPLAYS = 1
STOP_KEY = "9"
INVALID_PROMPT = "household.invalid"
NOTE_PROMPT = "household.q_note"
NOTICE_REVISION = 2
INTRO_MAX_S = 12


def notice_version(language: str) -> str:
    """Version tag of the consent notice read in this language (stored in the ledger)."""
    return f"{language}-{NOTICE_REVISION}"


NOTICE_VERSION = notice_version("hi")


class FlowStep(StrEnum):
    """Where a call is: the input the engine is waiting for, or START / DONE."""

    START = "START"
    Q_LANG = "Q_LANG"
    Q_WATER = "Q_WATER"
    Q_HOURS = "Q_HOURS"
    Q_CLEAN = "Q_CLEAN"
    Q_FALLBACK = "Q_FALLBACK"
    Q_NOTE = "Q_NOTE"
    Q_FIXED = "Q_FIXED"
    Q_AGE = "Q_AGE"
    Q_CONSENT = "Q_CONSENT"
    Q_ACCESS = "Q_ACCESS"
    Q_MENU = "Q_MENU"
    Q_STOP = "Q_STOP"
    Q_HEARD = "Q_HEARD"
    DONE = "DONE"


class ReportChoice(StrEnum):
    """What a resident chose in the missed-call menu."""

    NO_WATER = "NO_WATER"
    DIRTY = "DIRTY"
    NOTE = "NOTE"


class ConsentAnswer(StrEnum):
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"


class FlowAnswers(BaseModel):
    """Answers so far. ``None`` means not asked, or asked twice without a valid key."""

    water: WaterAnswer | None = None
    hours: int | None = Field(default=None, ge=0, le=24)
    clean: CleanAnswer | None = None
    fallback: Fallback | None = None
    fixed: bool | None = None
    blocker: BlockerCode | None = None
    note_recording_url: str | None = None
    adult: bool | None = None
    consent: ConsentAnswer | None = None
    consent_digits: str | None = None
    access: AccessKind | None = None
    report: ReportChoice | None = None
    heard: bool | None = None
    stop: bool | None = None


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
    ticket_number: int | None = Field(default=None, ge=1)
    water_point_name: str | None = None
    access: AccessKind | None = None
    message_text_hi: str | None = None
    language: str | None = None
    offered_languages: list[str] = Field(default_factory=list)
    notice_plays: int = Field(default=0, ge=0)
    menu_loops: int = Field(default=0, ge=0)
    replays: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_purpose_fields(self) -> Self:
        if self.purpose is Purpose.OPERATOR and (
            self.ticket_reason is None or self.reported_households is None
        ):
            raise ValueError("an OPERATOR call needs ticket_reason and reported_households")
        if self.purpose in _MESSAGE_PURPOSES and not self.message_text_hi:
            raise ValueError(f"a {self.purpose} call needs message_text_hi")
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
_FALLBACK = {"1": Fallback.OTHER_SOURCE, "2": Fallback.BOUGHT, "3": Fallback.NONE}
_FIXED = {"1": True, "2": False, "3": False, "4": False, "5": False, "6": False, "7": False}
_BLOCKERS = {
    "2": BlockerCode.PARTS_NEEDED,
    "3": BlockerCode.NO_POWER,
    "4": BlockerCode.PIPE_BROKEN,
    "5": BlockerCode.NOT_MINE,
    "6": BlockerCode.OTHER,
    "7": BlockerCode.NEEDS_PANCHAYAT,
}
_SPOKEN_BLOCKERS = frozenset({BlockerCode.OTHER, BlockerCode.NEEDS_PANCHAYAT})
_MESSAGE_PURPOSES = frozenset({Purpose.BROADCAST, Purpose.SUMMARY, Purpose.ALERT})
_AGE = {"1": True, "2": False}
_ACCESS = {
    "1": AccessKind.HOUSE_TAP,
    "2": AccessKind.STANDPOST,
    "3": AccessKind.HANDPUMP,
    "4": AccessKind.BOREWELL,
    "5": AccessKind.TANKER,
}
_MENU = {"1": ReportChoice.NO_WATER, "2": ReportChoice.DIRTY, "3": ReportChoice.NOTE}
_STOP = {STOP_KEY: True, "0": False}
_HEARD = {"1": True}

_WATER_PROMPTS: Mapping[AccessKind | None, str] = {
    None: "household.q_water",
    AccessKind.HOUSE_TAP: "household.q_water_house_tap",
    AccessKind.STANDPOST: "household.q_water_standpost",
    AccessKind.HANDPUMP: "household.q_water_handpump",
    AccessKind.BOREWELL: "household.q_water_borewell",
    AccessKind.TANKER: "household.q_water_tanker",
    AccessKind.OTHER: "household.q_water",
}
_PIPED_OR_UNKNOWN = frozenset({None, AccessKind.HOUSE_TAP, AccessKind.STANDPOST})

_FIXED_QUESTIONS: dict[tuple[Purpose, FlowStep], _Question] = {
    (Purpose.DAILY, FlowStep.Q_HOURS): _Question("household.q_hours", "hours", _HOURS),
    (Purpose.DAILY, FlowStep.Q_CLEAN): _Question("household.q_clean", "clean", _CLEAN),
    (Purpose.DAILY, FlowStep.Q_FALLBACK): _Question("household.q_fallback", "fallback", _FALLBACK),
    (Purpose.VERIFY, FlowStep.Q_WATER): _Question("verify.q_water", "water", _WATER_VERIFY),
    (Purpose.OPERATOR, FlowStep.Q_FIXED): _Question("operator.q_fixed", "fixed", _FIXED),
    (Purpose.REGISTER, FlowStep.Q_AGE): _Question("register.q_age", "adult", _AGE),
    (Purpose.REGISTER, FlowStep.Q_ACCESS): _Question("register.q_access", "access", _ACCESS),
    (Purpose.REPORT, FlowStep.Q_MENU): _Question("report.menu", "report", _MENU),
    (Purpose.BROADCAST, FlowStep.Q_HEARD): _Question("broadcast.q_heard", "heard", _HEARD),
    (Purpose.SUMMARY, FlowStep.Q_HEARD): _Question("broadcast.q_heard", "heard", _HEARD),
    (Purpose.ALERT, FlowStep.Q_HEARD): _Question("broadcast.q_heard", "heard", _HEARD),
}
_STOP_QUESTION = _Question("stop.q_confirm", "stop", _STOP)
_FIRST_STEP = {
    Purpose.DAILY: FlowStep.Q_WATER,
    Purpose.VERIFY: FlowStep.Q_WATER,
    Purpose.OPERATOR: FlowStep.Q_FIXED,
    Purpose.REGISTER: FlowStep.Q_AGE,
    Purpose.REPORT: FlowStep.Q_MENU,
    Purpose.BROADCAST: FlowStep.Q_HEARD,
    Purpose.SUMMARY: FlowStep.Q_HEARD,
    Purpose.ALERT: FlowStep.Q_HEARD,
}
_STOPPABLE = frozenset(
    {
        (Purpose.DAILY, FlowStep.Q_WATER),
        (Purpose.VERIFY, FlowStep.Q_WATER),
        (Purpose.REPORT, FlowStep.Q_MENU),
    }
)
_SUMMARY_PROMPT = {
    TicketReason.NO_SUPPLY: "operator.summary_no_supply",
    TicketReason.DIRTY: "operator.summary_dirty",
    TicketReason.LOW_PRESSURE: "operator.summary_low_pressure",
    TicketReason.LEAK: "operator.summary_leak",
    TicketReason.BROKEN: "operator.summary_broken",
    TicketReason.OTHER: "operator.summary_other",
}
_INTRO = {
    Purpose.DAILY: "household.greet",
    Purpose.VERIFY: "verify.greet",
    Purpose.REPORT: "report.greet",
    Purpose.BROADCAST: "broadcast.greet",
    Purpose.SUMMARY: "summary.greet",
    Purpose.ALERT: "alert.greet",
}
_WATER_CAME = frozenset({WaterAnswer.YES, WaterAnswer.PARTIAL})


def start(
    session: FlowSession, catalog: PromptCatalog | None = None
) -> tuple[FlowSession, list[Action]]:
    """Begin the call: greeting plus the first question. Replays the current step if started."""
    cat = catalog or catalog_for(session.language)
    if session.step is not FlowStep.START:
        return session, current_actions(session, cat)
    first_step = _FIRST_STEP[session.purpose]
    if session.purpose is Purpose.REGISTER and len(session.offered_languages) > 1:
        first_step = FlowStep.Q_LANG
    first = session.model_copy(
        update={
            "step": first_step,
            "retries": 0,
            "turn": session.turn + 1,
            "notice_plays": 1 if session.purpose is Purpose.REGISTER else session.notice_plays,
        }
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
    cat = catalog or catalog_for(session.language)
    if session.step is FlowStep.START:
        started, actions = start(session, cat)
        return started, actions, False
    if session.step is FlowStep.DONE:
        return session, [Hangup()], True
    if session.step is FlowStep.Q_NOTE:
        return _finish_note(session, recording_url, cat)
    key = None if timeout else _normalise(digits)
    special = _special_input(session, key, cat)
    if special is not None:
        return special
    question = _question(session)
    if key is not None and key in question.choices:
        return _advance(session, question.field, question.choices[key], cat, key)
    if session.retries < MAX_RETRIES:
        again = session.model_copy(
            update={"retries": session.retries + 1, "turn": session.turn + 1}
        )
        return again, [_play(cat, INVALID_PROMPT), *_question_actions(again, cat)], False
    return _advance(session, question.field, None, cat, key)


def current_actions(session: FlowSession, catalog: PromptCatalog | None = None) -> list[Action]:
    """Actions for the step the session is waiting on (for replaying a duplicate webhook)."""
    cat = catalog or catalog_for(session.language)
    if session.step is FlowStep.START:
        return start(session, cat)[1]
    return _step_actions(session, cat)


def with_recording(session: FlowSession, recording_url: str) -> FlowSession:
    """Attach a note recording that arrived after the flow moved on (provider callback)."""
    answers = session.answers.model_copy(update={"note_recording_url": recording_url})
    return session.model_copy(update={"answers": answers})


def result_to_checkin_fields(session: FlowSession) -> dict[str, Any]:
    """CheckIn fields from a household call: ``outcome``, ``water``, ``hours``, ``clean``, ...

    A pickup without a usable water answer is ``UNREACHABLE``, so it can never help a quorum.
    A REPORT maps "no water" to water NO and "dirty" to water YES + clean NO. Works on
    unfinished sessions too (caller hung up mid-flow).
    """
    if session.purpose not in (Purpose.DAILY, Purpose.VERIFY, Purpose.REPORT):
        raise ValueError(f"{session.purpose} calls do not produce a CheckIn")
    answers = session.answers
    water, clean = answers.water, answers.clean
    if session.purpose is Purpose.REPORT:
        water, clean = _REPORT_ANSWERS.get(answers.report, (None, None))
    outcome = CallOutcome.ANSWERED if water is not None else CallOutcome.UNREACHABLE
    return {
        "outcome": outcome,
        "water": water,
        "hours": answers.hours,
        "clean": clean,
        "fallback": answers.fallback,
    }


def result_to_operator(session: FlowSession) -> dict[str, Any]:
    """Operator's report: ``{"fixed": True | False | None, "blocker": BlockerCode | None}``."""
    if session.purpose is not Purpose.OPERATOR:
        raise ValueError("only operator calls report a fix")
    return {"fixed": session.answers.fixed, "blocker": session.answers.blocker}


def result_to_registration(session: FlowSession) -> dict[str, Any]:
    """Registration outcome: ``adult``, ``consent``, ``consent_digits`` and ``access``."""
    if session.purpose is not Purpose.REGISTER:
        raise ValueError("only registration calls ask for consent")
    answers = session.answers
    return {
        "adult": answers.adult,
        "consent": answers.consent,
        "consent_digits": answers.consent_digits,
        "access": answers.access,
        "language": session.language or "hi",
    }


def stop_requested(session: FlowSession) -> bool:
    """True when the caller confirmed (with 9, twice) that all calls should stop."""
    return session.answers.stop is True


_REPORT_ANSWERS: dict[ReportChoice | None, tuple[WaterAnswer | None, CleanAnswer | None]] = {
    ReportChoice.NO_WATER: (WaterAnswer.NO, None),
    ReportChoice.DIRTY: (WaterAnswer.YES, CleanAnswer.NO),
}


# --- engine internals -----------------------------------------------------------------------------


def _special_input(
    session: FlowSession, key: str | None, cat: PromptCatalog
) -> tuple[FlowSession, list[Action], bool] | None:
    """Keys with their own path: stop (9), hear the notice again, status, repeat a message."""
    where = (session.purpose, session.step)
    if session.step is FlowStep.Q_LANG:
        return _language_input(session, key)
    if key == STOP_KEY and session.purpose is Purpose.REGISTER:
        # The notice promises "press 9 in any call to stop": on the consent call that is a no.
        answers = session.answers.model_copy(
            update={"consent": ConsentAnswer.DECLINED, "consent_digits": STOP_KEY}
        )
        done = _moved(session.model_copy(update={"answers": answers}), FlowStep.DONE)
        return done, _step_actions(done, cat), True
    if key == STOP_KEY and where in _STOPPABLE:
        moved = _moved(session, FlowStep.Q_STOP)
        return moved, _step_actions(moved, cat), False
    if session.step is FlowStep.Q_STOP:
        stop = _STOP.get(key or "", False)
        answers = session.answers.model_copy(update={"stop": stop})
        done = _moved(session.model_copy(update={"answers": answers}), FlowStep.DONE)
        return done, _step_actions(done, cat), True
    if session.step is FlowStep.Q_CONSENT:
        return _consent_input(session, key, cat)
    if where == (Purpose.REPORT, FlowStep.Q_MENU) and key == "4":
        return _status_input(session, cat)
    if session.step is FlowStep.Q_HEARD and key == "2":
        if session.replays >= MAX_MESSAGE_REPLAYS:
            answers = session.answers.model_copy(update={"heard": True})
            done = _moved(session.model_copy(update={"answers": answers}), FlowStep.DONE)
            return done, _step_actions(done, cat), True
        again = session.model_copy(
            update={"replays": session.replays + 1, "retries": 0, "turn": session.turn + 1}
        )
        return again, [_message(again), *_question_actions(again, cat)], False
    return None


def _language_input(
    session: FlowSession, key: str | None
) -> tuple[FlowSession, list[Action], bool]:
    """The family picked a call language (or, after two misses, keeps the village default)."""
    offered = session.offered_languages
    index = int(key) - 1 if key and key.isdigit() else -1
    if not 0 <= index < len(offered) and session.retries < MAX_RETRIES:
        again = session.model_copy(
            update={"retries": session.retries + 1, "turn": session.turn + 1}
        )
        cat = catalog_for(session.language)
        return again, [_play(cat, INVALID_PROMPT), *_question_actions(again, cat)], False
    language = offered[index] if 0 <= index < len(offered) else session.language
    chosen = _moved(session.model_copy(update={"language": language}), FlowStep.Q_AGE)
    cat = catalog_for(language)
    return chosen, [_play(cat, "register.notice"), *_question_actions(chosen, cat)], False


def _consent_input(
    session: FlowSession, key: str | None, cat: PromptCatalog
) -> tuple[FlowSession, list[Action], bool]:
    if key == "1":
        return _advance(session, "consent", ConsentAnswer.GRANTED, cat, key)
    if key == "3":
        return _advance(session, "consent", ConsentAnswer.DECLINED, cat, key)
    if key == "2" and session.notice_plays < MAX_NOTICE_PLAYS:
        again = session.model_copy(
            update={
                "notice_plays": session.notice_plays + 1,
                "retries": 0,
                "turn": session.turn + 1,
            }
        )
        return again, [_play(cat, "register.notice"), *_question_actions(again, cat)], False
    if key != "2" and session.retries < MAX_RETRIES:
        again = session.model_copy(
            update={"retries": session.retries + 1, "turn": session.turn + 1}
        )
        return again, [_play(cat, INVALID_PROMPT), *_question_actions(again, cat)], False
    return _advance(session, "consent", None, cat, key)


def _status_input(
    session: FlowSession, cat: PromptCatalog
) -> tuple[FlowSession, list[Action], bool]:
    loops = session.menu_loops + 1
    status = Play(
        prompt_key="dyn.report_status",
        text_hi=session.message_text_hi or cat.text("report.status_unknown"),
    )
    if loops >= MAX_MENU_LOOPS:
        done = _moved(session.model_copy(update={"menu_loops": loops}), FlowStep.DONE)
        return done, [status, *_step_actions(done, cat)], True
    again = session.model_copy(update={"menu_loops": loops, "retries": 0, "turn": session.turn + 1})
    return again, [status, *_question_actions(again, cat)], False


def _advance(
    session: FlowSession,
    field: str,
    value: object,
    cat: PromptCatalog,
    key: str | None,
) -> tuple[FlowSession, list[Action], bool]:
    update: dict[str, object] = {field: value}
    if field == "fixed" and value is False and key in _BLOCKERS:
        update["blocker"] = _BLOCKERS[key]
    if field == "consent" and key is not None:
        update["consent_digits"] = key
    answers = session.answers.model_copy(update=update)
    answered = session.model_copy(update={"answers": answers})
    moved = _moved(answered, _next_step(answered))
    return moved, _step_actions(moved, cat), moved.done


def _moved(session: FlowSession, step: FlowStep) -> FlowSession:
    return session.model_copy(update={"step": step, "retries": 0, "turn": session.turn + 1})


def _finish_note(
    session: FlowSession, recording_url: str | None, cat: PromptCatalog
) -> tuple[FlowSession, list[Action], bool]:
    noted = with_recording(session, recording_url) if recording_url else session
    done = _moved(noted, FlowStep.DONE)
    return done, _step_actions(done, cat), True


def _next_step(session: FlowSession) -> FlowStep:
    answers = session.answers
    match (session.purpose, session.step):
        case (Purpose.DAILY, FlowStep.Q_WATER):
            if answers.water in _WATER_CAME:
                piped = session.access in _PIPED_OR_UNKNOWN
                return FlowStep.Q_HOURS if piped else FlowStep.Q_CLEAN
            if answers.water is WaterAnswer.NO:
                return FlowStep.Q_FALLBACK
            return FlowStep.Q_NOTE
        case (Purpose.DAILY, FlowStep.Q_HOURS):
            return FlowStep.Q_CLEAN
        case (Purpose.DAILY, FlowStep.Q_CLEAN | FlowStep.Q_FALLBACK):
            return FlowStep.Q_NOTE
        case (Purpose.REGISTER, FlowStep.Q_AGE):
            return FlowStep.Q_CONSENT if answers.adult is True else FlowStep.DONE
        case (Purpose.REGISTER, FlowStep.Q_CONSENT):
            granted = answers.consent is ConsentAnswer.GRANTED
            return FlowStep.Q_ACCESS if granted else FlowStep.DONE
        case (Purpose.REGISTER, FlowStep.Q_ACCESS):
            return FlowStep.Q_NOTE
        case (Purpose.REPORT, FlowStep.Q_MENU):
            return FlowStep.Q_NOTE if answers.report is ReportChoice.NOTE else FlowStep.DONE
        case (Purpose.OPERATOR, FlowStep.Q_FIXED):
            return FlowStep.Q_NOTE if answers.blocker in _SPOKEN_BLOCKERS else FlowStep.DONE
        case _:
            return FlowStep.DONE


def _language_menu(session: FlowSession, cat: PromptCatalog) -> Play:
    """ "Chhattisgarhi ke liye 1, Hindi ke liye 2 …" in the village language (runtime voice)."""
    parts = [
        cat.text("register.language_option", name=_language_name(cat, code), n=index + 1)
        for index, code in enumerate(session.offered_languages)
    ]
    return Play(prompt_key="dyn.language_menu", text_hi=" ".join(parts))


def _language_name(cat: PromptCatalog, code: str) -> str:
    try:
        return cat.text(f"lang.{code}")
    except KeyError:
        return code


def _question(session: FlowSession) -> _Question:
    if session.step is FlowStep.Q_STOP:
        return _STOP_QUESTION
    if session.step is FlowStep.Q_CONSENT:
        return _Question("register.q_consent", "consent", {})
    if (session.purpose, session.step) == (Purpose.DAILY, FlowStep.Q_WATER):
        return _Question(_WATER_PROMPTS[session.access], "water", _WATER_DAILY)
    return _FIXED_QUESTIONS[(session.purpose, session.step)]


def _step_actions(session: FlowSession, cat: PromptCatalog) -> list[Action]:
    if session.step is FlowStep.Q_NOTE:
        if session.purpose is Purpose.REGISTER:
            return [_play(cat, "register.q_intro"), Record(max_s=INTRO_MAX_S)]
        if session.purpose is Purpose.REPORT:
            return [_play(cat, "report.q_note"), Record(max_s=REPORT_NOTE_MAX_S)]
        if session.purpose is Purpose.OPERATOR:
            return [_play(cat, "operator.q_note"), Record(max_s=OPERATOR_NOTE_MAX_S)]
        return [_play(cat, NOTE_PROMPT), Record(max_s=NOTE_MAX_S)]
    if session.step is FlowStep.DONE:
        return [_play(cat, _closing_prompt(session)), Hangup()]
    return _question_actions(session, cat)


def _question_actions(session: FlowSession, cat: PromptCatalog) -> list[Action]:
    if session.step is FlowStep.Q_LANG:
        return [
            GetDigits(
                num_digits=1, timeout_s=QUESTION_TIMEOUT_S, prompts=[_language_menu(session, cat)]
            )
        ]
    prompt = _play(cat, _question(session).prompt_key)
    return [GetDigits(num_digits=1, timeout_s=QUESTION_TIMEOUT_S, prompts=[prompt])]


def _intro(session: FlowSession, cat: PromptCatalog) -> list[Action]:
    match session.purpose:
        case Purpose.OPERATOR:
            return _operator_intro(session, cat)
        case Purpose.REGISTER:
            if session.step is FlowStep.Q_LANG:
                return [_play(cat, "register.greet")]
            return [_play(cat, "register.greet"), _play(cat, "register.notice")]
        case Purpose.BROADCAST | Purpose.SUMMARY | Purpose.ALERT:
            return [_play(cat, _INTRO[session.purpose]), _message(session)]
        case _:
            return [_play(cat, _INTRO[session.purpose])]


def _operator_intro(session: FlowSession, cat: PromptCatalog) -> list[Action]:
    if session.ticket_reason is None or session.reported_households is None:
        raise ValueError("an OPERATOR call needs ticket_reason and reported_households")
    summary_key = _SUMMARY_PROMPT[session.ticket_reason]
    actions: list[Action] = [
        _play(cat, "operator.greet"),
        _play(cat, summary_key, households=session.reported_households),
    ]
    if session.ticket_number is not None and session.water_point_name:
        actions.append(
            _play(
                cat,
                "operator.where",
                number=session.ticket_number,
                place=session.water_point_name,
            )
        )
    elif session.ticket_number is not None:
        actions.append(_play(cat, "operator.number", number=session.ticket_number))
    return actions


def _message(session: FlowSession) -> Play:
    """The announcement or summary itself (rendered by runtime TTS)."""
    key = {Purpose.BROADCAST: "dyn.broadcast", Purpose.ALERT: "dyn.alert"}.get(
        session.purpose, "dyn.summary"
    )
    return Play(prompt_key=key, text_hi=session.message_text_hi or "")


_CLOSINGS: dict[Purpose, Callable[[FlowAnswers], str]] = {
    Purpose.DAILY: lambda a: "household.bye",
    Purpose.VERIFY: lambda a: "verify.bye",
    Purpose.OPERATOR: lambda a: (
        "operator.ack_fixed"
        if a.fixed is True
        else "operator.ack_not_mine"
        if a.blocker is BlockerCode.NOT_MINE
        else "operator.ack_panchayat"
        if a.blocker is BlockerCode.NEEDS_PANCHAYAT
        else "operator.ack_note"
        if a.blocker is BlockerCode.OTHER
        else "operator.ack_reason"
        if a.blocker is not None
        else "operator.ack_pending"
    ),
    Purpose.REGISTER: lambda a: (
        "register.minor"
        if a.adult is False
        else "register.declined"
        if a.consent is ConsentAnswer.DECLINED
        else "register.done"
        if a.consent is ConsentAnswer.GRANTED
        else "register.no_answer"
    ),
    Purpose.REPORT: lambda a: (
        "report.note_ack"
        if a.report is ReportChoice.NOTE
        else "report.ack"
        if a.report is not None
        else "report.bye"
    ),
    Purpose.BROADCAST: lambda a: "broadcast.bye",
    Purpose.SUMMARY: lambda a: "broadcast.bye",
    Purpose.ALERT: lambda a: "alert.bye",
}


def _closing_prompt(session: FlowSession) -> str:
    if session.answers.stop is True:
        return "stop.done"
    if session.answers.stop is False:
        return "stop.cancelled"
    return _CLOSINGS[session.purpose](session.answers)


def _play(cat: PromptCatalog, key: str, **variables: object) -> Play:
    clip = cat.audio_key(key, **variables)
    return Play(prompt_key=clip or key, text_hi=cat.text(key, **variables))


def _normalise(digits: str | None) -> str | None:
    if digits is None:
        return None
    cleaned = digits.strip()
    return cleaned or None
