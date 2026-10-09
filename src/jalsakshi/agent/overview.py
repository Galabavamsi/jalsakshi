"""AI overview of one complaint and a suggested next step (ARCHITECTURE.md §15.14).

Suggestions only. The secretary reads them and presses a button; the ticket state machine and
Cedar still guard every change, and nothing here is ever applied on its own. Two parts:

- the next step: Jev (TypeSafe's decision model: one typed choice with probabilities) when a key
  is configured, otherwise the fixed rules below (``suggest_rules``), which are also the fallback;
- the overview: two or three plain English sentences from Bedrock (the agent model chain), and a
  template when every model fails.

Only de-identified facts are used: the problem, how long, counts, the operator's reason codes and
the English gist of the operator's own words (the gist stays on AWS: Bedrock only). Jev, which is
outside AWS, gets the codes and counts only. Never names, phone numbers or families' words.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

import httpx
from pydantic import BaseModel, Field

from jalsakshi.agent.reader import ReaderError, converse_text
from jalsakshi.core.models import BlockerCode, Ticket, TicketReason, TicketState

logger = logging.getLogger(__name__)

JEV_URL: Final = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL: Final = "jev-1.13.0"  # pinned: an alias could change answers under us
OPENAI_URL: Final = "https://api.openai.com/v1/decisions"
OPENAI_MODEL: Final = "gpt-6-luna"
# One attempt each: the next model in the chain is the retry. Jev + OpenAI + two Bedrock reads
# (8 s each) stay inside the 30 s API Lambda.
DECISION_TIMEOUT_S: Final = 4.0
OVERVIEW_READ_TIMEOUT_S: Final = 8
MIN_CONFIDENCE: Final = 0.4
NEXT_STEP_QUESTION: Final = (
    "This is a drinking-water complaint in an Indian village, tracked by the Gram Panchayat. "
    "What should the Panchayat secretary do next?"
)
URGENT_TRUE: Final = "Families are without safe drinking water now, or it is a health risk"
URGENT_FALSE: Final = "Families still have safe water, or it is minor"
RULES: Final = "rules"
TEMPLATE: Final = "template"
_DIGITS: Final = re.compile(r"\d{4,}")


class NextStep(StrEnum):
    CALL_OPERATOR_AGAIN = "CALL_OPERATOR_AGAIN"
    SEND_TO_SARPANCH = "SEND_TO_SARPANCH"
    RAISE_WITH_BLOCK_OFFICE = "RAISE_WITH_BLOCK_OFFICE"
    WAIT_FOR_REPAIR = "WAIT_FOR_REPAIR"


STEP_TEXT: Final[dict[NextStep, str]] = {
    NextStep.CALL_OPERATOR_AGAIN: "Call the pump operator again",
    NextStep.SEND_TO_SARPANCH: "Send it to the Sarpanch",
    NextStep.RAISE_WITH_BLOCK_OFFICE: "Raise it with the PHED block office",
    NextStep.WAIT_FOR_REPAIR: "Wait: the repair is in progress",
}

# What each option means, for Jev (the rubric) and for people reading the code.
STEP_RUBRIC: Final[dict[NextStep, str]] = {
    NextStep.CALL_OPERATOR_AGAIN: (
        "The pump operator has not been reached recently, gave no reason, or said it was fixed "
        "while families still report the problem."
    ),
    NextStep.SEND_TO_SARPANCH: (
        "The operator cannot solve it alone (money, parts, electricity bill, approval, a "
        "dispute, or work beyond one person), or it has stayed unsolved for days."
    ),
    NextStep.RAISE_WITH_BLOCK_OFFICE: (
        "The Sarpanch already has it and it is still unsolved, or it is a scheme-level failure "
        "(motor or borewell replacement, main pipeline, water quality) that needs the PHED."
    ),
    NextStep.WAIT_FOR_REPAIR: (
        "The operator is working on it recently and nothing suggests it is stuck."
    ),
}

PROBLEM_EN: Final[dict[TicketReason, str]] = {
    TicketReason.NO_SUPPLY: "no water",
    TicketReason.DIRTY: "dirty water",
    TicketReason.LOW_PRESSURE: "very little water",
    TicketReason.LEAK: "a leaking pipe",
    TicketReason.BROKEN: "a broken pump or handpump",
    TicketReason.OTHER: "another water problem",
}

BLOCKER_EN: Final[dict[BlockerCode, str]] = {
    BlockerCode.PARTS_NEEDED: "parts needed",
    BlockerCode.NO_POWER: "no electricity",
    BlockerCode.PIPE_BROKEN: "pipe broken",
    BlockerCode.NOT_MINE: "not their source",
    BlockerCode.OTHER: "another reason (spoken)",
    BlockerCode.NEEDS_PANCHAYAT: "cannot fix it alone, needs the Panchayat",
}

STATE_EN: Final[dict[TicketState, str]] = {
    TicketState.OPEN: "new",
    TicketState.ASSIGNED: "pump operator told",
    TicketState.OPERATOR_REPORTED_FIXED: "operator says fixed, families not asked yet",
    TicketState.VERIFYING: "asking families if water is back",
    TicketState.CLOSED_VERIFIED: "closed, families confirmed",
    TicketState.REOPENED: "families say it is still not fixed",
    TicketState.ESCALATED: "escalated",
}


class ComplaintFacts(BaseModel):
    """What the AI may see about a complaint: no names, phone numbers or families' words."""

    number: int | None = None
    problem: str
    status: str
    hours_open: int = Field(ge=0)
    families_reporting: int = Field(ge=1)
    operator_called: int = Field(ge=0)
    hours_since_operator_contact: int | None = None
    operator_reasons: list[str] = Field(default_factory=list)
    operator_said: str | None = None
    operator_said_fixed: bool = False
    families_said_still_broken: int = Field(default=0, ge=0)
    sent_to_sarpanch: bool = False
    sarpanch_heard: bool = False
    closed: bool = False


class Suggestion(BaseModel):
    step: NextStep
    label: str
    source: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    probabilities: dict[str, float] = Field(default_factory=dict)
    urgent: float | None = Field(default=None, ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class Overview(BaseModel):
    text: str
    text_source: str
    suggestion: Suggestion | None
    facts: ComplaintFacts
    generated_at: datetime


def facts_for(ticket: Ticket, now: datetime) -> ComplaintFacts:
    """De-identified facts from a complaint's own record (deterministic)."""
    notified = [e for e in ticket.events if e.kind == "NOTIFIED"]
    operator_events = [
        e
        for e in ticket.events
        if e.actor.startswith("operator:") or e.kind in ("NOTIFIED", "OPERATOR_FIXED")
    ]
    reasons = [
        BLOCKER_EN.get(BlockerCode(e.detail["code"]), str(e.detail["code"]))
        for e in ticket.events
        if e.detail.get("note") == "operator_reason" and e.detail.get("code") in BlockerCode
    ]
    said = next(
        (
            str(e.detail.get("summary_en") or "")
            for e in reversed(ticket.events)
            if e.detail.get("note") == "operator_voice" and e.detail.get("summary_en")
        ),
        None,
    )
    last_contact = max((e.at for e in operator_events), default=None)
    return ComplaintFacts(
        number=ticket.number,
        problem=PROBLEM_EN[ticket.reason],
        status=STATE_EN[ticket.state],
        hours_open=max(0, int((now - ticket.opened_at).total_seconds() // 3600)),
        families_reporting=max(1, len(ticket.reporters)),
        operator_called=len(notified),
        hours_since_operator_contact=(
            int((now - last_contact).total_seconds() // 3600) if last_contact else None
        ),
        operator_reasons=reasons[-5:],
        operator_said=_scrub(said)[:300] if said else None,
        operator_said_fixed=any(e.kind == "OPERATOR_FIXED" for e in ticket.events),
        families_said_still_broken=sum(1 for e in ticket.events if e.kind == "VERIFY_FAILED"),
        sent_to_sarpanch=any(
            e.detail.get("to") == "SARPANCH"
            and (e.kind == "ESCALATED" or e.detail.get("note") == "sent_to_sarpanch")
            for e in ticket.events
        ),
        sarpanch_heard=any(e.detail.get("note") == "sarpanch_told" for e in ticket.events),
        closed=ticket.state is TicketState.CLOSED_VERIFIED,
    )


def suggest_rules(facts: ComplaintFacts) -> Suggestion:
    """The fixed rules: the fallback, and what Jev's answer can be compared with."""
    last = facts.operator_reasons[-1] if facts.operator_reasons else None
    stuck_reasons = {BLOCKER_EN[BlockerCode.PARTS_NEEDED], BLOCKER_EN[BlockerCode.NO_POWER]}
    if facts.sent_to_sarpanch and facts.hours_open >= 72:
        return _rule(NextStep.RAISE_WITH_BLOCK_OFFICE, "With the Sarpanch and open over 3 days")
    if last == BLOCKER_EN[BlockerCode.NEEDS_PANCHAYAT] and not facts.sent_to_sarpanch:
        return _rule(NextStep.SEND_TO_SARPANCH, "The operator says they cannot fix it alone")
    if facts.operator_said_fixed and facts.families_said_still_broken:
        return _rule(NextStep.CALL_OPERATOR_AGAIN, "Families say it is still not fixed")
    if last in stuck_reasons and facts.hours_open >= 48 and not facts.sent_to_sarpanch:
        return _rule(NextStep.SEND_TO_SARPANCH, f"Waiting on {last} for 2 days or more")
    if facts.operator_called == 0 or (facts.hours_since_operator_contact or 0) >= 24:
        return _rule(NextStep.CALL_OPERATOR_AGAIN, "No word from the operator for a day")
    if facts.hours_open >= 72 and not facts.sent_to_sarpanch:
        return _rule(NextStep.SEND_TO_SARPANCH, "Open for more than 3 days")
    return _rule(NextStep.WAIT_FOR_REPAIR, "The operator was reached recently")


def suggest(
    facts: ComplaintFacts,
    *,
    jev_key: str | None,
    openai_key: str | None = None,
    http: httpx.Client | None = None,
) -> Suggestion:
    """The first sure answer of Jev, then OpenAI Decisions, then the fixed rules.

    A model that fails or is less than ``MIN_CONFIDENCE`` sure is skipped, and the suggestion
    that is shown says so in its ``reasons``.
    """
    skipped: list[str] = []
    if http is not None:
        chain = (("Jev", jev_key, suggest_jev), ("OpenAI", openai_key, suggest_openai))
        for name, key, ask in chain:
            if not key:
                continue
            found = ask(facts, api_key=key, http=http)
            if found is None:
                skipped.append(f"the {name} decision model did not answer")
            elif (found.confidence or 0) < MIN_CONFIDENCE:
                pct = round((found.confidence or 0) * 100)
                skipped.append(f"the {name} decision model was unsure ({pct}%)")
            else:
                return found.model_copy(update={"reasons": [*found.reasons, *skipped]})
    ruled = suggest_rules(facts)
    return ruled.model_copy(update={"reasons": [*ruled.reasons, *skipped]})


def suggest_jev(facts: ComplaintFacts, *, api_key: str, http: httpx.Client) -> Suggestion | None:
    """Ask Jev for the next step (a typed choice) and how urgent it is; None on any failure."""
    body = {
        "model": JEV_MODEL,
        "state": facts.model_dump(mode="json", exclude={"operator_said"}),
        "questions": {
            "next_step": {
                "type": "choice",
                "instructions": NEXT_STEP_QUESTION,
                "criteria": {step.value: STEP_RUBRIC[step] for step in NextStep},
            },
            "urgent": {
                "type": "noul",
                "instructions": "Is this urgent for the families?",
                "criteria": {"true": URGENT_TRUE, "false": URGENT_FALSE},
            },
        },
    }
    data = _post_json(JEV_URL, body, api_key, http, "jev")
    return _parse_jev(data) if data is not None else None


def suggest_openai(facts: ComplaintFacts, *, api_key: str, http: httpx.Client) -> Suggestion | None:
    """The same question to OpenAI's Decisions API (``gpt-6-luna``); None on any failure."""
    body = {
        "model": OPENAI_MODEL,
        "input": json.dumps(facts.model_dump(mode="json", exclude={"operator_said"})),
        "questions": [
            {
                "type": "choice",
                "name": "next_step",
                "instructions": NEXT_STEP_QUESTION,
                "choices": [
                    {"value": step.value, "description": STEP_RUBRIC[step]} for step in NextStep
                ],
            },
            {
                "type": "predicate",
                "name": "urgent",
                "instructions": f"Is this urgent for the families? Yes: {URGENT_TRUE}. "
                f"No: {URGENT_FALSE}.",
            },
        ],
    }
    data = _post_json(OPENAI_URL, body, api_key, http, "openai")
    return _parse_openai(data) if data is not None else None


def _post_json(url: str, body: dict[str, Any], key: str, http: httpx.Client, name: str) -> Any:
    """One POST with a bearer key; the JSON body, or None (the key is never logged)."""
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        response = http.post(url, json=body, headers=headers, timeout=DECISION_TIMEOUT_S)
    except httpx.HTTPError as exc:
        logger.warning("decision request failed", extra={"api": name, "error": type(exc).__name__})
        return None
    if response.status_code != 200:
        logger.warning("decision refused", extra={"api": name, "status": response.status_code})
        return None
    try:
        return response.json()
    except ValueError:
        logger.warning("decision answer not JSON", extra={"api": name})
        return None


def write_overview(facts: ComplaintFacts, suggestion: Suggestion | None) -> tuple[str, str]:
    """Two or three plain sentences for the secretary, and who wrote them (a model or template)."""
    prompt = (
        "You help a Gram Panchayat secretary in India. Using ONLY these facts about one "
        "drinking-water complaint, write 2 or 3 short, plain English sentences: what is wrong, "
        "how long it has been open, and what the pump operator and the families have said. "
        "Do not invent anything. Do not decide anything. Call people by their role (the pump "
        "operator, the families) and never guess anyone's gender. Plain text only, no lists.\n"
        f"<facts>{json.dumps(facts.model_dump(mode='json'))}</facts>"
    )
    try:
        text, model_id = converse_text(
            prompt, max_tokens=220, read_timeout_s=OVERVIEW_READ_TIMEOUT_S
        )
    except ReaderError:
        return template_overview(facts), TEMPLATE
    cleaned = " ".join(text.split())[:600]
    return (cleaned or template_overview(facts)), (model_id if cleaned else TEMPLATE)


def template_overview(facts: ComplaintFacts) -> str:
    """The overview without a model: the same facts as fixed sentences."""
    number = f"Complaint #{facts.number}" if facts.number else "This complaint"
    families = (
        "1 family" if facts.families_reporting == 1 else f"{facts.families_reporting} families"
    )
    days = facts.hours_open // 24
    age = f"{days} day{'s' if days != 1 else ''}" if days else f"{facts.hours_open} hours"
    parts = [f"{number}: {families} reported {facts.problem}, open for {age} ({facts.status})."]
    if facts.operator_reasons:
        parts.append(f"The pump operator said: {facts.operator_reasons[-1]}.")
    if facts.operator_said:
        parts.append(f"In their words: {facts.operator_said}")
    if facts.families_said_still_broken:
        parts.append("Families said it is still not fixed after a repair.")
    return " ".join(parts)


def _parse_jev(data: Any) -> Suggestion | None:
    try:
        answers = data["answers"]
        choice = answers["next_step"]
        step = NextStep(choice["choice"])
        probabilities = {str(k): round(float(v), 3) for k, v in choice["probabilities"].items()}
        urgent = answers.get("urgent", {}).get("noul")
        return Suggestion(
            step=step,
            label=STEP_TEXT[step],
            source=str(data.get("model") or JEV_MODEL),
            confidence=round(float(choice["confidence"]), 3),
            probabilities=probabilities,
            urgent=round(float(urgent), 3) if urgent is not None else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("jev answer unusable", extra={"error": type(exc).__name__})
        return None


def _parse_openai(data: Any) -> Suggestion | None:
    try:
        answers = {a["name"]: a for a in data["answers"] if isinstance(a, dict) and "name" in a}
        choice = answers["next_step"]
        if choice.get("type") != "choice":  # e.g. a refusal
            return None
        step = NextStep(choice["choice"])
        probabilities = {
            str(p["value"]): round(float(p["probability"]), 3) for p in choice["probabilities"]
        }
        urgent = answers.get("urgent", {})
        probability = urgent.get("probability") if urgent.get("type") == "predicate" else None
        return Suggestion(
            step=step,
            label=STEP_TEXT[step],
            source=str(data.get("model") or OPENAI_MODEL),
            confidence=round(float(choice["confidence"]), 3),
            probabilities=probabilities,
            urgent=round(float(probability), 3) if probability is not None else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("openai answer unusable", extra={"error": type(exc).__name__})
        return None


def _rule(step: NextStep, reason: str) -> Suggestion:
    return Suggestion(step=step, label=STEP_TEXT[step], source=RULES, reasons=[reason])


def _scrub(text: str) -> str:
    """Drop long digit runs (phone numbers) from text that leaves the system."""
    return _DIGITS.sub("…", " ".join(text.split()))
