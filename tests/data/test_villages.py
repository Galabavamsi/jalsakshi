"""The bundled Durg block village master (jalsakshi.data.villages)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from jalsakshi.core.models import Freshness, GeoPoint, Village
from jalsakshi.data.villages import (
    DURG_BLOCK_FILE,
    haversine_km,
    load_villages,
    nearby,
    village_id,
)

LGD_SOURCE = "LGD snapshot 2 Sep 2026 via villagecodes.in; GP list confirmed on durg.gov.in"
CENSUS_SOURCE = "Census 2011 District Census Handbook (Durg), via public mirrors"


@pytest.fixture(scope="module")
def villages() -> list[Village]:
    return load_villages()


def _by_name(villages: list[Village], name: str) -> Village:
    return next(v for v in villages if v.name == name)


def test_kutelabhatha_master_record(villages: list[Village]):
    v = _by_name(villages, "Kutelabhatha")
    assert v.id == "lgd-442569"
    assert (v.name_hi, v.block, v.district, v.state) == (
        "कुटेलाभाटा",
        "Durg",
        "Durg",
        "Chhattisgarh",
    )
    assert (v.lgd_code, v.census_code, v.imis_village_code) == ("442569", "442569", "0000523118")
    assert (v.gram_panchayat, v.gp_lgd_code) == ("Kutelabhata", "124575")
    assert (v.census_population, v.census_households) == (1777, 397)
    assert v.location == GeoPoint(
        lat=21.238001, lon=81.318368, source="GeoNames, approximate (not in OpenStreetMap)"
    )
    assert v.inbound is True
    assert (v.checkin_local_time, v.quorum, v.active) == ("19:00", 2, True)
    assert v.claimed_hgj is None and v.hgj_certified is None


def test_census_source_is_labelled_annual_2011(villages: list[Village]):
    for v in villages:
        tag = v.census_source
        assert tag is not None
        assert tag.source == CENSUS_SOURCE
        assert tag.freshness is Freshness.ANNUAL
        assert tag.observed_at is not None and tag.observed_at.date().isoformat() == "2011-03-01"
        assert tag.fetched_at.astimezone(UTC).date() <= datetime(2026, 10, 9, tzinfo=UTC).date()


def test_every_village_is_real_and_unique(villages: list[Village]):
    expected = {
        "442569": ("Kutelabhatha", "124575", 1777, 397, "0000523118"),
        "442570": ("Khapri", "263420", 1153, 229, "0000523119"),
        "442561": ("Jeora", "124560", 3793, 804, "0000523105"),
        "442568": ("Bhatgaon", "124538", 1963, 413, "0000523102"),
        "442552": ("Kachandur", "124562", 2597, 583, "0000523106"),
        "442629": ("Sirsa Khurd", "124592", 6211, 1356, "0000523104"),
        "442565": ("Belaudi", "124535", 2208, 488, "0000523151"),
    }
    got = {
        v.lgd_code: (
            v.name,
            v.gp_lgd_code,
            v.census_population,
            v.census_households,
            v.imis_village_code,
        )
        for v in villages
    }
    assert got == expected
    assert len({v.id for v in villages}) == len(villages)
    assert all(v.id == village_id(v.lgd_code or "") for v in villages)
    assert [v.name for v in villages if v.inbound] == ["Kutelabhatha"]
    assert all((v.block, v.district, v.state) == ("Durg", "Durg", "Chhattisgarh") for v in villages)


def test_locations_keep_their_source_and_unknown_ones_are_none(villages: list[Village]):
    assert _by_name(villages, "Khapri").location == GeoPoint(
        lat=21.2356724, lon=81.3120997, source="OpenStreetMap"
    )
    kachandur = _by_name(villages, "Kachandur").location
    assert kachandur is not None and "uncertain" in kachandur.source
    assert _by_name(villages, "Sirsa Khurd").location is None
    assert _by_name(villages, "Belaudi").location is None


def test_master_file_records_name_their_code_source():
    rows = json.loads(DURG_BLOCK_FILE.read_text("utf-8"))
    assert isinstance(rows, list)
    assert all(row["codes_source"] == LGD_SOURCE for row in rows)
    kutela = next(row for row in rows if row["lgd_code"] == "442569")
    assert (kutela["census_male"], kutela["census_female"], kutela["census_area_ha"]) == (
        885,
        892,
        222.68,
    )
    assert kutela["pin"] == "491001"
    assert (kutela["janpad_lgd_code"], kutela["block_lgd_code"], kutela["tehsil_lgd_code"]) == (
        "254876",
        "3635",
        "3317",
    )
    assert (kutela["district_lgd_code"], kutela["state_lgd_code"]) == ("378", "22")


def test_nearby_lists_villages_nearest_first(villages: list[Village]):
    kutela = _by_name(villages, "Kutelabhatha")
    assert [v.name for v in nearby(kutela, villages, 1.0)] == ["Khapri"]
    assert [v.name for v in nearby(kutela, villages, 5.0)] == [
        "Khapri",
        "Jeora",
        "Bhatgaon",
        "Kachandur",
    ]
    assert nearby(kutela, villages, 0.0) == []


def test_nearby_without_a_location_is_empty(villages: list[Village]):
    assert nearby(_by_name(villages, "Belaudi"), villages, 100.0) == []


def test_nearby_rejects_negative_radius(villages: list[Village]):
    with pytest.raises(ValueError, match="km"):
        nearby(villages[0], villages, -1)


def test_haversine_known_distance():
    # Kutelabhatha to the Biroda_2 CGWB telemetry well, about 3.7 km west.
    assert haversine_km(21.238001, 81.318368, 21.2444, 81.2833) == pytest.approx(3.70, abs=0.01)


coords = st.tuples(
    st.floats(min_value=-89.9, max_value=89.9), st.floats(min_value=-179.9, max_value=179.9)
)


@given(coords, coords)
def test_haversine_is_symmetric_and_bounded(a: tuple[float, float], b: tuple[float, float]):
    d = haversine_km(*a, *b)
    assert d == pytest.approx(haversine_km(*b, *a), abs=1e-6)
    assert 0.0 <= d <= 20_016.0
    assert haversine_km(*a, *a) == pytest.approx(0.0, abs=1e-9)
