"""Client factory, retry with backoff and error mapping (jalsakshi.data.http)."""

from __future__ import annotations

from datetime import UTC

import httpx
import pytest
from data_fakes import ClientFor, Handler, Recorder

from jalsakshi.data import http as data_http
from jalsakshi.data.http import (
    USER_AGENT,
    DataSourceError,
    RetryPolicy,
    borrow_client,
    get_response,
    response_json,
    utc_now,
)

URL = "https://example.test/report"


def _sequence(*outcomes: int | Exception) -> Handler:
    """Handler that plays the given status codes or exceptions in order, then keeps the last."""
    queue = list(outcomes)

    def handler(request: httpx.Request) -> httpx.Response:
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, text=f"status {outcome}")

    return handler


def test_client_sends_user_agent_and_has_timeouts(client_for: ClientFor, recorder: Recorder):
    client = client_for(_sequence(200))
    get_response(client, URL)
    assert recorder.requests[0].headers["User-Agent"] == USER_AGENT
    assert client.timeout.connect == 5.0
    assert client.timeout.read == 20.0


def test_transient_status_is_retried_with_exponential_backoff(
    client_for: ClientFor, recorder: Recorder
):
    response = get_response(client_for(_sequence(503, 502, 200)), URL)
    assert response.status_code == 200
    assert len(recorder.requests) == 3
    assert recorder.sleeps == [0.5, 1.0]


def test_gives_up_after_three_retries(client_for: ClientFor, recorder: Recorder):
    with pytest.raises(DataSourceError, match="HTTP 503"):
        get_response(client_for(_sequence(503)), URL)
    assert len(recorder.requests) == 4
    assert recorder.sleeps == [0.5, 1.0, 2.0]


def test_transport_errors_are_retried(client_for: ClientFor, recorder: Recorder):
    handler = _sequence(httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), 200)
    assert get_response(client_for(handler), URL).status_code == 200
    assert len(recorder.requests) == 3


def test_persistent_transport_error_maps_to_data_source_error(
    client_for: ClientFor, recorder: Recorder
):
    with pytest.raises(DataSourceError, match="ConnectError"):
        get_response(client_for(_sequence(httpx.ConnectError("refused"))), URL)
    assert len(recorder.requests) == 4


def test_client_errors_are_not_retried(client_for: ClientFor, recorder: Recorder):
    with pytest.raises(DataSourceError, match="HTTP 404: status 404"):
        get_response(client_for(_sequence(404)), URL)
    assert len(recorder.requests) == 1
    assert recorder.sleeps == []


def test_non_idempotent_requests_are_not_retried(client_for: ClientFor, recorder: Recorder):
    response = client_for(_sequence(503, 200)).post(URL, content=b"x")
    assert response.status_code == 503
    assert len(recorder.requests) == 1


def test_retry_delay_is_capped():
    policy = RetryPolicy(retries=6, backoff_s=1.0, max_backoff_s=4.0)
    assert [policy.delay(i) for i in range(5)] == [1.0, 2.0, 4.0, 4.0, 4.0]


def test_borrow_client_leaves_caller_client_open(client_for: ClientFor):
    client = client_for(_sequence(200))
    with borrow_client(client) as borrowed:
        assert borrowed is client
    assert not client.is_closed


def test_borrow_client_closes_the_client_it_creates(monkeypatch: pytest.MonkeyPatch):
    created: list[httpx.Client] = []

    def fake_make_client() -> httpx.Client:
        created.append(httpx.Client(transport=httpx.MockTransport(_sequence(200))))
        return created[-1]

    monkeypatch.setattr(data_http, "make_client", fake_make_client)
    with borrow_client(None) as owned:
        assert owned is created[0]
    assert created[0].is_closed


def test_response_json_rejects_malformed_body():
    response = httpx.Response(200, text="<html>", request=httpx.Request("GET", URL))
    with pytest.raises(DataSourceError, match="valid JSON"):
        response_json(response)


def test_long_error_bodies_are_truncated(client_for: ClientFor):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="x" * 1000)

    with pytest.raises(DataSourceError) as caught:
        get_response(client_for(handler), URL)
    assert len(str(caught.value)) < 300


def test_utc_now_is_timezone_aware():
    assert utc_now().tzinfo is UTC
