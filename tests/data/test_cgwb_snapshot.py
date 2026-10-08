import httpx

from jalsakshi.core.models import Freshness
from jalsakshi.data.cgwb import (
    fetch_block_groundwater_or_snapshot,
    find_block,
    load_snapshot,
)


def test_snapshot_loads_and_is_labelled():
    blocks = load_snapshot("CG")
    assert len(blocks) > 100
    assert all(b.source.freshness is Freshness.ANNUAL for b in blocks)
    assert all("bundled snapshot" in b.source.source for b in blocks)
    durg = find_block(blocks, "Durg")
    assert durg is not None and durg.stage_pct is not None


def test_falls_back_to_snapshot_when_service_times_out():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated India-WRIS timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        blocks = fetch_block_groundwater_or_snapshot("CG", client=client)
    assert blocks and "bundled snapshot" in blocks[0].source.source
