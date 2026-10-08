"""Recent rainfall from the keyless Open-Meteo forecast API (context only, never a decision input).

`past_days=N` with `forecast_days=0` returns the N complete days before today in the requested
timezone. Values are model output, so results are tagged `Freshness.MODEL`.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from jalsakshi.core.models import Freshness, SourceTag
from jalsakshi.data.http import (
    DataSourceError,
    borrow_client,
    get_response,
    response_json,
    utc_now,
)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE_NAME = "Open-Meteo weather model (daily precipitation sum)"
TIMEZONE = "Asia/Kolkata"
MAX_PAST_DAYS = 92


class DailyRain(BaseModel):
    """Rain on one local (IST) day; None when the model has no value for that day."""

    model_config = ConfigDict(frozen=True)

    date: date
    mm: float | None = Field(default=None, ge=0)


class RainSummary(BaseModel):
    """Total rain over the last N days, with the per-day series it was summed from."""

    model_config = ConfigDict(frozen=True)

    total_mm: float = Field(ge=0)
    daily: list[DailyRain]
    source: SourceTag


def rain_last_days(
    lat: float, lon: float, days: int = 7, *, client: httpx.Client | None = None
) -> RainSummary:
    """Rain at (lat, lon) over the `days` complete days before today (IST).

    Raises `ValueError` for out-of-range arguments and `DataSourceError` if the API fails.
    """
    params = _query_params(lat, lon, days)
    with borrow_client(client) as http:
        response = get_response(http, FORECAST_URL, params=params)
    return parse_rain(response_json(response), url=str(response.url), fetched_at=utc_now())


def parse_rain(payload: Any, *, url: str, fetched_at: datetime) -> RainSummary:
    """Build a `RainSummary` from an Open-Meteo `daily=precipitation_sum` response."""
    daily = _daily_block(payload)
    rows = [
        DailyRain(date=_day(stamp), mm=_millimetres(value))
        for stamp, value in zip(daily["time"], daily["precipitation_sum"], strict=True)
    ]
    known = [row.mm for row in rows if row.mm is not None]
    if not known:
        raise DataSourceError("Open-Meteo returned no precipitation values")
    source = SourceTag(
        source=SOURCE_NAME, url=url, fetched_at=fetched_at, freshness=Freshness.MODEL
    )
    return RainSummary(total_mm=round(math.fsum(known), 2), daily=rows, source=source)


def _query_params(lat: float, lon: float, days: int) -> dict[str, str | float | int]:
    """Validated query parameters for the forecast endpoint."""
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError(f"coordinates out of range: lat={lat}, lon={lon}")
    if not 1 <= days <= MAX_PAST_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_PAST_DAYS}, got {days}")
    return {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "past_days": days,
        "forecast_days": 0,
        "timezone": TIMEZONE,
    }


def _daily_block(payload: Any) -> dict[str, list[Any]]:
    """The `daily` object, checked for matching `time`/`precipitation_sum` lists in millimetres."""
    if not isinstance(payload, dict):
        raise DataSourceError("Open-Meteo response is not a JSON object")
    if payload.get("error"):
        raise DataSourceError(f"Open-Meteo error: {payload.get('reason', 'unknown')}")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise DataSourceError("Open-Meteo response has no 'daily' block")
    times, values = daily.get("time"), daily.get("precipitation_sum")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise DataSourceError("Open-Meteo 'daily' block is malformed")
    unit = (payload.get("daily_units") or {}).get("precipitation_sum", "mm")
    if unit != "mm":
        raise DataSourceError(f"Open-Meteo precipitation unit is {unit!r}, expected 'mm'")
    return {"time": times, "precipitation_sum": values}


def _day(stamp: Any) -> date:
    try:
        return date.fromisoformat(str(stamp))
    except ValueError as exc:
        raise DataSourceError(f"Open-Meteo returned a bad date: {stamp!r}") from exc


def _millimetres(value: Any) -> float | None:
    """A non-negative finite rainfall value, or None when missing."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise DataSourceError(f"Open-Meteo returned a bad precipitation value: {value!r}")
    if value < 0:
        raise DataSourceError(f"Open-Meteo returned negative precipitation: {value!r}")
    return float(value)
