"""Refresh the bundled NWDP snapshot (groundwater telemetry + IMD rainfall) for one district.

Usage:  uv run python scripts/snapshot_nwdp.py [--district-lgd 378] [--district DURG]

The snapshot is the fallback when NWDP is unreachable. Its source reads "…, bundled snapshot",
`fetched_at` is the snapshot time and every reading keeps its own observation time, so the UI
labels it as old data rather than passing it off as current.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jalsakshi.data.http import make_client
from jalsakshi.data.nwdp import (
    F_ACTUAL,
    F_DATE,
    F_NORMAL,
    RAINFALL_PAGE,
    RAINFALL_RESOURCE,
    SNAPSHOT_PATH,
    TELEMETRY_PAGE,
    TELEMETRY_RESOURCE,
    fetch_rainfall_rows,
    fetch_station_summaries,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--district-lgd", default="378", help="LGD code for groundwater")
    parser.add_argument("--district", default="DURG", help="IMD district name for rainfall")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    with make_client(timeout=120.0) as http:
        stations = fetch_station_summaries(args.district_lgd, client=http, now=now)
        rain_rows = fetch_rainfall_rows(args.district, client=http)
    payload = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "groundwater": {
            "resource_id": TELEMETRY_RESOURCE,
            "url": TELEMETRY_PAGE,
            "district_lgd": args.district_lgd,
            "stations": [s.model_dump(mode="json") for s in stations],
        },
        "rainfall": {
            "resource_id": RAINFALL_RESOURCE,
            "url": RAINFALL_PAGE,
            "district": args.district.upper(),
            "rows": [
                {F_DATE: row.get(F_DATE), F_ACTUAL: row.get(F_ACTUAL), F_NORMAL: row.get(F_NORMAL)}
                for row in rain_rows
            ],
        },
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH} ({len(stations)} stations, {len(rain_rows)} rainfall days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
