"""Public context per village (groundwater, recent rain, the state's Har Ghar Jal claim).

The government sources are slow (seconds to tens of seconds per query), so a scheduled Lambda
(``refresh``) writes ``context/{village_id}.json`` to the evidence bucket and the console API
only reads that file. Every value keeps the ``SourceTag`` its fetcher attached.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Final

import httpx
from botocore.exceptions import ClientError

from jalsakshi.core.models import Village
from jalsakshi.data import (
    BlockGroundwater,
    DataSourceError,
    RainSummary,
    RetryPolicy,
    StateHGJ,
    fetch_block_groundwater,
    fetch_state_hgj,
    find_block,
    make_client,
    rain_last_days,
)
from jalsakshi.handlers import config
from jalsakshi.handlers.common import dumps, entrypoint, logger

CONTEXT_PREFIX: Final = "context/"
STATE_NAME: Final = "Chhattisgarh"
STATE_CODE: Final = "CG"
RAIN_DAYS: Final = 7
FETCH_TIMEOUT_S: Final = 30.0
FETCH_RETRY: Final = RetryPolicy(retries=1)  # bounds a slow source to about a minute

# District headquarters, used as the rain point for every village in the district.
DISTRICT_POINTS: Final[dict[str, tuple[float, float]]] = {
    "durg": (21.19, 81.28),
    "bemetara": (21.71, 81.53),
    "raipur": (21.25, 81.63),
    "balod": (20.73, 81.20),
    "rajnandgaon": (21.10, 81.03),
}
# Devanagari names used in the console, mapped to the English names the sources publish.
ALIASES: Final[dict[str, str]] = {
    "दुर्ग": "Durg",
    "बेमेतरा": "Bemetara",
    "रायपुर": "Raipur",
    "बालोद": "Balod",
    "राजनांदगांव": "Rajnandgaon",
    "पाटन": "Patan",
    "धमधा": "Dhamdha",
    "बेरला": "Berla",
    "साजा": "Saja",
}


def context_key(village_id: str) -> str:
    """S3 key of a village's cached context."""
    return f"{CONTEXT_PREFIX}{village_id}.json"


def english(name: str) -> str:
    """The English spelling the data sources use for a district or block name."""
    return ALIASES.get(name.strip(), name.strip())


def load_context(village_id: str) -> dict[str, Any]:
    """The cached context for a village, or {} when none was written yet (or S3 fails)."""
    bucket = config.settings().evidence_bucket
    if not bucket:
        return {}
    try:
        obj = config.client("s3").get_object(Bucket=bucket, Key=context_key(village_id))
        data = json.loads(obj["Body"].read())
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code")
        if code not in {"NoSuchKey", "404", "AccessDenied"}:
            logger.warning("context read failed", extra={"village_id": village_id, "code": code})
        return {}
    except (ValueError, OSError):
        logger.warning("context file unreadable", extra={"village_id": village_id})
        return {}
    return data if isinstance(data, dict) else {}


def build_context(
    village: Village,
    blocks: Sequence[BlockGroundwater] | None,
    state: StateHGJ | None,
    rain: RainSummary | None,
) -> dict[str, Any]:
    """The §13 ``context`` object for one village; a missing source becomes null."""
    groundwater = None
    if blocks:
        block = find_block(blocks, english(village.block), district=english(village.district))
        if block is not None:
            groundwater = {
                "stage_pct": block.stage_pct,
                "category": block.category,
                "source": block.source.model_dump(mode="json"),
            }
    return {
        "groundwater": groundwater,
        "rain_7d_mm": (
            {"value": rain.total_mm, "source": rain.source.model_dump(mode="json")}
            if rain
            else None
        ),
        "state_hgj": (
            state.model_dump(mode="json", include={"villages", "reported", "certified", "source"})
            if state
            else None
        ),
    }


def rain_point(village: Village) -> tuple[float, float] | None:
    """Coordinates used for the village's rain total (its district HQ), if known."""
    return DISTRICT_POINTS.get(english(village.district).lower())


@entrypoint
def refresh(event: Any, context: Any) -> dict[str, Any]:
    """Scheduled: fetch every source once and rewrite each village's context file."""
    cfg = config.settings()
    if not cfg.evidence_bucket:
        raise config.ConfigError("JALSAKSHI_EVIDENCE_BUCKET is not set")
    villages = config.repository().list_villages()
    with make_client(timeout=FETCH_TIMEOUT_S, retry=FETCH_RETRY) as http:
        state = _attempt("imis", lambda: fetch_state_hgj(STATE_NAME, client=http))
        blocks = _attempt("cgwb", lambda: fetch_block_groundwater(STATE_CODE, client=http))
        written = [_write(cfg.evidence_bucket, v, blocks, state, http) for v in villages]
    return {"villages": len(written), "state_hgj": state is not None, "groundwater": bool(blocks)}


def _write(
    bucket: str,
    village: Village,
    blocks: Sequence[BlockGroundwater] | None,
    state: StateHGJ | None,
    http: httpx.Client,
) -> str:
    point = rain_point(village)
    rain = None
    if point is not None:
        rain = _attempt("open-meteo", lambda: rain_last_days(*point, RAIN_DAYS, client=http))
    body = dumps(build_context(village, blocks, state, rain))
    config.client("s3").put_object(
        Bucket=bucket,
        Key=context_key(village.id),
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    return village.id


def _attempt[T](source: str, fetch: Callable[[], T]) -> T | None:
    """Run one fetch; a source that fails is left out (the console shows it as missing)."""
    try:
        return fetch()
    except (DataSourceError, httpx.HTTPError, ValueError) as exc:
        logger.warning("context source failed", extra={"source": source, "error": str(exc)[:200]})
        return None
