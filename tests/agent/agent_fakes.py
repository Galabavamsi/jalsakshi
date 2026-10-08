"""Offline fakes for the agent tests: a scripted Strands model and a factory that hands them out.

The real Strands ``Agent`` loop runs (tools, structured output, limits); only the model is fake.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from strands.models.model import Model

from jalsakshi.core.models import (
    Ticket,
    TicketEvent,
    TicketReason,
    TicketState,
)


@dataclass(frozen=True)
class ToolCall:
    """A scripted model turn that calls a tool."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Slow:
    """A scripted text turn whose first chunk arrives only after ``seconds``."""

    seconds: float
    text: str


type Turn = str | ToolCall | Slow | Exception


class ScriptedModel(Model):
    """Replays scripted turns: text ends the turn, ToolCall requests a tool, Exception raises."""

    def __init__(self, turns: list[Turn], model_id: str = "fake") -> None:
        self.turns = list(turns)
        self.model_id = model_id
        self.requests: list[dict[str, Any]] = []

    def update_config(self, **model_config: Any) -> None:
        """Nothing to configure."""

    def get_config(self) -> dict[str, Any]:
        return {"model_id": self.model_id}

    async def structured_output(  # type: ignore[override]
        self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("agents use structured_output_model, not this path")
        yield {}

    async def stream(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tool_specs: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.requests.append(
            {
                "messages": json.loads(json.dumps(messages, default=str)),
                "tools": [spec["name"] for spec in tool_specs or []],
                "system_prompt": system_prompt,
            }
        )
        if not self.turns:
            raise AssertionError("model called more times than scripted")
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        if isinstance(turn, Slow):
            await asyncio.sleep(turn.seconds)
            turn = turn.text
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(turn, ToolCall):
            tool_use = {"name": turn.name, "toolUseId": f"tool-{len(self.requests)}"}
            yield {"contentBlockStart": {"start": {"toolUse": tool_use}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn.args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": turn}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        usage = {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20}
        yield {"metadata": {"usage": usage, "metrics": {"latencyMs": 1}}}

    def tool_results(self) -> list[str]:
        """Text of every tool result the agent sent back to this model."""
        texts: list[str] = []
        for message in self.requests[-1]["messages"] if self.requests else []:
            for block in message.get("content", []):
                for item in block.get("toolResult", {}).get("content", []):
                    texts.append(item.get("text", ""))
        return texts


class ScriptedFactory:
    """A ``ModelFactory`` that hands out one ScriptedModel per requested model id, in order."""

    def __init__(self, *scripts: list[Turn]) -> None:
        self.scripts = list(scripts)
        self.calls: list[tuple[str, str]] = []
        self.models: list[ScriptedModel] = []

    def __call__(self, model_id: str, region: str) -> ScriptedModel:
        self.calls.append((model_id, region))
        if not self.scripts:
            raise AssertionError("more models requested than scripted")
        model = ScriptedModel(self.scripts.pop(0), model_id=model_id)
        self.models.append(model)
        return model


NOW = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)


def make_ticket(
    tid: str,
    opened: datetime,
    *,
    closed: datetime | None = None,
    reason: TicketReason = TicketReason.NO_SUPPLY,
    state: TicketState | None = None,
) -> Ticket:
    """A ticket, optionally closed by households at ``closed``."""
    events = []
    if closed is not None:
        events.append(
            TicketEvent(
                at=closed,
                actor="system",
                kind="VERIFY_QUORUM",
                from_state=TicketState.VERIFYING,
                to_state=TicketState.CLOSED_VERIFIED,
            )
        )
    final_state = state or (TicketState.CLOSED_VERIFIED if closed else TicketState.ASSIGNED)
    return Ticket(
        id=tid,
        village_id="v-kumhari",
        reason=reason,
        state=final_state,
        opened_at=opened,
        updated_at=closed or opened,
        events=events,
    )
