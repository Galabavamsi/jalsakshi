"""CGWB Dynamic Ground Water Resources Assessment 2025, block level, from India-WRIS ArcGIS.

Layer 8 of `NWIC/GWR2025_CGWB` categorises every block (Safe, Semi Critical, Critical,
Over Exploited, Salinity, Not Accessed) with its stage of groundwater extraction in percent.
The assessment is annual, so results are tagged `Freshness.ANNUAL`.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from jalsakshi.core.models import Freshness, SourceTag
from jalsakshi.data.http import (
    DataSourceError,
    borrow_client,
    get_response,
    response_json,
    utc_now,
)

logger = logging.getLogger(__name__)

QUERY_URL = "https://arc.indiawris.gov.in/server/rest/services/NWIC/GWR2025_CGWB/MapServer/8/query"
SOURCE_NAME = "CGWB Ground Water Resource Assessment 2025 (India-WRIS)"
OUT_FIELDS = "block,district,class,sgw_dev_pe"
PAGE_SIZE = 1000
MAX_PAGES = 20
FUZZY_CUTOFF = 0.8
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

_STATE_CODE = re.compile(r"[A-Z]{2}")
_PARENTHETICAL = re.compile(r"\(([^)]*)\)")
_NON_WORD = re.compile(r"[^\w\s]")


class BlockGroundwater(BaseModel):
    """One block's groundwater category and stage of extraction (percent of recharge used)."""

    model_config = ConfigDict(frozen=True)

    block: str
    district: str
    category: str
    stage_pct: float | None
    source: SourceTag


def fetch_block_groundwater(
    state_code: str = "CG",
    *,
    client: httpx.Client | None = None,
    page_size: int = PAGE_SIZE,
) -> list[BlockGroundwater]:
    """Fetch every block of a state (two-letter India-WRIS code, e.g. "CG") from layer 8.

    Raises `ValueError` for a malformed state code or page size, and `DataSourceError` if the
    service fails.
    """
    if page_size < 1:
        raise ValueError(f"page_size must be positive, got {page_size}")
    params = _query_params(state_code)
    with borrow_client(client) as http:
        features = _fetch_all_features(http, params, page_size)
    source = SourceTag(
        source=SOURCE_NAME,
        url=str(httpx.URL(QUERY_URL, params=params)),
        fetched_at=utc_now(),
        freshness=Freshness.ANNUAL,
    )
    return parse_blocks(features, source)


def load_snapshot(state_code: str = "CG") -> list[BlockGroundwater]:
    """The bundled copy of the annual assessment (see scripts/snapshot_cgwb.py).

    India-WRIS often times out from cloud IP ranges; the assessment is annual, so a dated snapshot
    is an honest stand-in. The source name says "bundled snapshot" and `fetched_at` is its date.
    """
    _query_params(state_code)  # same validation as the live path
    data = json.loads((SNAPSHOT_DIR / f"cgwb_2025_{state_code}.json").read_text("utf-8"))
    source = SourceTag(
        source=f"{SOURCE_NAME}, bundled snapshot",
        url=data.get("url"),
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        freshness=Freshness.ANNUAL,
    )
    return parse_blocks(({"attributes": row} for row in data["blocks"]), source)


def fetch_block_groundwater_or_snapshot(
    state_code: str = "CG", *, client: httpx.Client | None = None
) -> list[BlockGroundwater]:
    """Live India-WRIS data, or the bundled snapshot when the service fails."""
    try:
        return fetch_block_groundwater(state_code, client=client)
    except DataSourceError as exc:
        logger.warning("India-WRIS unavailable, using bundled snapshot: %s", exc)
        return load_snapshot(state_code)


def parse_blocks(
    features: Iterable[Mapping[str, Any]], source: SourceTag
) -> list[BlockGroundwater]:
    """Turn ArcGIS features into `BlockGroundwater` rows, skipping rows without a block name."""
    blocks: list[BlockGroundwater] = []
    for feature in features:
        block = _block_from_attributes(feature.get("attributes") or {}, source)
        if block is not None:
            blocks.append(block)
    return blocks


def find_block(
    blocks: Sequence[BlockGroundwater],
    name: str,
    *,
    district: str | None = None,
    cutoff: float = FUZZY_CUTOFF,
) -> BlockGroundwater | None:
    """Find a block by name, case-insensitively and tolerating small spelling differences.

    Matching tries, in order: the exact normalised name, the name without a bracketed qualifier
    ("Janjgir (Nawagarh)" -> "Janjgir"), the bracketed alias itself, then a fuzzy match. Returns
    None when nothing matches or when the name is ambiguous across districts (pass `district`).
    """
    target = _normalise(name)
    if not target:
        return None
    pool = [b for b in blocks if district is None or _normalise(b.district) == _normalise(district)]
    keys: tuple[Callable[[str], set[str]], ...] = (_exact_keys, _bare_keys, _alias_keys)
    for key in keys:
        hits = [b for b in pool if target in key(b.block)]
        if hits:
            return _unique(hits)
    return _fuzzy(pool, target, cutoff)


def _query_params(state_code: str) -> dict[str, str]:
    """ArcGIS query parameters; the state code is validated because it is spliced into SQL."""
    if not _STATE_CODE.fullmatch(state_code):
        raise ValueError(f"state_code must be two capital letters, got {state_code!r}")
    return {
        "where": f"state='{state_code}'",
        "outFields": OUT_FIELDS,
        "orderByFields": "district,block",
        "returnGeometry": "false",
        "f": "json",
    }


def _fetch_all_features(
    http: httpx.Client, params: Mapping[str, str], page_size: int
) -> list[Mapping[str, Any]]:
    """Follow ArcGIS paging (`exceededTransferLimit`) until every feature is collected."""
    features: list[Mapping[str, Any]] = []
    for page in range(MAX_PAGES):
        paging = {"resultOffset": str(page * page_size), "resultRecordCount": str(page_size)}
        payload = _fetch_page(http, {**params, **paging})
        batch = payload.get("features")
        if not isinstance(batch, list):
            raise DataSourceError("India-WRIS response has no 'features' list")
        features.extend(batch)
        if not batch or not payload.get("exceededTransferLimit"):
            return features
    raise DataSourceError(f"India-WRIS returned more than {MAX_PAGES} pages")


def _fetch_page(http: httpx.Client, params: Mapping[str, str]) -> Mapping[str, Any]:
    """One query page; ArcGIS reports errors as HTTP 200 with an `error` object."""
    payload = response_json(get_response(http, QUERY_URL, params=params))
    if not isinstance(payload, dict):
        raise DataSourceError("India-WRIS response is not a JSON object")
    if "error" in payload:
        error = payload["error"] if isinstance(payload["error"], dict) else {}
        raise DataSourceError(f"India-WRIS query failed: {error.get('message', payload['error'])}")
    return payload


def _block_from_attributes(
    attributes: Mapping[str, Any], source: SourceTag
) -> BlockGroundwater | None:
    block = str(attributes.get("block") or "").strip()
    if not block:
        logger.warning("Skipping India-WRIS feature without a block name: %s", attributes)
        return None
    return BlockGroundwater(
        block=block,
        district=str(attributes.get("district") or "").strip(),
        category=str(attributes.get("class") or "").strip(),
        stage_pct=_stage(attributes.get("sgw_dev_pe")),
        source=source,
    )


def _stage(value: Any) -> float | None:
    """Stage of extraction as a float, or None when missing or not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise(text: str) -> str:
    """Casefold, unify Unicode forms, turn punctuation into spaces and collapse whitespace."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_NON_WORD.sub(" ", folded).split())


def _exact_keys(block: str) -> set[str]:
    return {_normalise(block)}


def _bare_keys(block: str) -> set[str]:
    return {_normalise(_PARENTHETICAL.sub(" ", block))}


def _alias_keys(block: str) -> set[str]:
    return {_normalise(alias) for alias in _PARENTHETICAL.findall(block)}


def _unique(hits: list[BlockGroundwater]) -> BlockGroundwater | None:
    """The single hit, or None if the same name appears in more than one district."""
    if len({(_normalise(b.block), _normalise(b.district)) for b in hits}) == 1:
        return hits[0]
    return None


def _fuzzy(pool: Sequence[BlockGroundwater], target: str, cutoff: float) -> BlockGroundwater | None:
    """Closest block name by `difflib` ratio, if it clears `cutoff` and is unambiguous."""
    names = sorted({_normalise(b.block) for b in pool})
    best = difflib.get_close_matches(target, names, n=1, cutoff=cutoff)
    if not best:
        return None
    return _unique([b for b in pool if _normalise(b.block) == best[0]])
