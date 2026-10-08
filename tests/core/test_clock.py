from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfoNotFoundError

import pytest

from jalsakshi.core import clock
from jalsakshi.core.clock import (
    IST,
    hour_ist,
    in_window,
    ist_datetime,
    now_ist,
    parse_hhmm,
    parse_window,
    to_ist,
    today_ist,
)

OFFSET = timedelta(hours=5, minutes=30)


def test_now_ist_is_aware_and_offset_530() -> None:
    now = now_ist()
    assert now.utcoffset() == OFFSET
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


@pytest.mark.parametrize("month", [1, 4, 7, 10])
def test_ist_has_no_dst(month: int) -> None:
    assert datetime(2026, month, 1, 12, tzinfo=IST).utcoffset() == OFFSET


def test_fixed_offset_fallback_without_tz_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(key: str) -> None:
        raise ZoneInfoNotFoundError(key)

    monkeypatch.setattr(clock, "ZoneInfo", missing)
    fallback = clock._load_ist()
    assert datetime(2026, 10, 9, 9, tzinfo=fallback) == datetime(2026, 10, 9, 9, tzinfo=IST)
    assert fallback.tzname(None) == "IST"


def test_to_ist_converts_utc() -> None:
    assert to_ist(datetime(2026, 10, 9, 3, 30, tzinfo=UTC)) == datetime(
        2026, 10, 9, 9, 0, tzinfo=IST
    )


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_ist(datetime(2026, 10, 9, 9, 0))
    with pytest.raises(ValueError, match="naive"):
        hour_ist(datetime(2026, 10, 9, 9, 0))


@pytest.mark.parametrize(
    ("utc_hour", "utc_minute", "expected"),
    [(3, 29, 8), (3, 30, 9), (15, 29, 20), (15, 30, 21), (18, 30, 0)],
)
def test_hour_ist(utc_hour: int, utc_minute: int, expected: int) -> None:
    assert hour_ist(datetime(2026, 10, 9, utc_hour, utc_minute, tzinfo=UTC)) == expected


def test_hour_ist_defaults_to_now() -> None:
    assert 0 <= hour_ist() <= 23


def test_today_ist_rolls_over_at_ist_midnight() -> None:
    assert today_ist(datetime(2026, 10, 9, 18, 29, tzinfo=UTC)) == date(2026, 10, 9)
    assert today_ist(datetime(2026, 10, 9, 18, 30, tzinfo=UTC)) == date(2026, 10, 10)


def test_today_ist_defaults_to_now() -> None:
    before = now_ist().date()
    today = today_ist()
    assert before <= today <= now_ist().date()


def test_parse_hhmm_and_ist_datetime() -> None:
    assert parse_hhmm("09:05") == time(9, 5)
    assert parse_hhmm("23:59") == time(23, 59)
    assert ist_datetime(date(2026, 10, 9), "10:30") == datetime(2026, 10, 9, 10, 30, tzinfo=IST)


def test_parse_window() -> None:
    assert parse_window("09:00-20:00") == (time(9, 0), time(20, 0))
    assert parse_window("22:00-06:00") == (time(22, 0), time(6, 0))


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "09:00",
        "9:00-20:00",
        "09:00-2000",
        "24:00-25:00",
        "09:60-10:00",
        "09:00-20:00-21:00",
        "09:00 - 20:00",
        "٩٩:00-20:00",  # Arabic-Indic digits must not pass as HH
        "09:00-09:00",
    ],
)
def test_parse_window_rejects_bad_input(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_window(bad)


@pytest.mark.parametrize(
    ("ist_clock", "expected"),
    [
        (time(8, 59, 59), False),
        (time(9, 0), True),
        (time(14, 0), True),
        (time(19, 59, 59), True),
        (time(20, 0), False),
        (time(23, 0), False),
    ],
)
def test_in_window_start_inclusive_end_exclusive(ist_clock: time, expected: bool) -> None:
    moment = datetime.combine(date(2026, 10, 9), ist_clock, tzinfo=IST)
    assert in_window("09:00-20:00", moment) is expected
    assert in_window((time(9, 0), time(20, 0)), moment) is expected


def test_in_window_converts_to_ist_first() -> None:
    # 03:30 UTC is 09:00 IST: inside; 15:30 UTC is 21:00 IST: outside the legal calling window.
    assert in_window("09:00-21:00", datetime(2026, 10, 9, 3, 30, tzinfo=UTC))
    assert not in_window("09:00-21:00", datetime(2026, 10, 9, 15, 30, tzinfo=UTC))


@pytest.mark.parametrize(
    ("ist_clock", "expected"),
    [(time(21, 59), False), (time(22, 0), True), (time(2, 0), True), (time(6, 0), False)],
)
def test_in_window_wraps_midnight(ist_clock: time, expected: bool) -> None:
    moment = datetime.combine(date(2026, 10, 9), ist_clock, tzinfo=IST)
    assert in_window("22:00-06:00", moment) is expected


def test_in_window_rejects_empty_tuple_window() -> None:
    with pytest.raises(ValueError, match="empty window"):
        in_window((time(9, 0), time(9, 0)), now_ist())
