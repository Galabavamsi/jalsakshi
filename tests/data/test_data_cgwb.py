"""CGWB 2025 block groundwater from India-WRIS (jalsakshi.data.cgwb), offline from a saved query."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from data_fakes import ClientFor, Recorder, json_response
from hypothesis import given
from hypothesis import strategies as st

from jalsakshi.core.models import Freshness, SourceTag
from jalsakshi.data.cgwb import (
    QUERY_URL,
    SOURCE_NAME,
    BlockGroundwater,
    fetch_block_groundwater,
    find_block,
    parse_blocks,
)
from jalsakshi.data.http import DataSourceError

FIXTURE = "cgwb_cg_blocks.json"
SOURCE = SourceTag(
    source=SOURCE_NAME, fetched_at=datetime(2026, 10, 8, tzinfo=UTC), freshness=Freshness.ANNUAL
)


@pytest.fixture
def payload(fixture_text: Callable[[str], str]) -> dict[str, Any]:
    return json.loads(fixture_text(FIXTURE))


@pytest.fixture
def blocks(payload: dict[str, Any]) -> list[BlockGroundwater]:
    return parse_blocks(payload["features"], SOURCE)


def _block(name: str, district: str = "Durg") -> BlockGroundwater:
    return BlockGroundwater(
        block=name, district=district, category="Safe", stage_pct=50.0, source=SOURCE
    )


def test_fetch_parses_blocks_with_annual_source(
    payload: dict[str, Any], client_for: ClientFor, recorder: Recorder
):
    result = fetch_block_groundwater(client=client_for(lambda request: json_response(payload)))

    assert len(result) == 13
    durg = next(b for b in result if b.block == "Durg")
    assert (durg.district, durg.category) == ("Durg", "Semi Critical")
    assert durg.stage_pct == pytest.approx(87.2421636)
    assert durg.source.freshness is Freshness.ANNUAL
    assert durg.source.source == SOURCE_NAME
    assert durg.source.observed_at is None
    assert durg.source.url is not None and durg.source.url.startswith(QUERY_URL)
    assert "state%3D%27CG%27" in durg.source.url

    params = recorder.requests[0].url.params
    assert params["where"] == "state='CG'"
    assert params["outFields"] == "block,district,class,sgw_dev_pe"
    assert params["returnGeometry"] == "false"
    assert params["f"] == "json"
    assert params["resultOffset"] == "0"


def test_fetch_follows_arcgis_paging(
    payload: dict[str, Any], client_for: ClientFor, recorder: Recorder
):
    features = payload["features"]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["resultOffset"])
        size = int(request.url.params["resultRecordCount"])
        page = features[offset : offset + size]
        more = offset + size < len(features)
        return json_response({"features": page, "exceededTransferLimit": more})

    result = fetch_block_groundwater(client=client_for(handler), page_size=5)

    assert [b.block for b in result] == [f["attributes"]["block"] for f in features]
    assert [r.url.params["resultOffset"] for r in recorder.requests] == ["0", "5", "10"]


def test_arcgis_error_payload_raises(client_for: ClientFor):
    error = {"error": {"code": 400, "message": "Failed to execute query.", "details": []}}
    with pytest.raises(DataSourceError, match="Failed to execute query"):
        fetch_block_groundwater(client=client_for(lambda request: json_response(error)))


def test_payload_without_features_raises(client_for: ClientFor):
    with pytest.raises(DataSourceError, match="features"):
        fetch_block_groundwater(client=client_for(lambda request: json_response({"x": 1})))


@pytest.mark.parametrize("code", ["cg", "CGX", "C'", "", "CG' OR 1=1 --"])
def test_state_code_is_validated_before_any_request(
    code: str, client_for: ClientFor, recorder: Recorder
):
    with pytest.raises(ValueError, match="state_code"):
        fetch_block_groundwater(code, client=client_for(lambda request: json_response({})))
    assert recorder.requests == []


def test_page_size_must_be_positive(client_for: ClientFor):
    with pytest.raises(ValueError, match="page_size"):
        fetch_block_groundwater(client=client_for(lambda request: json_response({})), page_size=0)


def test_parse_skips_unnamed_blocks_and_tolerates_missing_stage():
    features = [
        {"attributes": {"block": "  ", "district": "Durg", "class": "Safe", "sgw_dev_pe": 1.0}},
        {"attributes": {"block": "Saja", "district": "Bemetara", "class": "Salinity"}},
        {"attributes": {"block": "Berla", "district": "Bemetara", "sgw_dev_pe": "n/a"}},
        {},
    ]
    result = parse_blocks(features, SOURCE)
    assert [(b.block, b.category, b.stage_pct) for b in result] == [
        ("Saja", "Salinity", None),
        ("Berla", "", None),
    ]


@pytest.mark.parametrize(
    ("query", "district", "expected"),
    [
        ("durg", None, ("Durg", "Durg")),
        ("NAWAGARH", None, ("Nawagarh", "Bemetara")),
        ("Nawagarh", "janjgir champa", ("Janjgir (Nawagarh)", "Janjgir-Champa")),
        ("Janjgir", None, ("Janjgir (Nawagarh)", "Janjgir-Champa")),
        ("Dhamda", None, ("Dhamdha", "Durg")),
        ("doundi", None, ("Doundi", "Balod")),
        ("Doundi-Lohara", None, ("Doundi Lohara", "Balod")),
        ("Bemetara", "Bemetara", ("Bemetara", "Bemetara")),
    ],
)
def test_find_block_matches_fuzzily(
    blocks: list[BlockGroundwater],
    query: str,
    district: str | None,
    expected: tuple[str, str],
):
    found = find_block(blocks, query, district=district)
    assert found is not None
    assert (found.block, found.district) == expected


@pytest.mark.parametrize(("query", "district"), [("Raipur", None), ("", None), ("Durg", "Balod")])
def test_find_block_returns_none_without_a_good_match(
    blocks: list[BlockGroundwater], query: str, district: str | None
):
    assert find_block(blocks, query, district=district) is None


def test_find_block_refuses_ambiguous_names_unless_district_given():
    twins = [_block("Patan", "Durg"), _block("Patan", "Gujarat Border")]
    assert find_block(twins, "patan") is None
    found = find_block(twins, "patan", district="durg")
    assert found is not None and found.district == "Durg"


@given(data=st.data())
def test_find_block_survives_case_and_spacing_changes(data: st.DataObject):
    names = ["Durg", "Dhamdha", "Patan", "Nawagarh", "Janjgir (Nawagarh)", "Doundi Lohara"]
    pool = [_block(name, district=f"D{i}") for i, name in enumerate(names)]
    target = data.draw(st.sampled_from(pool))
    flips = data.draw(st.lists(st.booleans(), min_size=len(target.block)))
    mangled = "".join(
        ch.upper() if flip else ch.lower() for ch, flip in zip(target.block, flips, strict=False)
    )
    padding = data.draw(st.sampled_from(["", " ", "  ", "\t"]))
    assert find_block(pool, f"{padding}{mangled}{padding}") == target
