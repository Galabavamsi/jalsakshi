"""The real village master for Durg block (Kutelabhatha and its neighbours), from bundled JSON.

Codes come from the Local Government Directory (LGD) and the Census 2011 District Census
Handbook, and locations from OpenStreetMap or GeoNames; every record names its sources
(`villages/durg_block.json`). Villages without a known location get `location=None`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from jalsakshi.core.models import Freshness, GeoPoint, SourceTag, Village

VILLAGES_DIR: Final = Path(__file__).parent / "villages"
DURG_BLOCK_FILE: Final = VILLAGES_DIR / "durg_block.json"
CHECKIN_LOCAL_TIME: Final = "19:00"
QUORUM: Final = 2
EARTH_RADIUS_KM: Final = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres (mean Earth radius)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def village_id(lgd_code: str) -> str:
    """Our id for a village: its LGD code with a prefix (`lgd-442569`)."""
    return f"lgd-{lgd_code}"


def load_villages(path: Path = DURG_BLOCK_FILE) -> list[Village]:
    """Every village in the bundled master file, as `Village` records (file order)."""
    return [village_from_record(row) for row in _records(path)]


def village_from_record(row: Mapping[str, Any]) -> Village:
    """Build a `Village` from one master record (id `lgd-{code}`, check-in 19:00, quorum 2)."""
    location = row.get("location")
    census_source = SourceTag(
        source=row["census_source"],
        observed_at=datetime.fromisoformat(row["census_observed_at"]),
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        freshness=Freshness.ANNUAL,
    )
    return Village(
        id=village_id(row["lgd_code"]),
        name=row["name"],
        name_hi=row.get("name_hi"),
        block=row["block"],
        district=row["district"],
        state=row.get("state"),
        lgd_code=row["lgd_code"],
        census_code=row.get("census_code"),
        gram_panchayat=row.get("gram_panchayat"),
        gp_lgd_code=row.get("gp_lgd_code"),
        census_households=row.get("census_households"),
        census_population=row.get("census_population"),
        census_source=census_source,
        location=GeoPoint(**location) if location else None,
        inbound=bool(row.get("inbound", False)),
        imis_village_code=row.get("imis_village_code"),
        checkin_local_time=CHECKIN_LOCAL_TIME,
        quorum=QUORUM,
    )


def nearby(village: Village, villages: Iterable[Village], km: float) -> list[Village]:
    """Other villages within `km` of `village`, nearest first (villages without a location skip)."""
    if km < 0:
        raise ValueError(f"km must not be negative, got {km}")
    if village.location is None:
        return []
    here = village.location
    hits: list[tuple[float, Village]] = []
    for other in villages:
        if other.id == village.id or other.location is None:
            continue
        distance = haversine_km(here.lat, here.lon, other.location.lat, other.location.lon)
        if distance <= km:
            hits.append((distance, other))
    hits.sort(key=lambda hit: (hit[0], hit[1].id))
    return [other for _, other in hits]


@lru_cache(maxsize=4)
def _records(path: Path) -> tuple[Mapping[str, Any], ...]:
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must hold a JSON list of village records")
    return tuple(data)
