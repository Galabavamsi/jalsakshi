"""Refresh the bundled CGWB 2025 block snapshot used when India-WRIS is unreachable from AWS.

Usage:  uv run python scripts/snapshot_cgwb.py [--state CG]

The assessment is annual, so a dated snapshot is honest; the UI labels it as such.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jalsakshi.data.cgwb import SNAPSHOT_DIR, fetch_block_groundwater


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default="CG")
    args = parser.parse_args(argv)

    blocks = fetch_block_groundwater(args.state)
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "url": blocks[0].source.url if blocks else None,
        "blocks": [
            {
                "block": b.block,
                "district": b.district,
                "class": b.category,
                "sgw_dev_pe": b.stage_pct,
            }
            for b in blocks
        ],
    }
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"cgwb_2025_{args.state}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(blocks)} blocks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
