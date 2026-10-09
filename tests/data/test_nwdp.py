"""NWDP groundwater telemetry and IMD district rainfall (jalsakshi.data.nwdp), offline.

Fixtures are trimmed real responses captured on 9 Oct 2026: the Durg district readings of the
last 7 days' 6-hourly slots (`nwdp_gw_recent.json`), a sample of station Biroda_2's history
(`nwdp_gw_history_biroda.json`) and the newest 10 IMD rows for DURG (`nwdp_rain_durg.json`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from data_fakes import ClientFor, Recorder, json_response
from hypothesis import given
from hypothesis import strategies as st

from jalsakshi.core.models import Freshness
from jalsakshi.data.http import IST, DataSourceError
from jalsakshi.data.nwdp import (
    API_URL,
    F_LEVEL,
    HISTORY_ROWS,
    RAINFALL_PAGE,
    RAINFALL_RESOURCE,
    RAINFALL_SOURCE,
    SNAPSHOT_PATH,
    TELEMETRY_FIELDS,
    TELEMETRY_PAGE,
    TELEMETRY_RESOURCE,
    TIME_FORMAT,
    DistrictRainDay,
    district_rainfall,
    district_rainfall_or_snapshot,
    load_groundwater_snapshot,
    load_rainfall_snapshot,
    nearest_groundwater,
    nearest_groundwater_or_snapshot,
    parse_rainfall,
    parse_telemetry,
    recent_slots,
    summarise_rainfall,
    summarise_station,
)

KUTELA = (21.238001, 81.318368)
BIRODA = (21.2444, 81.2833)
KACHANDUR_WELL = (21.2584, 81.3364)  # closer to Kutelabhatha than Biroda_2
NOW = datetime(2026, 10, 9, 5, 0, tzinfo=IST)  # newest NWDP reading is 06-10-2026 18:00
FETCHED = datetime(2026, 10, 9, tzinfo=IST)
FIELDS = [{"id": name, "type": "text"} for name in TELEMETRY_FIELDS]


@pytest.fixture
def load(fixture_text: Callable[[str], str]) -> Callable[[str], dict[str, Any]]:
    return lambda name: json.loads(fixture_text(name))


def _filters(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.url.params["filters"])


def _payload(records: list[dict[str, Any]], fields: list[dict[str, str]] = FIELDS) -> dict:
    return {
        "success": True,
        "result": {"fields": fields, "records": records, "total": len(records)},
    }


def _row(station: str, point: tuple[float, float], at: datetime, level: str) -> dict[str, Any]:
    return {
        "_id": 1,
        "Station": station,
        "Latitude": f"{point[0]:.8f}",
        "Longitude": f"{point[1]:.8f}",
        "Data Acquisition Time": at.astimezone(IST).strftime(TIME_FORMAT),
        F_LEVEL: level,
    }


def _series(
    station: str, point: tuple[float, float], end: datetime, days: int, level: Callable[[int], str]
) -> list[dict[str, Any]]:
    """6-hourly rows ending at `end`, newest first (as `_id desc` returns them)."""
    return [_row(station, point, end - i * timedelta(hours=6), level(i)) for i in range(days * 4)]


def _router(
    recent: dict[str, Any], histories: dict[str, dict[str, Any]]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        station = _filters(request).get("Station")
        return json_response(recent if station is None else histories[station])

    return handler


# --- groundwater: live ------------------------------------------------------------------------


def test_picks_the_nearest_station_and_labels_it(
    load: Callable[[str], dict[str, Any]], client_for: ClientFor, recorder: Recorder
):
    handler = _router(
        load("nwdp_gw_recent.json"), {"Biroda_2": load("nwdp_gw_history_biroda.json")}
    )

    reading = nearest_groundwater(*KUTELA, client=client_for(handler), now=NOW)

    assert reading is not None
    assert (reading.station, reading.lat, reading.lon) == ("Biroda_2", *BIRODA)
    assert reading.distance_km == pytest.approx(3.7, abs=0.01)
    assert reading.depth_m_below_ground == 8.301
    assert reading.observed_at == datetime(2026, 10, 6, 18, 0, tzinfo=IST)
    assert reading.observed_at.utcoffset() == timedelta(hours=5, minutes=30)
    assert reading.stale is True  # 59 hours old
    # Fixture months: Mar 19.42, Apr 22.08, May 19.95 (Aug has one reading, too few).
    assert (reading.pre_monsoon_month, reading.pre_monsoon_depth_m) == ("2026-04", 22.08)
    assert reading.rise_since_pre_monsoon_m == 13.78
    source = reading.source
    assert source.source == (
        "CGWB telemetry via National Water Data Portal (nearest station, 3.7 km)"
    )
    assert source.freshness is Freshness.DAILY
    assert source.observed_at == reading.observed_at
    assert source.url == TELEMETRY_PAGE

    recent, history = recorder.requests
    assert str(recent.url).startswith(API_URL)
    assert recent.url.params["resource_id"] == TELEMETRY_RESOURCE
    assert recent.url.params["sort"] == "_id desc"
    assert recent.url.params["fields"] == ",".join(TELEMETRY_FIELDS)
    assert (recent.url.params["limit"], recent.url.params["offset"]) == ("1000", "0")
    assert _filters(recent) == {
        "District LGD Code": "378",
        "Data Acquisition Time": recent_slots(NOW),
    }
    assert _filters(history) == {"District LGD Code": "378", "Station": "Biroda_2"}
    assert history.url.params["limit"] == str(HISTORY_ROWS)


def test_a_reading_under_48_hours_old_is_live(
    load: Callable[[str], dict[str, Any]], client_for: ClientFor
):
    handler = _router(
        load("nwdp_gw_recent.json"), {"Biroda_2": load("nwdp_gw_history_biroda.json")}
    )
    now = datetime(2026, 10, 7, 10, 0, tzinfo=IST)

    reading = nearest_groundwater(*KUTELA, client=client_for(handler), now=now)

    assert reading is not None and reading.stale is False
    assert reading.source.freshness is Freshness.LIVE


def test_a_stuck_sensor_is_skipped_for_the_next_station(client_for: ClientFor, recorder: Recorder):
    end = datetime(2026, 10, 6, 18, 0, tzinfo=IST)
    stuck = _series("Kachandur", KACHANDUR_WELL, end, 40, lambda i: "-24.05")
    good = _series("Biroda_2", BIRODA, end, 40, lambda i: f"-{8.301 + i / 100:.3f}")
    recent = _payload(stuck[:4] + good[:4])
    handler = _router(recent, {"Kachandur": _payload(stuck), "Biroda_2": _payload(good)})

    reading = nearest_groundwater(*KUTELA, client=client_for(handler), now=NOW)

    assert reading is not None and reading.station == "Biroda_2"
    assert [_filters(r).get("Station") for r in recorder.requests] == [
        None,
        "Kachandur",
        "Biroda_2",
    ]


def test_marker_and_positive_levels_never_count_as_readings(
    client_for: ClientFor, recorder: Recorder
):
    end = datetime(2026, 10, 6, 18, 0, tzinfo=IST)
    markers = ["1", "0", "1.00", "0.00", "1.88", "", "-", "n/a"]
    bad = [
        _row("Kachandur", KACHANDUR_WELL, end - timedelta(hours=6 * i), v)
        for i, v in enumerate(markers)
    ]
    good = _series("Biroda_2", BIRODA, end, 10, lambda i: f"-{8.3 + i / 100:.2f}")
    handler = _router(_payload(bad + good[:2]), {"Biroda_2": _payload(good)})

    reading = nearest_groundwater(*KUTELA, client=client_for(handler), now=NOW)

    assert reading is not None and reading.station == "Biroda_2"
    assert len(recorder.requests) == 2  # Kachandur's history is never fetched


def test_tries_at_most_three_stations(client_for: ClientFor, recorder: Recorder):
    end = datetime(2026, 10, 6, 18, 0, tzinfo=IST)
    stations = {
        f"S{k}": _series(f"S{k}", (21.24 + k / 100, 81.30), end, 35, lambda i: "-9.5")
        for k in range(5)
    }
    recent = _payload([rows[0] for rows in stations.values()])
    handler = _router(recent, {name: _payload(rows) for name, rows in stations.items()})

    assert nearest_groundwater(*KUTELA, client=client_for(handler), now=NOW) is None
    assert [_filters(r).get("Station") for r in recorder.requests] == [None, "S0", "S1", "S2"]


def test_no_recent_reading_returns_none(client_for: ClientFor, recorder: Recorder):
    handler = _router(_payload([]), {})
    assert nearest_groundwater(*KUTELA, client=client_for(handler), now=NOW) is None
    assert len(recorder.requests) == 1


def test_readings_older_than_seven_days_do_not_qualify(
    load: Callable[[str], dict[str, Any]], client_for: ClientFor, recorder: Recorder
):
    handler = _router(load("nwdp_gw_recent.json"), {})
    later = datetime(2026, 10, 14, 0, 0, tzinfo=IST)
    assert nearest_groundwater(*KUTELA, client=client_for(handler), now=later) is None
    assert len(recorder.requests) == 1


def test_stations_beyond_max_km_are_ignored(
    load: Callable[[str], dict[str, Any]], client_for: ClientFor, recorder: Recorder
):
    handler = _router(load("nwdp_gw_recent.json"), {})
    assert nearest_groundwater(*KUTELA, client=client_for(handler), now=NOW, max_km=2) is None
    assert len(recorder.requests) == 1


def test_pages_until_the_total_is_reached(client_for: ClientFor, recorder: Recorder):
    end = datetime(2026, 10, 6, 18, 0, tzinfo=IST)
    rows = _series("Biroda_2", BIRODA, end, 400, lambda i: f"-{8 + i / 1000:.3f}")[:1500]

    def handler(request: httpx.Request) -> httpx.Response:
        if "Station" in _filters(request):
            return json_response(_payload(rows))
        offset, limit = int(request.url.params["offset"]), int(request.url.params["limit"])
        page = _payload(rows[offset : offset + limit])
        page["result"]["total"] = len(rows)
        return json_response(page)

    reading = nearest_groundwater(*KUTELA, client=client_for(handler), now=NOW)

    assert reading is not None
    offsets = [r.url.params.get("offset") for r in recorder.requests]
    assert offsets == ["0", "1000", None]


@pytest.mark.parametrize(
    ("status", "body", "match"),
    [
        (409, {"success": False, "error": {"message": "Not found"}}, "HTTP 409"),
        (200, {"success": False, "error": {"message": "boom"}}, "boom"),
        (200, {"success": True, "result": {"fields": FIELDS}}, "records"),
        (200, {"success": True, "result": {"fields": FIELDS[:3], "records": []}}, "missing"),
        (200, ["not", "an", "object"], "JSON object"),
    ],
)
def test_bad_responses_raise_data_source_error(
    status: int, body: Any, match: str, client_for: ClientFor
):
    client = client_for(lambda request: json_response(body, status))
    with pytest.raises(DataSourceError, match=match):
        nearest_groundwater(*KUTELA, client=client, now=NOW)


def test_server_errors_are_retried_then_raise(client_for: ClientFor, recorder: Recorder):
    client = client_for(lambda request: httpx.Response(503, text="busy"))
    with pytest.raises(DataSourceError, match="503"):
        nearest_groundwater(*KUTELA, client=client, now=NOW)
    assert len(recorder.requests) == 4
    assert recorder.sleeps == [0.5, 1.0, 2.0]


@pytest.mark.parametrize(
    ("args", "kwargs", "match"),
    [
        ((91.0, 81.0), {}, "coordinates"),
        (KUTELA, {"district_lgd": "378'"}, "district_lgd"),
        (KUTELA, {"max_km": 0}, "max_km"),
        (KUTELA, {"now": datetime(2026, 10, 9, 5, 0)}, "timezone-aware"),
    ],
)
def test_arguments_are_checked_before_any_request(
    args: tuple[float, float],
    kwargs: dict[str, Any],
    match: str,
    client_for: ClientFor,
    recorder: Recorder,
):
    kwargs = {"now": NOW, **kwargs}
    with pytest.raises(ValueError, match=match):
        nearest_groundwater(*args, client=client_for(lambda r: json_response({})), **kwargs)
    assert recorder.requests == []


def test_recent_slots_cover_seven_days_of_six_hourly_times():
    slots = recent_slots(datetime(2026, 10, 8, 23, 47, tzinfo=IST))
    assert slots[0] == "08-10-2026 18:00"
    assert slots[-1] == "01-10-2026 18:00"
    assert len(slots) == 29
    from_utc = recent_slots(datetime.fromisoformat("2026-10-08T23:47:00+00:00"))
    assert from_utc[0] == "09-10-2026 00:00"


# --- groundwater: parsing and summaries ------------------------------------------------------


def test_parse_drops_markers_and_malformed_rows():
    at = datetime(2026, 10, 6, 18, 0, tzinfo=IST)
    rows: list[Any] = [
        _row("A", BIRODA, at, "-8.3"),
        _row("A", BIRODA, at, "1.00"),
        _row("A", BIRODA, at, "0.00"),
        _row("A", BIRODA, at, "2.5"),
        _row("A", BIRODA, at, "-450"),
        _row("A", BIRODA, at, "nan"),
        {**_row("A", BIRODA, at, "-8.3"), "Data Acquisition Time": "2026-10-06 18:00"},
        {**_row("A", BIRODA, at, "-8.3"), "Latitude": "-"},
        {**_row("A", BIRODA, at, "-8.3"), "Station": " "},
        {**_row("A", BIRODA, at, "-8.3"), F_LEVEL: None},
        "not a row",
    ]
    readings = parse_telemetry(rows)
    assert [(r.station, r.level, r.at) for r in readings] == [("A", -8.3, at)]


@given(st.one_of(st.floats(allow_nan=True, allow_infinity=True).map(str), st.text(max_size=8)))
def test_parse_never_keeps_a_level_at_or_above_ground(level: str):
    row = _row("A", BIRODA, datetime(2026, 10, 6, 18, 0, tzinfo=IST), level)
    for reading in parse_telemetry([row]):
        assert -300.0 <= reading.level < 0


def test_summary_tracks_unchanged_run_and_monthly_means():
    end = datetime(2026, 4, 30, 18, 0, tzinfo=IST)
    rows = _series("A", BIRODA, end, 3, lambda i: "-20.0" if i < 5 else f"-{19 + i / 10:.1f}")
    future = _row("A", BIRODA, end + timedelta(days=1), "-1.0")
    summary = summarise_station(parse_telemetry([future, *rows]), as_of=end)

    assert summary is not None
    assert summary.latest_at == end and summary.depth_m == 20.0
    assert summary.unchanged_days == 1.0  # five equal readings span 24 hours
    assert summary.stuck is False
    assert list(summary.monthly_depth_m) == ["2026-04"]


def test_summary_of_nothing_is_none():
    assert summarise_station([], as_of=NOW) is None


# --- groundwater: snapshot -------------------------------------------------------------------


def test_snapshot_is_dated_and_drops_marker_only_stations():
    data = json.loads(SNAPSHOT_PATH.read_text("utf-8"))
    fetched = datetime.fromisoformat(data["fetched_at"])
    assert fetched.tzinfo is not None
    block = data["groundwater"]
    assert block["district_lgd"] == "378" and block["url"] == TELEMETRY_PAGE
    names = {s["station"] for s in block["stations"]}
    assert "Biroda_2" in names and "Kachandur" not in names
    biroda = next(s for s in block["stations"] if s["station"] == "Biroda_2")
    assert biroda["monthly_depth_m"]["2026-04"] == 22.01
    assert biroda["monthly_depth_m"]["2026-05"] == 20.27
    assert data["rainfall"]["district"] == "DURG" and data["rainfall"]["rows"]


def test_falls_back_to_the_snapshot_when_nwdp_times_out():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated NWDP timeout", request=request)

    later = datetime(2026, 10, 20, tzinfo=IST)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        reading = nearest_groundwater_or_snapshot(*KUTELA, client=client, now=later)

    assert reading is not None and reading.station == "Biroda_2"
    assert reading.source.source.endswith(", bundled snapshot")
    assert reading.source.freshness is Freshness.DAILY
    assert reading.stale is True
    snapshot_at = json.loads(SNAPSHOT_PATH.read_text("utf-8"))["fetched_at"]
    assert reading.source.fetched_at == datetime.fromisoformat(snapshot_at)
    assert reading.pre_monsoon_month == "2026-04" and reading.pre_monsoon_depth_m == 22.01


def test_snapshot_for_another_district_is_none():
    assert load_groundwater_snapshot(*KUTELA, now=NOW, district_lgd="999") is None


# --- rainfall --------------------------------------------------------------------------------


def test_rainfall_sums_the_last_seven_reported_days(
    load: Callable[[str], dict[str, Any]], client_for: ClientFor, recorder: Recorder
):
    payload = load("nwdp_rain_durg.json")

    summary = district_rainfall(client=client_for(lambda r: json_response(payload)), now=NOW)

    assert summary is not None
    assert (summary.district, summary.start, summary.end) == (
        "DURG",
        date(2026, 10, 2),
        date(2026, 10, 8),
    )
    assert (summary.actual_mm, summary.normal_mm, summary.departure_pct) == (4.4, 23.0, -81)
    assert summary.days_counted == 7 and len(summary.daily) == 7
    assert summary.latest == DistrictRainDay(date=date(2026, 10, 8), actual_mm=4.4, normal_mm=3.3)
    assert summary.stale is False
    assert summary.source.source == RAINFALL_SOURCE
    assert summary.source.freshness is Freshness.DAILY
    assert summary.source.observed_at == datetime(2026, 10, 8, 8, 30, tzinfo=IST)
    assert summary.source.url == RAINFALL_PAGE

    (request,) = recorder.requests
    assert request.url.params["resource_id"] == RAINFALL_RESOURCE
    assert _filters(request) == {"District": "DURG"}
    assert request.url.params["sort"] == "_id desc"
    assert request.url.params["fields"] == "_id,Date,Daily Actual,Daily Normal"


def test_rainfall_district_name_is_normalised(
    load: Callable[[str], dict[str, Any]], client_for: ClientFor, recorder: Recorder
):
    payload = load("nwdp_rain_durg.json")
    district_rainfall("  durg ", client=client_for(lambda r: json_response(payload)), now=NOW)
    assert _filters(recorder.requests[0]) == {"District": "DURG"}


def test_rainfall_is_stale_when_the_latest_day_is_old(
    load: Callable[[str], dict[str, Any]], client_for: ClientFor
):
    payload = load("nwdp_rain_durg.json")
    later = datetime(2026, 10, 12, 9, 0, tzinfo=IST)
    summary = district_rainfall(client=client_for(lambda r: json_response(payload)), now=later)
    assert summary is not None and summary.stale is True and summary.end == date(2026, 10, 8)


def test_rainfall_with_no_rows_is_none(client_for: ClientFor):
    fields = [{"id": f} for f in ("_id", "Date", "Daily Actual", "Daily Normal")]
    client = client_for(lambda r: json_response(_payload([], fields)))
    assert district_rainfall(client=client, now=NOW) is None


def test_rainfall_missing_field_raises(client_for: ClientFor):
    fields = [{"id": f} for f in ("_id", "Date", "Daily Actual")]
    client = client_for(lambda r: json_response(_payload([], fields)))
    with pytest.raises(DataSourceError, match="Daily Normal"):
        district_rainfall(client=client, now=NOW)


def test_parse_rainfall_skips_junk_and_keeps_the_newest_row_per_date():
    rows = [
        {"Date": "2026-10-08", "Daily Actual": "4.4", "Daily Normal": "3.3"},
        {"Date": "2026-10-08", "Daily Actual": "9.9", "Daily Normal": "3.3"},
        {"Date": "07-10-2026", "Daily Actual": "-", "Daily Normal": "3.8"},
        {"Date": "2026-10-06", "Daily Actual": "", "Daily Normal": "-1"},
        {"Date": "not a date", "Daily Actual": "1", "Daily Normal": "1"},
        "junk",
    ]
    assert parse_rainfall(rows) == [
        DistrictRainDay(date=date(2026, 10, 6)),
        DistrictRainDay(date=date(2026, 10, 7), normal_mm=3.8),
        DistrictRainDay(date=date(2026, 10, 8), actual_mm=4.4, normal_mm=3.3),
    ]


def test_summary_ignores_future_days_and_zero_normal_has_no_departure():
    rows = [
        DistrictRainDay(date=date(2026, 10, 8), actual_mm=2.0, normal_mm=0.0),
        DistrictRainDay(date=date(2026, 10, 10), actual_mm=50.0, normal_mm=1.0),
    ]
    summary = summarise_rainfall(rows, district="DURG", now=NOW, days=7, fetched_at=FETCHED)
    assert summary is not None
    assert (summary.end, summary.actual_mm, summary.departure_pct) == (date(2026, 10, 8), 2.0, None)


def test_summary_without_actual_values_is_none():
    rows = [DistrictRainDay(date=date(2026, 10, 8), normal_mm=3.3)]
    assert summarise_rainfall(rows, district="DURG", now=NOW, days=7, fetched_at=FETCHED) is None


@pytest.mark.parametrize(("district", "days"), [("DURG'", 7), ("", 7), ("DURG", 0), ("DURG", 32)])
def test_rainfall_arguments_are_checked(
    district: str, days: int, client_for: ClientFor, recorder: Recorder
):
    with pytest.raises(ValueError):
        district_rainfall(district, client=client_for(lambda r: json_response({})), days=days)
    assert recorder.requests == []


def test_rainfall_falls_back_to_the_snapshot():
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated refusal", request=request)

    with httpx.Client(transport=httpx.MockTransport(refused)) as client:
        summary = district_rainfall_or_snapshot(client=client, now=NOW)

    assert summary is not None
    assert summary.source.source == RAINFALL_SOURCE + ", bundled snapshot"
    assert summary.days_counted >= 1
    assert load_rainfall_snapshot("BEMETARA", now=NOW) is None
