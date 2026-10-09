"""What the government's own dashboards say about each village (bundled, dated snapshot).

Read by hand from the public JJM IMIS and WQMIS dashboards on 9 Oct 2026 (they have no API and
need a browser session) and stored in `snapshots/jjm_official_durg.json`. These are the state's
claims, shown next to what households report; they are never a decision input. The snapshot holds
no person names or phone numbers.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from jalsakshi.core.models import Freshness, SourceTag
from jalsakshi.data.http import IST

SNAPSHOT_PATH: Final = Path(__file__).parent / "snapshots" / "jjm_official_durg.json"

HgjStatus = Literal["IN_PROGRESS", "REPORTED", "CERTIFIED"]


class Scheme(BaseModel):
    """A water-supply scheme serving the village, as listed in IMIS (amounts in Rs lakh)."""

    model_config = ConfigDict(frozen=True)

    scheme_id: str
    name: str | None = None
    kind: str | None = None
    sanction_year: str | None = None
    estimated_lakh: float | None = Field(default=None, ge=0)
    spent_lakh: float | None = Field(default=None, ge=0)
    status: str | None = None
    functional_status: str | None = None


class OfficialWaterQuality(BaseModel):
    """Water-quality testing on record in WQMIS (values are ranges as published)."""

    model_config = ConfigDict(frozen=True)

    last_household_test: date | None = None
    household_test_dates: list[date] = Field(default_factory=list)
    last_household_values_date: date | None = None
    last_household_values: dict[str, str] = Field(default_factory=dict)
    samples_summary: str = ""
    contamination_flags: list[str] = Field(default_factory=list)
    ftk_this_fy: str | None = None
    ftk_samples_this_fy: int | None = Field(default=None, ge=0)
    ftk_samples_last_fy: int | None = Field(default=None, ge=0)
    ftk_parameters: list[str] = Field(default_factory=list)
    ftk_note: str | None = None
    women_trained_ftk: int | None = Field(default=None, ge=0)


class OfficialRecord(BaseModel):
    """One village's official JJM record: connections, Har Ghar Jal status, schemes, testing.

    `population` and `wq` are None where the dashboard was not read for that village.
    """

    model_config = ConfigDict(frozen=True)

    village_lgd: str
    imis_village_id: str
    name: str
    gram_panchayat: str | None = None
    gp_imis_id: str | None = None
    households: int = Field(ge=0)
    tap_connections: int = Field(ge=0)
    population: int | None = Field(default=None, ge=0)
    population_sc: int | None = Field(default=None, ge=0)
    population_st: int | None = Field(default=None, ge=0)
    hgj_status: HgjStatus
    schemes: list[Scheme] = Field(default_factory=list)
    source_type: str | None = None
    wq: OfficialWaterQuality | None = None
    source: SourceTag


class OfficialDistrict(BaseModel):
    """District Har Ghar Jal totals from the IMIS report named in `report` (e.g. J8)."""

    model_config = ConfigDict(frozen=True)

    district: str
    state: str
    report: str
    villages: int = Field(ge=0)
    hgj_reported: int = Field(ge=0)
    hgj_certified: int = Field(ge=0)
    source: SourceTag


def load_official(lgd_code: str, *, path: Path = SNAPSHOT_PATH) -> OfficialRecord | None:
    """The official record for a village by LGD code, or None when the snapshot has none."""
    return _records(path).get(lgd_code.strip())


def load_official_district(*, path: Path = SNAPSHOT_PATH) -> OfficialDistrict | None:
    """The district totals stored with the snapshot, if any."""
    data = _snapshot(path)
    block = data.get("district")
    if not isinstance(block, dict):
        return None
    source = _source(data, observed_at=_as_on(block.get("as_on")))
    return OfficialDistrict.model_validate(
        {k: v for k, v in block.items() if k != "as_on"} | {"source": source}
    )


def official_age_note(record: OfficialRecord, now: datetime) -> str:
    """One line on how old the last official household tap test is, for the console and brief.

    Example: "Last official household tap test: 17 Aug 2023 (3 years ago)".
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    tested = record.wq.last_household_test if record.wq else None
    if tested is None:
        return "No official household tap test on record"
    age = _ago(tested, now.astimezone(IST).date())
    return f"Last official household tap test: {_day(tested)} ({age})"


def _ago(then: date, today: date) -> str:
    """Whole years, else whole months, else days between two dates, in plain English."""
    if then > today:
        return "in the future"
    months = (today.year - then.year) * 12 + today.month - then.month - (today.day < then.day)
    if months >= 12:
        return _plural(months // 12, "year")
    if months >= 1:
        return _plural(months, "month")
    days = (today - then).days
    return "today" if days == 0 else _plural(days, "day")


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit} ago" if n == 1 else f"{n} {unit}s ago"


def _day(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


@lru_cache(maxsize=4)
def _records(path: Path) -> dict[str, OfficialRecord]:
    data = _snapshot(path)
    source = _source(data)
    records = (
        OfficialRecord.model_validate({**row, "source": source}) for row in data.get("villages", [])
    )
    return {record.village_lgd: record for record in records}


@lru_cache(maxsize=4)
def _snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict) or "fetched_at" not in data:
        raise ValueError(f"{path.name} is not an official-record snapshot")
    return data


def _source(data: dict[str, Any], observed_at: datetime | None = None) -> SourceTag:
    return SourceTag(
        source=data["source"],
        observed_at=observed_at,
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        freshness=Freshness.DAILY,
        url=data.get("url"),
    )


def _as_on(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.combine(date.fromisoformat(str(value)), datetime.min.time(), tzinfo=IST)
