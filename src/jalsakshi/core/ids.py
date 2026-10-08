"""Time-sortable identifiers with no external dependencies.

Format: ``{prefix}_{time}{random}``, where ``time`` is the Unix time in milliseconds as 10
characters of lowercase Crockford base32 and ``random`` is 80 bits from `secrets` as 16 more
characters. Ids with the same prefix sort lexicographically by creation time (to the
millisecond), which keeps DynamoDB sort keys and console lists in time order.
"""

from __future__ import annotations

import re
import secrets
import time
from datetime import UTC, datetime, timedelta

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32: ASCII order == numeric order
_DECODE = {char: index for index, char in enumerate(_ALPHABET)}
_TIME_CHARS = 10
_RANDOM_CHARS = 16
_RANDOM_BITS = 5 * _RANDOM_CHARS
_PREFIX = re.compile(r"[a-z][a-z0-9]{0,15}")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)


def new_id(prefix: str, *, at: datetime | None = None) -> str:
    """Return a new id such as ``tkt_01k7c3z9q0...``; `at` fixes the time part (default: now)."""
    name = _checked_prefix(prefix)
    millis = _epoch_millis(at) if at is not None else time.time_ns() // 1_000_000
    stamp = _encode(millis, _TIME_CHARS)
    noise = _encode(secrets.randbits(_RANDOM_BITS), _RANDOM_CHARS)
    return f"{name}_{stamp}{noise}"


def id_timestamp(value: str) -> datetime:
    """Return the UTC creation time (millisecond precision) encoded in an id from `new_id`."""
    _, sep, body = value.rpartition("_")
    if not sep or len(body) != _TIME_CHARS + _RANDOM_CHARS:
        raise ValueError(f"not a JalSakshi id: {value!r}")
    return _EPOCH + _decode(body[:_TIME_CHARS]) * _ONE_MS


def _checked_prefix(prefix: str) -> str:
    """Validate the prefix ("tkt" or "tkt_"): lowercase, starts with a letter, at most 16 chars."""
    name = prefix.removesuffix("_")
    if _PREFIX.fullmatch(name) is None:
        raise ValueError(f"id prefix must match [a-z][a-z0-9]{{0,15}}, got {prefix!r}")
    return name


def _epoch_millis(at: datetime) -> int:
    """Milliseconds since the Unix epoch for an aware datetime."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("naive datetime: pass an aware datetime to new_id(at=...)")
    millis = (at - _EPOCH) // _ONE_MS
    if millis < 0:
        raise ValueError("ids cannot encode times before 1970")
    return millis


def _encode(value: int, width: int) -> str:
    """Encode a non-negative int as fixed-width Crockford base32."""
    if value >= 32**width:
        raise ValueError(f"{value} does not fit in {width} base32 characters")
    chars = []
    for _ in range(width):
        value, digit = divmod(value, 32)
        chars.append(_ALPHABET[digit])
    return "".join(reversed(chars))


def _decode(text: str) -> int:
    """Decode lowercase Crockford base32 into an int."""
    value = 0
    for char in text:
        if char not in _DECODE:
            raise ValueError(f"invalid base32 character {char!r}")
        value = value * 32 + _DECODE[char]
    return value
