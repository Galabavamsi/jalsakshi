"""IVR actions: what the engine asks a phone channel to do next (docs/ARCHITECTURE.md section 13).

``Action`` is a tagged union on ``type``: ``play`` | ``get_digits`` | ``record`` | ``hangup``.
Adapters (Vobiz XML, the web simulator) translate a list of actions; the engine never sees them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from jalsakshi.voice.catalog import PromptCatalog, audio_url, default_catalog


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Play(_Action):
    """Play one prompt: pre-rendered audio if the channel has it, else ``text_hi`` via TTS."""

    type: Literal["play"] = "play"
    prompt_key: str = Field(min_length=1)
    text_hi: str
    audio_url: str | None = None


class GetDigits(_Action):
    """Play ``prompts`` (interruptible) and wait up to ``timeout_s`` for ``num_digits`` keys."""

    type: Literal["get_digits"] = "get_digits"
    num_digits: int = Field(default=1, ge=1, le=32)
    timeout_s: int = Field(default=10, ge=1, le=60)
    prompts: list[Play] = Field(min_length=1)


class Record(_Action):
    """Record the caller for at most ``max_s`` seconds after a beep; ``#`` ends it early."""

    type: Literal["record"] = "record"
    max_s: int = Field(default=15, ge=1, le=300)


class Hangup(_Action):
    """End the call."""

    type: Literal["hangup"] = "hangup"


Action = Annotated[Play | GetDigits | Record | Hangup, Field(discriminator="type")]
ACTION_LIST: TypeAdapter[list[Action]] = TypeAdapter(list[Action])


def actions_to_json(actions: Sequence[Action]) -> list[dict[str, Any]]:
    """Serialise actions to plain JSON-ready dicts."""
    return ACTION_LIST.dump_python(list(actions), mode="json")


def actions_from_json(data: object) -> list[Action]:
    """Parse a JSON-ready list back into actions (raises pydantic.ValidationError)."""
    return ACTION_LIST.validate_python(data)


def with_audio_urls(
    actions: Sequence[Action], base_url: str, catalog: PromptCatalog | None = None
) -> list[Action]:
    """Copy of ``actions`` where every Play with a pre-rendered clip gets its ``audio_url``."""
    cat = catalog or default_catalog()

    def fill(play: Play) -> Play:
        if play.audio_url or not cat.has_audio(play.prompt_key):
            return play
        return play.model_copy(update={"audio_url": audio_url(play.prompt_key, base_url)})

    filled: list[Action] = []
    for action in actions:
        if isinstance(action, Play):
            filled.append(fill(action))
        elif isinstance(action, GetDigits):
            filled.append(action.model_copy(update={"prompts": [fill(p) for p in action.prompts]}))
        else:
            filled.append(action)
    return filled
