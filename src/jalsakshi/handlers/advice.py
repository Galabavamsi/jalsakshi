"""AI advice on a complaint for the console (ARCHITECTURE.md §15.14): an overview and a
suggested next step. Advice only: buttons in the console carry out what the secretary decides.

The decision models' keys are the optional SSM parameters ``jev_api_key`` and
``openai_api_key`` (Jev first, then OpenAI Decisions); without them, or when neither is sure,
the suggestion comes from the fixed rules in ``agent.overview``. Results are cached per Lambda
container for each version of a complaint (its ``updated_at``) and hour, so reopening the page
costs nothing while time-based advice ("no word from the operator for a day") still moves on.
"""

from __future__ import annotations

from typing import Final

from jalsakshi.agent.overview import (
    Overview,
    Suggestion,
    facts_for,
    suggest,
    write_overview,
)
from jalsakshi.core.models import Ticket
from jalsakshi.handlers import config
from jalsakshi.handlers.common import logger

JEV_API_KEY_PARAM: Final = "jev_api_key"
OPENAI_API_KEY_PARAM: Final = "openai_api_key"
_CACHE_MAX: Final = 200
_cache: dict[tuple[str, str, str], Overview] = {}


def overview(ticket: Ticket) -> Overview:
    """Overview text and suggested next step for this version of the complaint."""
    now = config.now()
    key = (ticket.id, ticket.updated_at.isoformat(), now.strftime("%Y%m%d%H"))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    facts = facts_for(ticket, now)
    suggestion = suggestion_for(ticket) if not facts.closed else None
    text, source = write_overview(facts, suggestion)
    result = Overview(
        text=text, text_source=source, suggestion=suggestion, facts=facts, generated_at=now
    )
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = result
    return result


def suggestion_for(ticket: Ticket) -> Suggestion:
    """The next step: Jev, then OpenAI Decisions, then the fixed rules (see ``suggest``)."""
    facts = facts_for(ticket, config.now())
    return suggest(
        facts,
        jev_key=_key(JEV_API_KEY_PARAM),
        openai_key=_key(OPENAI_API_KEY_PARAM),
        http=config.http_client(),
    )


def _key(param: str) -> str | None:
    try:
        value = config.secrets.get(param, required=False)
    except Exception as exc:  # an unreadable key only means "skip that model"
        logger.warning(
            "decision key unreadable", extra={"param": param, "error": type(exc).__name__}
        )
        return None
    return str(value) if value else None
