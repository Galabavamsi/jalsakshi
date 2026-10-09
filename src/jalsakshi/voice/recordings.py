"""Vobiz voice-note recordings: fetch, archive to the evidence bucket, delete the Vobiz copy.

Flow (docs/ARCHITECTURE.md section 15.6): the ``RecordStop`` callback carries the file URL; the
notes Lambda fetches it with the account credentials, stores it at
``s3://<evidence>/audio/{village_id}/{call_id}.{wav|mp3}`` (SSE-S3; the bucket lifecycle keeps it
365 days) and then deletes the copy on Vobiz.

The URL comes from a webhook, so ``fetch_recording`` only fetches ``https://*.vobiz.ai`` (an SSRF
guard) and caps the size. Redirects are followed by hand: the Vobiz auth headers go only to
``*.vobiz.ai`` hosts (a storage redirect gets none), and every hop must stay on HTTPS with a host
name, never an IP address.

Docs relied on (read 2026-10-08): https://vobiz.ai/docs/xml/record and
https://vobiz.ai/docs/api-reference/authentication
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, Final
from urllib.parse import urljoin, urlsplit

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from jalsakshi.voice.adapters.vobiz import API_BASE, VobizAuth
from jalsakshi.voice.stt import CONTENT_TYPES, sniff_audio_format

logger = logging.getLogger(__name__)

ALLOWED_HOST_SUFFIX: Final = ".vobiz.ai"
DEFAULT_MAX_BYTES: Final = 5_000_000
MAX_REDIRECTS: Final = 5
DEFAULT_TIMEOUT_S: Final = 20.0
ARCHIVE_PREFIX: Final = "audio"
DELETED_STATUSES: Final = frozenset({200, 202, 204, 404})
"""Delete outcomes that leave no copy on Vobiz (404: already gone)."""

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class RecordingError(RuntimeError):
    """A recording could not be fetched or archived."""


def is_vobiz_url(url: str) -> bool:
    """True for an ``https`` URL on a ``*.vobiz.ai`` host, default port, no user info."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and host.endswith(ALLOWED_HOST_SUFFIX)
        and not parts.username
        and not parts.password
        and port in (None, 443)
    )


def fetch_recording(
    url: str,
    auth: VobizAuth,
    http: httpx.Client,
    max_bytes: int = DEFAULT_MAX_BYTES,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> bytes:
    """Download a Vobiz recording; raises ``RecordingError`` for a bad URL, status or size."""
    if not is_vobiz_url(url):
        raise RecordingError(f"refusing to fetch a recording from {_safe(url)}")
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        headers = _auth_headers(auth) if is_vobiz_url(current) else {}
        try:
            with http.stream(
                "GET", current, headers=headers, follow_redirects=False, timeout=timeout_s
            ) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    current = _next_hop(current, response)
                    continue
                if response.status_code != httpx.codes.OK:
                    raise RecordingError(
                        f"recording fetch from {_safe(current)} returned "
                        f"HTTP {response.status_code}"
                    )
                return _read_capped(response, max_bytes)
        except httpx.HTTPError as exc:
            raise RecordingError(
                f"recording fetch from {_safe(current)} failed: {type(exc).__name__}"
            ) from exc
    raise RecordingError(f"too many redirects fetching {_safe(url)}")


def archive_recording(data: bytes, *, s3: Any, bucket: str, village_id: str, call_id: str) -> str:
    """Store a recording at ``audio/{village_id}/{call_id}.{fmt}`` with SSE-S3; returns the key."""
    if not data:
        raise RecordingError("no recording data to archive")
    for label, value in (("village_id", village_id), ("call_id", call_id)):
        if not _is_safe_segment(value):
            raise ValueError(f"{label} is not a safe S3 key segment: {value!r}")
    fmt = sniff_audio_format(data)
    key = f"{ARCHIVE_PREFIX}/{village_id}/{call_id}.{fmt}"
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=CONTENT_TYPES[fmt],
            ServerSideEncryption="AES256",
        )
    except (ClientError, BotoCoreError) as exc:
        raise RecordingError(f"could not archive recording {key}: {type(exc).__name__}") from exc
    return key


def delete_vobiz_recording(
    recording_id: str,
    auth: VobizAuth,
    http: httpx.Client,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> bool:
    """Delete the Vobiz copy; True if it is gone (200/202/204/404). Never raises on failure."""
    if not _is_safe_segment(recording_id):
        logger.warning("not deleting recording with an unsafe id")
        return False
    url = f"{API_BASE}/Account/{auth.auth_id}/Recording/{recording_id}/"
    try:
        response = http.delete(url, headers=_auth_headers(auth), timeout=timeout_s)
    except httpx.HTTPError as exc:
        logger.warning("Vobiz recording delete %s failed: %s", recording_id, type(exc).__name__)
        return False
    if response.status_code in DELETED_STATUSES:
        return True
    logger.warning("Vobiz recording delete %s returned HTTP %d", recording_id, response.status_code)
    return False


def _auth_headers(auth: VobizAuth) -> dict[str, str]:
    return {"X-Auth-ID": auth.auth_id, "X-Auth-Token": auth.auth_token}


def _next_hop(current: str, response: httpx.Response) -> str:
    location = response.headers.get("location")
    if not location:
        raise RecordingError(f"redirect from {_safe(current)} has no Location")
    target = urljoin(current, location)
    parts = urlsplit(target)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or _is_ip(host) or host == "localhost":
        raise RecordingError(f"refusing a redirect to {_safe(target)}")
    return target


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise RecordingError(f"recording is {declared} bytes; the limit is {max_bytes}")
    body = bytearray()
    for part in response.iter_bytes():
        body.extend(part)
        if len(body) > max_bytes:
            raise RecordingError(f"recording is larger than {max_bytes} bytes")
    if not body:
        raise RecordingError("recording is empty")
    return bytes(body)


def _is_safe_segment(value: str) -> bool:
    return bool(_SAFE_SEGMENT.match(value)) and ".." not in value


def _safe(url: str) -> str:
    """Scheme, host and path only: query strings can carry signed tokens."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid url>"
    host = parts.hostname or ""
    return f"{parts.scheme}://{host}{parts.path}"
