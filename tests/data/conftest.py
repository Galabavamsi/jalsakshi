"""Shared fixtures for the data fetcher tests: saved payloads and offline httpx clients."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from data_fakes import ClientFor, Handler, Recorder

from jalsakshi.data.http import make_client

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def client_for(recorder: Recorder) -> Iterator[ClientFor]:
    """Factory for production-configured clients whose network is a `httpx.MockTransport`."""
    clients: list[httpx.Client] = []

    def build(handler: Handler) -> httpx.Client:
        def record(request: httpx.Request) -> httpx.Response:
            recorder.requests.append(request)
            return handler(request)

        client = make_client(transport=httpx.MockTransport(record), sleep=recorder.sleeps.append)
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.close()


@pytest.fixture
def fixture_text() -> Callable[[str], str]:
    """Read a saved payload from tests/data/fixtures."""
    return lambda name: (FIXTURES / name).read_text("utf-8")
