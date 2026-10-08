"""Gram Sabha evidence brief (docs/ARCHITECTURE.md section 10).

A Strands agent reads two tools that return only the computed numbers, then writes a short Hindi
sheet. Its text is accepted only if every number in it equals a tool value; otherwise the next
model is tried and, finally, the deterministic template is used. Source and freshness labels are
always added by code, never by the model.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, Self

from jalsakshi.agent import models as agent_models
from jalsakshi.agent.evidence import (
    Brief,
    BriefInput,
    BriefSummary,
    allowed_numbers,
    identifiers,
    ticket_facts,
)
from jalsakshi.agent.numbers import invented_numbers, validate_numbers
from jalsakshi.agent.prompts import BRIEF_SYSTEM_PROMPT, brief_user_prompt
from jalsakshi.agent.template import (
    FRESHNESS_HI,
    REASON_HI,
    STATE_HI,
    template_markdown,
    wrap_agent_markdown,
)

if TYPE_CHECKING:
    from strands import Agent
    from strands.agent.agent_result import AgentResult
    from strands.models.model import Model

__all__ = [
    "Brief",
    "BriefInput",
    "BriefRejected",
    "BriefSummary",
    "generate_brief",
    "template_brief",
    "tickets_payload",
    "validate_numbers",
    "village_summary_payload",
]

logger = logging.getLogger(__name__)

BRIEF_MAX_TOKENS: Final = 3000
BRIEF_MAX_TURNS: Final = 6
DEFAULT_DEADLINE_S: Final = 24.0  # API Gateway cuts sync requests at 29 s
MAX_BRIEF_CHARS: Final = 8000
SUMMARY_TOOL: Final = "village_summary"
TICKETS_TOOL: Final = "tickets"

_FENCE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^\s*#")
_SOURCES_HEADING = re.compile(r"^\s*#{1,6}\s*स्रोत\s*$")


class BriefRejected(ValueError):
    """The agent's text failed a check, so the next model or the template is used."""


def generate_brief(
    inp: BriefInput,
    use_agent: bool = True,
    *,
    model_factory: agent_models.ModelFactory | None = None,
    now: datetime | None = None,
    deadline_s: float | None = DEFAULT_DEADLINE_S,
) -> Brief:
    """Write the brief with the agent when allowed, valid and on time, else with the template.

    ``deadline_s`` bounds the whole model chain (None disables it); past it, the in-flight call
    is cancelled and the template is returned.
    """
    generated_at = now or datetime.now(UTC)
    if not use_agent:
        return template_brief(inp, now=generated_at)
    try:
        with _Deadline(deadline_s) as deadline:
            body, model_id = _agent_body(inp, model_factory, deadline)
    except agent_models.AllModelsFailed as exc:
        logger.warning(
            "brief agent failed on every model; using template",
            extra={
                "village_id": inp.village.id,
                "errors": [f"{type(e).__name__}: {str(e)[:200]}" for _, e in exc.errors],
            },
        )
        return template_brief(inp, now=generated_at)
    except Exception:
        logger.exception(
            "brief agent crashed; using template", extra={"village_id": inp.village.id}
        )
        return template_brief(inp, now=generated_at)
    return Brief(
        markdown_hi=wrap_agent_markdown(inp, body),
        numbers=inp.summary.numbers(),
        generated_by="agent",
        sources=inp.all_sources(),
        generated_at=generated_at,
        model_id=model_id,
    )


def template_brief(inp: BriefInput, *, now: datetime | None = None) -> Brief:
    """Deterministic Hindi brief; always passes ``validate_numbers``."""
    return Brief(
        markdown_hi=template_markdown(inp),
        numbers=inp.summary.numbers(),
        generated_by="template",
        sources=inp.all_sources(),
        generated_at=now or datetime.now(UTC),
    )


def village_summary_payload(inp: BriefInput) -> dict[str, Any]:
    """What the ``village_summary`` tool returns: context plus the computed numbers only."""
    village, numbers = inp.village, inp.summary.numbers()
    claimed = village.claimed_source
    return {
        "village": {
            "id": village.id,
            "name": village.name,
            "block": village.block,
            "district": village.district,
        },
        "period": {"from": inp.period_from.isoformat(), "to": inp.period_to.isoformat()},
        "state_claim": {
            "claimed_hgj": village.claimed_hgj,
            "hgj_certified": village.hgj_certified,
            "source": claimed.source if claimed else None,
        },
        "observed_days": {
            key: numbers[key]
            for key in ("days", "supplied", "partial", "no_supply", "dirty", "unverified")
        },
        "supplied_pct": numbers["supplied_pct"],
        "tickets": {
            "opened": numbers["tickets_opened"],
            "closed_verified": numbers["tickets_closed_verified"],
            "median_hours_to_verified_fix": numbers["median_hours_to_verified_fix"],
        },
        "sources": [
            {
                "source": s.source,
                "freshness": s.freshness.value,
                "freshness_hi": FRESHNESS_HI[s.freshness],
            }
            for s in inp.all_sources()
        ],
        "glossary": {
            "supplied_pct": "percent of observed days with full supply",
            "unverified": "days with too few household answers to decide",
        },
    }


def tickets_payload(inp: BriefInput) -> dict[str, Any]:
    """What the ``tickets`` tool returns: each ticket's citeable facts."""
    facts = ticket_facts(inp.tickets)
    return {
        "count": len(facts),
        "tickets": [
            {
                "id": f.id,
                "reason": f.reason.value,
                "reason_hi": REASON_HI[f.reason],
                "state": f.state.value,
                "state_hi": STATE_HI[f.state],
                "opened_on": f.opened_on.isoformat(),
                "closed_verified_on": (
                    f.closed_verified_on.isoformat() if f.closed_verified_on else None
                ),
                "hours_to_verified_fix": f.hours_to_verified_fix,
            }
            for f in facts
        ],
    }


def clean_agent_markdown(text: str) -> str:
    """Drop code fences, any preface before the first heading, and any model-written sources."""
    lines = [line for line in text.strip().splitlines() if not _FENCE.match(line)]
    start = next((i for i, line in enumerate(lines) if _HEADING.match(line)), None)
    if start is None:
        return ""
    body = lines[start:]
    end = next((i for i, line in enumerate(body) if _SOURCES_HEADING.match(line)), len(body))
    return "\n".join(body[:end]).strip()


@dataclass
class _BriefSession:
    """An agent plus a log of which tools it called."""

    agent: Agent
    called: set[str]


class _Deadline:
    """Wall-clock budget for the whole chain; ``signal`` cancels an in-flight agent call."""

    def __init__(self, seconds: float | None) -> None:
        self.signal = threading.Event()
        self._at = None if seconds is None else time.monotonic() + seconds
        self._timer = None if seconds is None else threading.Timer(seconds, self.signal.set)

    def __enter__(self) -> Self:
        if self._timer is not None:
            self._timer.daemon = True
            self._timer.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def expired(self) -> bool:
        """True once the budget is spent."""
        return self.signal.is_set() or (self._at is not None and time.monotonic() >= self._at)


def _agent_body(
    inp: BriefInput, model_factory: agent_models.ModelFactory | None, deadline: _Deadline
) -> tuple[str, str]:
    factory = model_factory or partial(agent_models.make_model, max_tokens=BRIEF_MAX_TOKENS)
    return agent_models.run_with_fallback(
        partial(_build_session, inp=inp),
        partial(_write_body, inp=inp, deadline=deadline),
        model_factory=factory,
    )


def _build_session(model: Model, *, inp: BriefInput) -> _BriefSession:
    called: set[str] = set()
    agent = agent_models.new_agent(
        model,
        name="jalsakshi-brief",
        system_prompt=BRIEF_SYSTEM_PROMPT,
        tools=_brief_tools(inp, called),
    )
    return _BriefSession(agent=agent, called=called)


def _brief_tools(inp: BriefInput, called: set[str]) -> list[Any]:
    """The two read-only tools, bound to this input so the model cannot ask for anything else."""
    from strands import tool

    @tool(name=SUMMARY_TOOL)
    def village_summary() -> dict[str, Any]:
        """Village, period, the state's Har Ghar Jal claim and the computed day and ticket
        counts. These are the only numbers you may cite."""
        called.add(SUMMARY_TOOL)
        return village_summary_payload(inp)

    @tool(name=TICKETS_TOOL)
    def tickets() -> dict[str, Any]:
        """Repair tickets with ids, reason, state, dates and hours to household-verified fix."""
        called.add(TICKETS_TOOL)
        return tickets_payload(inp)

    return [village_summary, tickets]


def _write_body(session: _BriefSession, *, inp: BriefInput, deadline: _Deadline) -> str:
    if deadline.expired():
        raise BriefRejected("deadline passed before this model was tried")
    prompt = brief_user_prompt(
        inp.village.name, inp.period_from.isoformat(), inp.period_to.isoformat()
    )
    result = session.agent(prompt, limits={"turns": BRIEF_MAX_TURNS}, cancel_signal=deadline.signal)
    if result.stop_reason != "end_turn":
        raise BriefRejected(f"agent stopped with {result.stop_reason}")
    if SUMMARY_TOOL not in session.called:
        raise BriefRejected("agent wrote without reading village_summary")
    body = clean_agent_markdown(_result_text(result))
    _check_body(body, inp)
    return body


def _check_body(body: str, inp: BriefInput) -> None:
    if not body or len(body) > MAX_BRIEF_CHARS:
        raise BriefRejected("empty or oversized brief")
    invented = invented_numbers(body, allowed_numbers(inp), ignore=identifiers(inp))
    if invented:
        raise BriefRejected(f"{len(invented)} number(s) not from the tools: {invented[:5]}")


def _result_text(result: AgentResult) -> str:
    content = result.message.get("content", [])
    return "\n".join(block["text"] for block in content if "text" in block)
