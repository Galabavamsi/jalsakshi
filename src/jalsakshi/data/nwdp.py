"""Groundwater telemetry and district rainfall from the National Water Data Portal (NWDP).

NWDP (nwdp.nwic.gov.in) is a CKAN portal whose `datastore_search` action is a keyless GET.
Two resources are read (context only, never a decision input):

- **CGWB groundwater telemetry, Chhattisgarh 2026-30.** One row per station every 6 hours. The
  level is NEGATIVE metres below ground. Loggers write 1.00 / 0.00 as error markers, and some
  report positive levels for weeks, so only negative levels are kept. A level unchanged for more
  than 30 days is a stuck sensor and the station is skipped. Rows are stored station by station
  (each station is one block of `_id`s), so the newest `_id`s are not the newest readings. The
  fetcher therefore asks for every reading in the district's 6-hourly slots of the last 7 days
  (one request), then reads the history of the nearest candidates (one request each, at most 3).
- **IMD district daily rainfall** (one row per district per day, the 24 hours ending 08:30 IST).
  Only `Date`, `Daily Actual` and `Daily Normal` are used: the weekly and cumulative columns have
  typos and line breaks in their names, and inconsistent values.

Both have a bundled, dated snapshot (`snapshots/nwdp_durg.json`, made by
`scripts/snapshot_nwdp.py`) for when NWDP cannot be reached; its source reads "…, bundled
snapshot" and `fetched_at` is the snapshot date.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from jalsakshi.core.models import Freshness, SourceTag
from jalsakshi.data.http import (
    IST,
    DataSourceError,
    borrow_client,
    get_response,
    response_json,
    utc_now,
)
from jalsakshi.data.villages import haversine_km

logger = logging.getLogger(__name__)

API_URL: Final = "https://nwdp.nwic.gov.in/api/3/action/datastore_search"
TELEMETRY_RESOURCE: Final = "40c11a45-e4ca-46a6-9af7-497844bf5267"
TELEMETRY_PAGE: Final = (
    "https://nwdp.nwic.gov.in/dataset/3782ba15-9b12-46a8-ae44-410b1f84020e/resource/"
    + TELEMETRY_RESOURCE
)
RAINFALL_RESOURCE: Final = "8752174f-1d17-4aaf-8058-2eb396f50157"
RAINFALL_PAGE: Final = (
    "https://nwdp.nwic.gov.in/dataset/9380580f-9bf0-4708-9773-0cea3cbc595a/resource/"
    + RAINFALL_RESOURCE
)
GROUNDWATER_SOURCE: Final = (
    "CGWB telemetry via National Water Data Portal (nearest station, {km:.1f} km)"
)
RAINFALL_SOURCE: Final = (
    "IMD district rainfall via National Water Data Portal (district average, not your village)"
)
SNAPSHOT_LABEL: Final = ", bundled snapshot"
SNAPSHOT_PATH: Final = Path(__file__).parent / "snapshots" / "nwdp_durg.json"
DURG_LGD: Final = "378"
DURG: Final = "DURG"

F_ID: Final = "_id"
F_STATION: Final = "Station"
F_LAT: Final = "Latitude"
F_LON: Final = "Longitude"
F_DISTRICT_LGD: Final = "District LGD Code"
F_TIME: Final = "Data Acquisition Time"
F_LEVEL: Final = "Groundwater Level Telemetry 6 Hourly (meter)"
TELEMETRY_FIELDS: Final = (F_ID, F_STATION, F_LAT, F_LON, F_TIME, F_LEVEL)
F_DISTRICT: Final = "District"
F_DATE: Final = "Date"
F_ACTUAL: Final = "Daily Actual"
F_NORMAL: Final = "Daily Normal"
RAINFALL_FIELDS: Final = (F_ID, F_DATE, F_ACTUAL, F_NORMAL)

TIME_FORMAT: Final = "%d-%m-%Y %H:%M"
SLOT: Final = timedelta(hours=6)
PAGE_SIZE: Final = 1000
MAX_PAGES: Final = 3
HISTORY_ROWS: Final = 1500  # about 375 days of 6-hourly readings
MAX_CANDIDATES: Final = 3
MAX_KM: Final = 30.0
MAX_AGE: Final = timedelta(days=7)
STALE_AFTER: Final = timedelta(hours=48)
STUCK_AFTER: Final = timedelta(days=30)
MAX_DEPTH_M: Final = 300.0
MIN_MONTH_READINGS: Final = 4  # a monthly mean needs at least a day of readings
PRE_MONSOON_MONTHS: Final = (3, 4, 5, 6)
RAIN_DAYS: Final = 7
RAIN_ROWS: Final = 40
MAX_RAIN_DAYS: Final = 31
RAIN_STALE_DAYS: Final = 2
IMD_DAY_ENDS: Final = time(8, 30)

_LGD = re.compile(r"\d{1,6}")
_DISTRICT = re.compile(r"[A-Z][A-Z .&()-]{0,63}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True, slots=True)
class TelemetryReading:
    """One plausible telemetry row; `level` is as published (negative metres below ground)."""

    station: str
    lat: float
    lon: float
    at: datetime
    level: float


class StationSummary(BaseModel):
    """One station reduced to what the context needs (also the snapshot's row format).

    `depth_m` is the latest level as positive metres below ground, `unchanged_days` how long that
    exact value has repeated, and `monthly_depth_m` the mean depth per "YYYY-MM" (IST) for months
    with at least `MIN_MONTH_READINGS` readings.
    """

    model_config = ConfigDict(frozen=True)

    station: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    latest_at: datetime
    depth_m: float = Field(gt=0)
    unchanged_days: float = Field(ge=0)
    monthly_depth_m: dict[str, float] = Field(default_factory=dict)

    @property
    def stuck(self) -> bool:
        """True when the latest value has not changed for more than `STUCK_AFTER`."""
        return self.unchanged_days > STUCK_AFTER / timedelta(days=1)


class GroundwaterReading(BaseModel):
    """The nearest working CGWB telemetry well's latest level, with pre-monsoon context.

    `pre_monsoon_depth_m` is the deepest monthly mean of March to June of the reading's year (the
    pre-monsoon low) and `pre_monsoon_month` its "YYYY-MM"; `rise_since_pre_monsoon_m` is how much
    higher the water stands now (positive = recovered). `stale` is true when the reading is more
    than 48 hours old at `now`.
    """

    model_config = ConfigDict(frozen=True)

    station: str
    lat: float
    lon: float
    distance_km: float = Field(ge=0)
    depth_m_below_ground: float = Field(gt=0)
    observed_at: datetime
    stale: bool
    pre_monsoon_depth_m: float | None = None
    pre_monsoon_month: str | None = None
    rise_since_pre_monsoon_m: float | None = None
    source: SourceTag


class DistrictRainDay(BaseModel):
    """IMD rainfall for one district-day (None when the cell was blank or not a number)."""

    model_config = ConfigDict(frozen=True)

    date: date
    actual_mm: float | None = Field(default=None, ge=0)
    normal_mm: float | None = Field(default=None, ge=0)


class RainfallSummary(BaseModel):
    """District rainfall over the `days` days ending at the latest reported day, against normal.

    Sums cover only the days with both an actual and a normal value (`days_counted`).
    `departure_pct` is the IMD-style departure from normal, rounded to a whole percent (None
    when the normal is 0). `stale` is true when the latest day is more than 2 days before today.
    """

    model_config = ConfigDict(frozen=True)

    district: str
    start: date
    end: date
    days_counted: int = Field(ge=1)
    actual_mm: float = Field(ge=0)
    normal_mm: float = Field(ge=0)
    departure_pct: int | None
    latest: DistrictRainDay
    daily: list[DistrictRainDay]
    stale: bool
    source: SourceTag


# --- groundwater -----------------------------------------------------------------------------


def nearest_groundwater(
    lat: float,
    lon: float,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    district_lgd: str = DURG_LGD,
    max_km: float = MAX_KM,
) -> GroundwaterReading | None:
    """The nearest telemetry well within `max_km` with a good reading at most 7 days old.

    Returns None when no station qualifies. Raises `ValueError` for bad arguments and
    `DataSourceError` when NWDP fails or its response cannot be understood.
    """
    _check_point(lat, lon)
    _check_lgd(district_lgd)
    _check_km(max_km)
    now = _aware(now)
    with borrow_client(client) as http:
        recent = parse_telemetry(
            _fetch_records(http, _recent_params(district_lgd, now), PAGE_SIZE, MAX_PAGES)
        )
        for station in _candidates(recent, lat, lon, as_of=now, max_km=max_km)[:MAX_CANDIDATES]:
            result = _datastore(http, _history_params(district_lgd, station), TELEMETRY_FIELDS)
            history = [r for r in parse_telemetry(result["records"]) if r.station == station]
            summary = summarise_station(history, as_of=now)
            if summary is not None and _usable(summary, now):
                return _to_reading(summary, lat, lon, now=now, fetched_at=utc_now())
            logger.info("Skipping NWDP station %s: no recent reading or a stuck sensor", station)
    return None


def nearest_groundwater_or_snapshot(
    lat: float,
    lon: float,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    district_lgd: str = DURG_LGD,
    max_km: float = MAX_KM,
) -> GroundwaterReading | None:
    """Live NWDP groundwater, or the bundled snapshot when NWDP fails."""
    try:
        return nearest_groundwater(
            lat, lon, client=client, now=now, district_lgd=district_lgd, max_km=max_km
        )
    except DataSourceError as exc:
        logger.warning("NWDP groundwater unavailable, using bundled snapshot: %s", exc)
        return load_groundwater_snapshot(
            lat, lon, now=now, district_lgd=district_lgd, max_km=max_km
        )


def load_groundwater_snapshot(
    lat: float,
    lon: float,
    *,
    now: datetime | None = None,
    district_lgd: str = DURG_LGD,
    max_km: float = MAX_KM,
    path: Path = SNAPSHOT_PATH,
) -> GroundwaterReading | None:
    """The nearest usable station in the bundled snapshot, judged as of the snapshot date.

    `stale` is computed against the real `now`, so an old snapshot is always labelled stale.
    Returns None when the snapshot covers another district or no station qualifies.
    """
    _check_point(lat, lon)
    _check_lgd(district_lgd)
    _check_km(max_km)
    data = _snapshot(path)
    block = data.get("groundwater") or {}
    if block.get("district_lgd") != district_lgd:
        return None
    fetched_at = datetime.fromisoformat(data["fetched_at"])
    summaries = [StationSummary.model_validate(row) for row in block.get("stations", [])]
    best = pick_nearest(summaries, lat, lon, as_of=fetched_at, max_km=max_km)
    if best is None:
        return None
    return _to_reading(best, lat, lon, now=_aware(now), fetched_at=fetched_at, snapshot=True)


def fetch_station_summaries(
    district_lgd: str = DURG_LGD,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    page_size: int = 5000,
    max_pages: int = 10,
) -> list[StationSummary]:
    """Every station of a district from its whole telemetry series (for the bundled snapshot)."""
    _check_lgd(district_lgd)
    params = {
        "resource_id": TELEMETRY_RESOURCE,
        "filters": json.dumps({F_DISTRICT_LGD: district_lgd}),
        "fields": ",".join(TELEMETRY_FIELDS),
        "sort": f"{F_ID} desc",
    }
    with borrow_client(client) as http:
        rows = _fetch_records(http, params, page_size, max_pages)
    return summarise_stations(parse_telemetry(rows), as_of=_aware(now))


def parse_telemetry(records: Iterable[Any]) -> list[TelemetryReading]:
    """Telemetry rows with a plausible level; markers, positive and malformed rows are dropped."""
    readings: list[TelemetryReading] = []
    for row in records:
        reading = _telemetry_row(row) if isinstance(row, Mapping) else None
        if reading is not None:
            readings.append(reading)
    return readings


def summarise_station(
    readings: Iterable[TelemetryReading], *, as_of: datetime
) -> StationSummary | None:
    """Reduce one station's readings (those not after `as_of`) to a `StationSummary`."""
    rows = sorted((r for r in readings if r.at <= as_of), key=lambda r: r.at)
    if not rows:
        return None
    latest = rows[-1]
    since = latest.at
    for reading in reversed(rows):
        if reading.level != latest.level:
            break
        since = reading.at
    monthly: dict[str, list[float]] = defaultdict(list)
    for reading in rows:
        local = reading.at.astimezone(IST)
        monthly[f"{local.year:04d}-{local.month:02d}"].append(-reading.level)
    means = {
        month: round(math.fsum(depths) / len(depths), 2)
        for month, depths in sorted(monthly.items())
        if len(depths) >= MIN_MONTH_READINGS
    }
    return StationSummary(
        station=latest.station,
        lat=latest.lat,
        lon=latest.lon,
        latest_at=latest.at.astimezone(IST),
        depth_m=round(-latest.level, 3),
        unchanged_days=round((latest.at - since) / timedelta(days=1), 2),
        monthly_depth_m=means,
    )


def summarise_stations(
    readings: Iterable[TelemetryReading], *, as_of: datetime
) -> list[StationSummary]:
    """`summarise_station` for every station in `readings`, sorted by station name."""
    by_station: dict[str, list[TelemetryReading]] = defaultdict(list)
    for reading in readings:
        by_station[reading.station].append(reading)
    summaries = (summarise_station(rows, as_of=as_of) for _, rows in sorted(by_station.items()))
    return [s for s in summaries if s is not None]


def pick_nearest(
    summaries: Iterable[StationSummary],
    lat: float,
    lon: float,
    *,
    as_of: datetime,
    max_km: float = MAX_KM,
) -> StationSummary | None:
    """The nearest station within `max_km` with a reading at most 7 days old and no stuck sensor."""
    best: tuple[float, str, StationSummary] | None = None
    for summary in summaries:
        if not _usable(summary, as_of):
            continue
        distance = haversine_km(lat, lon, summary.lat, summary.lon)
        if distance <= max_km and (best is None or (distance, summary.station) < best[:2]):
            best = (distance, summary.station, summary)
    return best[2] if best else None


def _telemetry_row(row: Mapping[str, Any]) -> TelemetryReading | None:
    station = str(row.get(F_STATION) or "").strip()
    if not station:
        return None
    try:
        lat, lon = float(row[F_LAT]), float(row[F_LON])
        at = datetime.strptime(str(row[F_TIME]).strip(), TIME_FORMAT).replace(tzinfo=IST)
        level = float(row[F_LEVEL])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    if not math.isfinite(level) or level >= 0 or level < -MAX_DEPTH_M:
        return None  # 1.00 / 0.00 are logger error markers; positive levels are faults
    return TelemetryReading(station=station, lat=lat, lon=lon, at=at, level=level)


def _candidates(
    readings: Sequence[TelemetryReading],
    lat: float,
    lon: float,
    *,
    as_of: datetime,
    max_km: float,
) -> list[str]:
    """Stations with a reading in the last 7 days within `max_km`, nearest first."""
    latest: dict[str, TelemetryReading] = {}
    for reading in readings:
        if not timedelta(0) <= as_of - reading.at <= MAX_AGE:
            continue
        current = latest.get(reading.station)
        if current is None or reading.at > current.at:
            latest[reading.station] = reading
    ranked = sorted((haversine_km(lat, lon, r.lat, r.lon), name) for name, r in latest.items())
    return [name for distance, name in ranked if distance <= max_km]


def _usable(summary: StationSummary, as_of: datetime) -> bool:
    return timedelta(0) <= as_of - summary.latest_at <= MAX_AGE and not summary.stuck


def _to_reading(
    summary: StationSummary,
    lat: float,
    lon: float,
    *,
    now: datetime,
    fetched_at: datetime,
    snapshot: bool = False,
) -> GroundwaterReading:
    distance = round(haversine_km(lat, lon, summary.lat, summary.lon), 2)
    stale = now - summary.latest_at > STALE_AFTER
    month, low = _pre_monsoon(summary)
    label = GROUNDWATER_SOURCE.format(km=distance) + (SNAPSHOT_LABEL if snapshot else "")
    source = SourceTag(
        source=label,
        observed_at=summary.latest_at,
        fetched_at=fetched_at,
        freshness=Freshness.LIVE if not (stale or snapshot) else Freshness.DAILY,
        url=TELEMETRY_PAGE,
    )
    return GroundwaterReading(
        station=summary.station,
        lat=summary.lat,
        lon=summary.lon,
        distance_km=distance,
        depth_m_below_ground=summary.depth_m,
        observed_at=summary.latest_at,
        stale=stale,
        pre_monsoon_depth_m=low,
        pre_monsoon_month=month,
        rise_since_pre_monsoon_m=round(low - summary.depth_m, 2) if low is not None else None,
        source=source,
    )


def _pre_monsoon(summary: StationSummary) -> tuple[str | None, float | None]:
    """The deepest March-June monthly mean of the reading's year, if any month qualified."""
    year = summary.latest_at.astimezone(IST).year
    months = [f"{year:04d}-{m:02d}" for m in PRE_MONSOON_MONTHS]
    present = [(m, summary.monthly_depth_m[m]) for m in months if m in summary.monthly_depth_m]
    if not present:
        return None, None
    return max(present, key=lambda item: item[1])


def _recent_params(district_lgd: str, now: datetime) -> dict[str, str]:
    """Every reading of the district in the 6-hourly slots of the last 7 days."""
    return {
        "resource_id": TELEMETRY_RESOURCE,
        "filters": json.dumps({F_DISTRICT_LGD: district_lgd, F_TIME: recent_slots(now)}),
        "fields": ",".join(TELEMETRY_FIELDS),
        "sort": f"{F_ID} desc",
    }


def _history_params(district_lgd: str, station: str) -> dict[str, str | int]:
    """The newest `HISTORY_ROWS` rows of one station (its rows are stored in time order)."""
    return {
        "resource_id": TELEMETRY_RESOURCE,
        "filters": json.dumps({F_DISTRICT_LGD: district_lgd, F_STATION: station}),
        "fields": ",".join(TELEMETRY_FIELDS),
        "sort": f"{F_ID} desc",
        "limit": HISTORY_ROWS,
    }


def recent_slots(now: datetime) -> list[str]:
    """The 6-hourly acquisition times (IST, NWDP text format) from now back 7 days, newest first."""
    local = now.astimezone(IST)
    start = local.replace(hour=local.hour // 6 * 6, minute=0, second=0, microsecond=0)
    count = int(MAX_AGE / SLOT) + 1
    return [(start - i * SLOT).strftime(TIME_FORMAT) for i in range(count)]


# --- rainfall --------------------------------------------------------------------------------


def district_rainfall(
    district: str = DURG,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    days: int = RAIN_DAYS,
) -> RainfallSummary | None:
    """IMD rainfall for a district (NWDP spelling, e.g. "DURG") over the latest `days` days.

    Returns None when NWDP has no rows for the district. Raises `ValueError` for bad arguments and
    `DataSourceError` when NWDP fails or its response cannot be understood.
    """
    name = _check_district(district)
    _check_days(days)
    now = _aware(now)
    with borrow_client(client) as http:
        rows = fetch_rainfall_rows(name, client=http)
    return summarise_rainfall(
        parse_rainfall(rows), district=name, now=now, days=days, fetched_at=utc_now()
    )


def district_rainfall_or_snapshot(
    district: str = DURG,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    days: int = RAIN_DAYS,
) -> RainfallSummary | None:
    """Live NWDP rainfall, or the bundled snapshot when NWDP fails."""
    try:
        return district_rainfall(district, client=client, now=now, days=days)
    except DataSourceError as exc:
        logger.warning("NWDP rainfall unavailable, using bundled snapshot: %s", exc)
        return load_rainfall_snapshot(district, now=now, days=days)


def load_rainfall_snapshot(
    district: str = DURG,
    *,
    now: datetime | None = None,
    days: int = RAIN_DAYS,
    path: Path = SNAPSHOT_PATH,
) -> RainfallSummary | None:
    """Rainfall from the bundled snapshot (None when it covers another district)."""
    name = _check_district(district)
    _check_days(days)
    data = _snapshot(path)
    block = data.get("rainfall") or {}
    if block.get("district") != name:
        return None
    return summarise_rainfall(
        parse_rainfall(block.get("rows", [])),
        district=name,
        now=_aware(now),
        days=days,
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        snapshot=True,
    )


def fetch_rainfall_rows(
    district: str = DURG, *, client: httpx.Client | None = None, limit: int = RAIN_ROWS
) -> list[Mapping[str, Any]]:
    """The newest `limit` raw IMD rows for a district (`_id`, Date, Daily Actual, Daily Normal)."""
    name = _check_district(district)
    params: dict[str, str | int] = {
        "resource_id": RAINFALL_RESOURCE,
        "filters": json.dumps({F_DISTRICT: name}),
        "fields": ",".join(RAINFALL_FIELDS),
        "sort": f"{F_ID} desc",
        "limit": limit,
    }
    with borrow_client(client) as http:
        result = _datastore(http, params, RAINFALL_FIELDS)
    return [row for row in result["records"] if isinstance(row, Mapping)]


def parse_rainfall(records: Iterable[Any]) -> list[DistrictRainDay]:
    """One `DistrictRainDay` per date, oldest first; the first row seen for a date wins."""
    days: dict[date, DistrictRainDay] = {}
    for row in records:
        if not isinstance(row, Mapping):
            continue
        day = _rain_date(row.get(F_DATE))
        if day is None or day in days:
            continue
        days[day] = DistrictRainDay(
            date=day, actual_mm=_mm(row.get(F_ACTUAL)), normal_mm=_mm(row.get(F_NORMAL))
        )
    return [days[d] for d in sorted(days)]


def summarise_rainfall(
    rows: Sequence[DistrictRainDay],
    *,
    district: str,
    now: datetime,
    days: int,
    fetched_at: datetime,
    snapshot: bool = False,
) -> RainfallSummary | None:
    """Sum the `days` days ending at the latest day with an actual value (not after today, IST)."""
    today = now.astimezone(IST).date()
    reported = [r for r in rows if r.date <= today and r.actual_mm is not None]
    if not reported:
        return None
    end = max(r.date for r in reported)
    start = end - timedelta(days=days - 1)
    window = [r for r in rows if start <= r.date <= end]
    both = [r for r in window if r.actual_mm is not None and r.normal_mm is not None]
    if not both:
        return None
    actual = round(math.fsum(r.actual_mm or 0.0 for r in both), 1)
    normal = round(math.fsum(r.normal_mm or 0.0 for r in both), 1)
    departure = round((actual - normal) / normal * 100) if normal > 0 else None
    source = SourceTag(
        source=RAINFALL_SOURCE + (SNAPSHOT_LABEL if snapshot else ""),
        observed_at=datetime.combine(end, IMD_DAY_ENDS, tzinfo=IST),
        fetched_at=fetched_at,
        freshness=Freshness.DAILY,
        url=RAINFALL_PAGE,
    )
    return RainfallSummary(
        district=district,
        start=start,
        end=end,
        days_counted=len(both),
        actual_mm=actual,
        normal_mm=normal,
        departure_pct=departure,
        latest=next(r for r in window if r.date == end),
        daily=window,
        stale=(today - end).days > RAIN_STALE_DAYS,
        source=source,
    )


def _rain_date(value: Any) -> date | None:
    text = str(value or "").strip()
    try:
        if _ISO_DATE.fullmatch(text):
            return date.fromisoformat(text)
        return datetime.strptime(text, "%d-%m-%Y").date()
    except ValueError:
        return None


def _mm(value: Any) -> float | None:
    """A non-negative finite millimetre value, or None for blanks, dashes and junk."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


# --- shared ----------------------------------------------------------------------------------


def _fetch_records(
    http: httpx.Client,
    params: Mapping[str, Any],
    page_size: int,
    max_pages: int,
    required: Sequence[str] = TELEMETRY_FIELDS,
) -> list[Any]:
    """Page through `datastore_search` (at most `max_pages` pages of `page_size` rows)."""
    records: list[Any] = []
    for page in range(max_pages):
        paging = {"limit": page_size, "offset": page * page_size}
        result = _datastore(http, {**params, **paging}, required)
        batch = result["records"]
        records.extend(batch)
        total = result.get("total")
        if len(batch) < page_size or (isinstance(total, int) and len(records) >= total):
            return records
    logger.warning("NWDP query stopped after %d pages (%d rows)", max_pages, len(records))
    return records


def _datastore(
    http: httpx.Client, params: Mapping[str, Any], required: Sequence[str]
) -> Mapping[str, Any]:
    """One `datastore_search` call; CKAN reports failures as `success: false`."""
    payload = response_json(get_response(http, API_URL, params=params))
    if not isinstance(payload, dict):
        raise DataSourceError("NWDP response is not a JSON object")
    if payload.get("success") is not True:
        raise DataSourceError(f"NWDP datastore_search failed: {payload.get('error')}")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("records"), list):
        raise DataSourceError("NWDP response has no 'records' list")
    fields = result.get("fields") if isinstance(result.get("fields"), list) else []
    names = {f.get("id") for f in fields if isinstance(f, dict)}
    missing = [name for name in required if name not in names]
    if missing:
        raise DataSourceError(f"NWDP resource is missing fields: {', '.join(missing)}")
    return result


@lru_cache(maxsize=4)
def _snapshot(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict) or "fetched_at" not in data:
        raise ValueError(f"{path.name} is not an NWDP snapshot")
    return data


def _aware(now: datetime | None) -> datetime:
    if now is None:
        return utc_now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


def _check_point(lat: float, lon: float) -> None:
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError(f"coordinates out of range: lat={lat}, lon={lon}")


def _check_lgd(code: str) -> None:
    if not _LGD.fullmatch(code):
        raise ValueError(f"district_lgd must be an LGD code of digits, got {code!r}")


def _check_km(km: float) -> None:
    if not km > 0:
        raise ValueError(f"max_km must be positive, got {km}")


def _check_days(days: int) -> None:
    if not 1 <= days <= MAX_RAIN_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_RAIN_DAYS}, got {days}")


def _check_district(district: str) -> str:
    name = " ".join(district.split()).upper()
    if not _DISTRICT.fullmatch(name):
        raise ValueError(f"district must be a district name, got {district!r}")
    return name
