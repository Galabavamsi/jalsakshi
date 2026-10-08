"""IST (Asia/Kolkata) time helpers.

Calling windows, check-in times and day boundaries are always IST. Naive datetimes are rejected,
because their zone is unknown and calling hours are a legal limit.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _load_ist() -> tzinfo:
    """Asia/Kolkata from the tz database, else its exact equivalent: +05:30, no DST since 1945.

    The fallback covers hosts without a tz database (Windows without the `tzdata` package).
    """
    try:
        return ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=5, minutes=30), "IST")


IST: tzinfo = _load_ist()

# A daily IST window: start is inclusive, end is exclusive. If start > end it wraps midnight.
type Window = tuple[time, time]

_HHMM = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")


def now_ist() -> datetime:
    """Return the current time as an aware IST datetime."""
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    """Convert an aware datetime to IST. Raise ValueError for a naive datetime."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime: attach a timezone (UTC or IST) before converting")
    return dt.astimezone(IST)


def hour_ist(dt: datetime | None = None) -> int:
    """Return the IST hour of day (0-23) for `dt`, or for now when omitted."""
    return (to_ist(dt) if dt is not None else now_ist()).hour


def today_ist(now: datetime | None = None) -> date:
    """Return the IST calendar date for `now`, or for the current time when omitted."""
    return (to_ist(now) if now is not None else now_ist()).date()


def parse_hhmm(value: str) -> time:
    """Parse a strict 24-hour "HH:MM" string (e.g. "09:00") into a time."""
    match = _HHMM.fullmatch(value)
    if match is None:
        raise ValueError(f"expected a 24-hour HH:MM time, got {value!r}")
    return time(int(match.group(1)), int(match.group(2)))


def ist_datetime(day: date, hhmm: str) -> datetime:
    """Combine an IST date and an "HH:MM" clock time into an aware IST datetime."""
    return datetime.combine(day, parse_hhmm(hhmm), tzinfo=IST)


def parse_window(window: str) -> Window:
    """Parse "HH:MM-HH:MM" (e.g. "09:00-20:00") into a (start, end) pair."""
    start, sep, end = window.partition("-")
    if not sep:
        raise ValueError(f"expected HH:MM-HH:MM, got {window!r}")
    return _checked((parse_hhmm(start), parse_hhmm(end)))


def in_window(window: str | Window, dt: datetime) -> bool:
    """Return True if `dt`, in IST, falls inside the window (start inclusive, end exclusive)."""
    start, end = parse_window(window) if isinstance(window, str) else _checked(window)
    clock = to_ist(dt).time()
    if start < end:
        return start <= clock < end
    return clock >= start or clock < end


def _checked(window: Window) -> Window:
    """Reject an empty window, whose meaning (never or always) would be ambiguous."""
    start, end = window
    if start == end:
        raise ValueError(f"empty window: start and end are both {start:%H:%M}")
    return start, end
