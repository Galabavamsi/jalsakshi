"""Bedrock model factory and the model fallback chain (docs/ARCHITECTURE.md sections 6 and 10).

Every model is built with an explicit region and model id (never Strands defaults), temperature 0
and bounded timeouts. ``run_with_fallback`` walks ``MODEL_CHAIN``; callers fall back to their
deterministic template when every model fails.

Strands is imported lazily so that importing this module stays cheap for Lambda cold starts.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from strands import Agent
    from strands.models.bedrock import BedrockModel
    from strands.models.model import Model

logger = logging.getLogger(__name__)

# Claude Haiku 5.5 first (about a tenth of Haiku 4.5's price per token; global routing), then
# Haiku 4.5 in India, then Nova 2 Lite; callers fall back to a template after the last.
HAIKU_MODEL_ID: Final = "global.anthropic.claude-haiku-5-5"
HAIKU_45_MODEL_ID: Final = "in.anthropic.claude-haiku-4-5-20251001-v1:0"
NOVA_MODEL_ID: Final = "global.amazon.nova-2-lite-v1:0"
MODEL_CHAIN: Final[tuple[str, ...]] = (HAIKU_MODEL_ID, HAIKU_45_MODEL_ID, NOVA_MODEL_ID)

DEFAULT_REGION: Final = "ap-south-1"
REGION_ENV: Final = "JALSAKSHI_REGION"
MODEL_CHAIN_ENV: Final = "JALSAKSHI_MODEL_CHAIN"

DEFAULT_MAX_TOKENS: Final = 1024
CONNECT_TIMEOUT_S: Final = 5
READ_TIMEOUT_S: Final = 60
BOTO_MAX_ATTEMPTS: Final = 2

# Builds a Strands model from (model_id, region). Tests inject fakes through this.
type ModelFactory = Callable[[str, str], Model]


class AllModelsFailed(RuntimeError):
    """Every model in the chain failed; ``errors`` holds ``(model_id, exception)`` pairs."""

    def __init__(self, errors: Sequence[tuple[str, Exception]]) -> None:
        self.errors: list[tuple[str, Exception]] = list(errors)
        tried = ", ".join(f"{mid}: {type(exc).__name__}" for mid, exc in self.errors) or "none"
        super().__init__(f"all models failed ({tried})")


def agent_region() -> str:
    """Region for Bedrock calls: ``JALSAKSHI_REGION`` or ap-south-1 (never ``AWS_REGION``)."""
    return os.environ.get(REGION_ENV, "").strip() or DEFAULT_REGION


def model_chain() -> tuple[str, ...]:
    """Model ids to try in order; ``JALSAKSHI_MODEL_CHAIN`` (comma separated) overrides."""
    raw = os.environ.get(MODEL_CHAIN_ENV, "")
    ids = tuple(part.strip() for part in raw.split(",") if part.strip())
    return ids or MODEL_CHAIN


# Models that reject a ``temperature`` (they choose their own sampling, e.g. Claude Haiku 5.5).
NO_TEMPERATURE_MARKERS: Final = ("claude-haiku-5", "claude-sonnet-5", "claude-opus-5")
# Those models reason before answering; the reasoning uses output tokens.
THINKING_HEADROOM: Final = 1024


def accepts_temperature(model_id: str) -> bool:
    """False for models that refuse a ``temperature`` setting."""
    return not any(marker in model_id for marker in NO_TEMPERATURE_MARKERS)


def inference_config(model_id: str, max_tokens: int) -> dict[str, Any]:
    """Converse ``inferenceConfig``: temperature 0 where the model allows it, and room for the
    hidden reasoning of models that think first (it counts against ``maxTokens``)."""
    if accepts_temperature(model_id):
        return {"maxTokens": max_tokens, "temperature": 0}
    return {"maxTokens": max_tokens + THINKING_HEADROOM}


def make_model(
    model_id: str,
    region: str | None = None,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    read_timeout_s: int = READ_TIMEOUT_S,
) -> BedrockModel:
    """Build a Bedrock model with explicit region, temperature 0 and bounded timeouts."""
    from botocore.config import Config
    from strands.models.bedrock import BedrockModel

    client_config = Config(
        connect_timeout=CONNECT_TIMEOUT_S,
        read_timeout=read_timeout_s,
        retries={"total_max_attempts": BOTO_MAX_ATTEMPTS, "mode": "standard"},
    )
    thinks = not accepts_temperature(model_id)
    sampling: dict[str, Any] = {} if thinks else {"temperature": 0.0}
    return BedrockModel(
        model_id=model_id,
        region_name=region or agent_region(),
        boto_client_config=client_config,
        max_tokens=max_tokens + (THINKING_HEADROOM if thinks else 0),
        **sampling,
    )


def new_agent(
    model: Model,
    *,
    name: str,
    system_prompt: str,
    tools: Sequence[Any] = (),
) -> Agent:
    """Build a quiet Strands agent: no stdout printing, no SDK retries (the chain is the retry)."""
    from strands import Agent

    return Agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
        callback_handler=None,
        retry_strategy=None,
        name=name,
    )


def run_with_fallback[A, R](
    build_agent: Callable[[Model], A],
    call: Callable[[A], R],
    *,
    model_ids: Sequence[str] | None = None,
    region: str | None = None,
    model_factory: ModelFactory | None = None,
) -> tuple[R, str]:
    """Try each model in order; return ``(result, model_id)`` or raise ``AllModelsFailed``.

    Any exception from building the model, building the agent or ``call`` moves on to the next
    model, so ``call`` may raise to reject an answer (for example, an invented number).
    """
    factory = model_factory or make_model
    resolved_region = region or agent_region()
    errors: list[tuple[str, Exception]] = []
    for model_id in model_ids or model_chain():
        try:
            agent = build_agent(factory(model_id, resolved_region))
            return call(agent), model_id
        except Exception as exc:
            logger.warning(
                "agent model failed, trying next",
                extra={"model_id": model_id, "error_type": type(exc).__name__},
            )
            errors.append((model_id, exc))
    raise AllModelsFailed(errors)
