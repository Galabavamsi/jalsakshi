"""Shared HTTP plumbing for the public data fetchers: one client factory, retries, error mapping.

Every fetcher in `jalsakshi.data` takes an optional `httpx.Client`. Tests pass a client built on
`httpx.MockTransport`; production code passes nothing and gets `make_client()`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

from jalsakshi import __version__

USER_AGENT = (
    f"JalSakshi/{__version__} (public-data fetcher; Jal Jeevan Mission tap-water check-ins)"
)
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
IST = timezone(timedelta(hours=5, minutes=30), "IST")
"""India Standard Time. India has no DST, so a fixed offset is exact (and needs no tzdata)."""

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class DataSourceError(RuntimeError):
    """A public data source could not be fetched or its response could not be understood."""


@dataclass(frozen=True)
class RetryPolicy:
    """Retry idempotent requests on transport errors and transient status codes.

    `retries` counts the extra attempts after the first one. The delay before retry n (0-based)
    is `backoff_s * 2**n`, capped at `max_backoff_s`.
    """

    retries: int = 3
    backoff_s: float = 0.5
    max_backoff_s: float = 4.0
    retry_statuses: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 500, 502, 503, 504})
    )

    def delay(self, retry_index: int) -> float:
        """Seconds to wait before the given retry (0 for the first retry)."""
        return min(self.backoff_s * (2**retry_index), self.max_backoff_s)


DEFAULT_RETRY = RetryPolicy()


class RetryTransport(httpx.BaseTransport):
    """Wraps another transport and retries idempotent requests with exponential backoff."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        policy: RetryPolicy = DEFAULT_RETRY,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._sleep = sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request, retrying transient failures; the last outcome is returned or raised."""
        if request.method not in _IDEMPOTENT_METHODS:
            return self._inner.handle_request(request)
        for retry_index in range(self._policy.retries):
            try:
                response = self._inner.handle_request(request)
            except httpx.TransportError:
                self._sleep(self._policy.delay(retry_index))
                continue
            if response.status_code not in self._policy.retry_statuses:
                return response
            response.close()
            self._sleep(self._policy.delay(retry_index))
        return self._inner.handle_request(request)

    def close(self) -> None:
        """Close the wrapped transport."""
        self._inner.close()


def make_client(
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    retry: RetryPolicy = DEFAULT_RETRY,
    sleep: Callable[[float], None] = time.sleep,
    headers: Mapping[str, str] | None = None,
) -> httpx.Client:
    """Build the shared client: JalSakshi user agent, timeouts, redirects and retry with backoff."""
    inner = transport if transport is not None else httpx.HTTPTransport()
    merged = {"User-Agent": USER_AGENT, **(headers or {})}
    return httpx.Client(
        transport=RetryTransport(inner, retry, sleep),
        timeout=timeout,
        headers=merged,
        follow_redirects=True,
    )


@contextmanager
def borrow_client(client: httpx.Client | None) -> Iterator[httpx.Client]:
    """Yield the caller's client untouched, or a fresh `make_client()` that is closed afterwards."""
    if client is not None:
        yield client
        return
    with make_client() as owned:
        yield owned


def get_response(
    client: httpx.Client, url: str, *, params: Mapping[str, Any] | None = None
) -> httpx.Response:
    """GET `url` and return a 2xx response, mapping every HTTP failure to `DataSourceError`."""
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _snippet(exc.response.text)
        raise DataSourceError(f"{url} returned HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise DataSourceError(f"{url} request failed: {type(exc).__name__}: {exc}") from exc
    return response


def _snippet(text: str, limit: int = 200) -> str:
    """First `limit` characters of a body on one line, for error messages."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def response_json(response: httpx.Response) -> Any:
    """Decode a JSON body, mapping malformed payloads to `DataSourceError`."""
    try:
        return response.json()
    except ValueError as exc:
        raise DataSourceError(f"{response.request.url} did not return valid JSON") from exc


def utc_now() -> datetime:
    """Timezone-aware current time in UTC, used for `SourceTag.fetched_at`."""
    return datetime.now(UTC)
