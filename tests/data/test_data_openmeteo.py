"""Recent rain from Open-Meteo (jalsakshi.data.openmeteo), offline from a saved response."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from data_fakes import ClientFor, Recorder, json_response
from hypothesis import given
from hypothesis import strategies as st

from jalsakshi.core.models import Freshness
from jalsakshi.data.http import DataSourceError
from jalsakshi.data.openmeteo import (
    FORECAST_URL,
    SOURCE_NAME,
    DailyRain,
    RainSummary,
    parse_rain,
    rain_last_days,
)

FIXTURE = "openmeteo_past7.json"
DURG = (21.19, 81.28)
FETCHED_AT = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


@pytest.fixture
def payload(fixture_text: Callable[[str], str]) -> dict[str, Any]:
    return json.loads(fixture_text(FIXTURE))


def _with_values(payload: dict[str, Any], values: list[float | None]) -> dict[str, Any]:
    start = date(2026, 10, 1)
    payload["daily"] = {
        "time": [(start + timedelta(days=i)).isoformat() for i in range(len(values))],
        "precipitation_sum": values,
    }
    return payload


def test_fetch_sums_the_last_seven_days_with_model_source(
    payload: dict[str, Any], client_for: ClientFor, recorder: Recorder
):
    result = rain_last_days(*DURG, client=client_for(lambda request: json_response(payload)))

    assert isinstance(result, RainSummary)
    assert result.total_mm == 0.4
    assert len(result.daily) == 7
    assert result.daily[0] == DailyRain(date=date(2026, 10, 1), mm=0.0)
    assert result.daily[5] == DailyRain(date=date(2026, 10, 6), mm=0.3)
    assert result.source.source == SOURCE_NAME
    assert result.source.freshness is Freshness.MODEL
    assert result.source.observed_at is None
    assert result.source.url is not None and result.source.url.startswith(FORECAST_URL)

    params = recorder.requests[0].url.params
    assert (params["latitude"], params["longitude"]) == ("21.19", "81.28")
    assert params["daily"] == "precipitation_sum"
    assert params["past_days"] == "7"
    assert params["forecast_days"] == "0"
    assert params["timezone"] == "Asia/Kolkata"


def test_days_parameter_is_passed_through(
    payload: dict[str, Any], client_for: ClientFor, recorder: Recorder
):
    rain_last_days(*DURG, days=3, client=client_for(lambda request: json_response(payload)))
    assert recorder.requests[0].url.params["past_days"] == "3"


def test_missing_days_are_kept_but_not_summed(payload: dict[str, Any]):
    result = parse_rain(
        _with_values(payload, [1.25, None, 2.5]), url=FORECAST_URL, fetched_at=FETCHED_AT
    )
    assert result.total_mm == 3.75
    assert [d.mm for d in result.daily] == [1.25, None, 2.5]
    assert result.source.fetched_at == FETCHED_AT


def test_all_values_missing_raises(payload: dict[str, Any]):
    with pytest.raises(DataSourceError, match="no precipitation"):
        parse_rain(_with_values(payload, [None, None]), url=FORECAST_URL, fetched_at=FETCHED_AT)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.pop("daily"), "no 'daily'"),
        (lambda p: p["daily"]["time"].pop(), "malformed"),
        (lambda p: p["daily_units"].update(precipitation_sum="inch"), "unit"),
        (lambda p: p["daily"]["precipitation_sum"].__setitem__(0, -1.0), "negative"),
        (lambda p: p["daily"]["precipitation_sum"].__setitem__(0, "lots"), "bad precipitation"),
        (lambda p: p["daily"]["time"].__setitem__(0, "yesterday"), "bad date"),
    ],
)
def test_malformed_payloads_raise(
    payload: dict[str, Any], mutate: Callable[[dict[str, Any]], object], message: str
):
    mutate(payload)
    with pytest.raises(DataSourceError, match=message):
        parse_rain(payload, url=FORECAST_URL, fetched_at=FETCHED_AT)


def test_api_error_reason_is_reported(client_for: ClientFor, recorder: Recorder):
    body = {"error": True, "reason": "Parameter 'past_days' is out of range"}

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(body, status=400)

    with pytest.raises(DataSourceError, match="past_days"):
        rain_last_days(*DURG, client=client_for(handler))
    assert len(recorder.requests) == 1


def test_error_flag_in_a_200_body_raises():
    with pytest.raises(DataSourceError, match="Open-Meteo error: boom"):
        parse_rain({"error": True, "reason": "boom"}, url=FORECAST_URL, fetched_at=FETCHED_AT)


@pytest.mark.parametrize(
    ("lat", "lon", "days"),
    [(91.0, 81.0, 7), (21.0, -181.0, 7), (21.0, 81.0, 0), (21.0, 81.0, 93)],
)
def test_arguments_are_validated_before_any_request(
    lat: float, lon: float, days: int, client_for: ClientFor, recorder: Recorder
):
    with pytest.raises(ValueError):
        rain_last_days(lat, lon, days, client=client_for(lambda request: json_response({})))
    assert recorder.requests == []


@given(
    st.lists(
        st.one_of(st.none(), st.floats(min_value=0, max_value=500, allow_nan=False)),
        min_size=1,
        max_size=14,
    ).filter(lambda values: any(v is not None for v in values))
)
def test_total_is_the_rounded_sum_of_known_days(values: list[float | None]):
    payload = _with_values({"daily_units": {"precipitation_sum": "mm"}}, values)
    result = parse_rain(payload, url=FORECAST_URL, fetched_at=FETCHED_AT)
    expected = round(math.fsum(v for v in values if v is not None), 2)
    assert result.total_mm == expected
    assert len(result.daily) == len(values)
