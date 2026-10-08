"""Offline HTTP helpers shared by the data tests (unique module name: tests/ has no packages)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

Handler = Callable[[httpx.Request], httpx.Response]
ClientFor = Callable[[Handler], httpx.Client]


@dataclass
class Recorder:
    """What the mock transport saw: every request sent and every backoff sleep requested."""

    requests: list[httpx.Request] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)


def json_response(payload: object, status: int = 200) -> httpx.Response:
    """A JSON response as an upstream API would send it."""
    return httpx.Response(status, json=payload)
