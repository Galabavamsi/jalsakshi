"""Web-phone simulator adapter for the console's ``/sim`` API (docs/ARCHITECTURE.md section 13).

The browser keypad drives the same engine as a real call. Answers captured this way are stored
with ``captured_via = SIMULATOR`` so they are always labelled as simulated.

- ``POST /sim/calls`` body ``{household_id | operator_id, purpose}`` -> ``{call_id, actions}``
- ``POST /sim/calls/{call_id}/input`` body ``{digits?, timeout?}`` -> ``{actions, done}``
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jalsakshi.core.models import CapturedVia, Purpose
from jalsakshi.voice.actions import Action, actions_to_json, with_audio_urls
from jalsakshi.voice.catalog import PromptCatalog

CAPTURED_VIA = CapturedVia.SIMULATOR


class SimStartRequest(BaseModel):
    """Body of ``POST /sim/calls``: one household (DAILY / VERIFY) or one operator (OPERATOR)."""

    model_config = ConfigDict(extra="forbid")

    household_id: str | None = Field(default=None, min_length=1)
    operator_id: str | None = Field(default=None, min_length=1)
    purpose: Purpose

    @model_validator(mode="after")
    def _one_subject(self) -> Self:
        if (self.household_id is None) == (self.operator_id is None):
            raise ValueError("give exactly one of household_id or operator_id")
        if (self.purpose is Purpose.OPERATOR) != (self.operator_id is not None):
            raise ValueError("OPERATOR calls take operator_id; DAILY and VERIFY take household_id")
        return self


class SimInput(BaseModel):
    """Body of ``POST /sim/calls/{call_id}/input``: keys pressed, or a timeout."""

    model_config = ConfigDict(extra="forbid")

    digits: str | None = Field(default=None, pattern=r"^[0-9*#]{1,8}$")
    timeout: bool = False

    @field_validator("digits", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


def to_json(
    actions: Sequence[Action],
    audio_base_url: str | None = None,
    catalog: PromptCatalog | None = None,
) -> list[dict[str, Any]]:
    """Actions as JSON-ready dicts; with a base URL, prompts that have a clip get ``audio_url``."""
    if audio_base_url:
        actions = with_audio_urls(actions, audio_base_url, catalog)
    return actions_to_json(actions)


def from_json(payload: Mapping[str, Any] | str | bytes | None) -> SimInput:
    """Parse an input body (dict or raw JSON). Raises pydantic.ValidationError or ValueError."""
    return SimInput.model_validate(_as_mapping(payload))


def parse_start(payload: Mapping[str, Any] | str | bytes | None) -> SimStartRequest:
    """Parse a start-call body (dict or raw JSON)."""
    return SimStartRequest.model_validate(_as_mapping(payload))


def start_response(
    call_id: str, actions: Sequence[Action], audio_base_url: str | None = None
) -> dict[str, Any]:
    """Response body for ``POST /sim/calls``."""
    return {"call_id": call_id, "actions": to_json(actions, audio_base_url)}


def input_response(
    actions: Sequence[Action], done: bool, audio_base_url: str | None = None
) -> dict[str, Any]:
    """Response body for ``POST /sim/calls/{call_id}/input``."""
    return {"actions": to_json(actions, audio_base_url), "done": done}


def _as_mapping(payload: Mapping[str, Any] | str | bytes | None) -> Mapping[str, Any]:
    if payload is None or payload in ("", b""):
        return {}
    if isinstance(payload, str | bytes):
        decoded = json.loads(payload)
        if not isinstance(decoded, Mapping):
            raise ValueError("expected a JSON object")
        return decoded
    return payload
