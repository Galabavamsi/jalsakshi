"""Official JJM IMIS / WQMIS records snapshot (jalsakshi.data.official)."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from jalsakshi.core.models import Freshness
from jalsakshi.data.http import IST
from jalsakshi.data.official import (
    SNAPSHOT_PATH,
    OfficialRecord,
    OfficialWaterQuality,
    load_official,
    load_official_district,
    official_age_note,
)
from jalsakshi.data.villages import load_villages

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=IST)


def _record(lgd: str) -> OfficialRecord:
    record = load_official(lgd)
    assert record is not None
    return record


def test_kutelabhatha_official_record():
    r = _record("442569")
    assert (r.imis_village_id, r.name, r.gram_panchayat, r.gp_imis_id) == (
        "0000523118",
        "Kutela Bhatha",
        "Kutelabhatha",
        "0000216969",
    )
    assert (r.households, r.tap_connections, r.population) == (455, 450, 2036)
    assert (r.population_sc, r.population_st) == (477, 199)
    assert r.hgj_status == "IN_PROGRESS"
    assert r.source_type == "Deep tubewell (groundwater) in village"
    assert [
        (s.scheme_id, s.name, s.sanction_year, s.estimated_lakh, s.spent_lakh) for s in r.schemes
    ] == [
        ("40006378", "Retrofitting Scheme Kutelabhata", "2021-22", 56.01, 48.93),
        ("40061307", "Jeora-Sirsakhurd-Bhatgaon 17 MVS", "2021-22", 2371.58, 1549.22),
    ]
    assert all((s.status, s.functional_status) == ("Ongoing", "Functional") for s in r.schemes)


def test_kutelabhatha_water_quality_on_record():
    wq = _record("442569").wq
    assert wq is not None
    assert wq.last_household_test == date(2023, 8, 17)
    assert wq.household_test_dates == [date(2023, 3, 18), date(2023, 8, 10), date(2023, 8, 17)]
    assert wq.last_household_values_date == date(2023, 8, 10)
    assert wq.last_household_values["Nitrate (mg/L, limit 45)"] == "44.5\u201344.9"
    assert wq.last_household_values["pH"] == "7.02\u20137.2"
    assert wq.last_household_values["Arsenic"] == "0"
    assert "6 household tap samples" in wq.samples_summary and "all Safe" in wq.samples_summary
    assert wq.contamination_flags == ["FY 2024-25 lab: turbidity, 1 sample"]
    assert (wq.ftk_this_fy, wq.ftk_samples_this_fy, wq.ftk_samples_last_fy) == ("2026-27", 13, 14)
    assert wq.ftk_parameters == ["pH", "turbidity", "TDS", "hardness"]
    assert wq.women_trained_ftk == 5


def test_source_tag_says_it_is_the_state_claim():
    source = _record("442569").source
    assert source.source == "JJM IMIS / WQMIS public dashboard (as entered by the state)"
    assert source.freshness is Freshness.DAILY
    assert source.fetched_at == datetime(2026, 10, 9, 5, 0, tzinfo=IST)
    assert source.url == "https://ejalshakti.gov.in/jjmreport/JJMIndia.aspx"


@pytest.mark.parametrize(
    ("lgd", "imis", "households", "taps", "status"),
    [
        ("442570", "0000523119", 271, 209, "IN_PROGRESS"),
        ("442561", "0000523105", 1029, 988, "IN_PROGRESS"),
        ("442629", "0000523104", 1553, 1547, "IN_PROGRESS"),
        ("442568", "0000523102", 543, 509, "IN_PROGRESS"),
        ("442552", "0000523106", 466, 466, "CERTIFIED"),
        ("442565", "0000523151", 448, 320, "IN_PROGRESS"),
    ],
)
def test_neighbour_records(lgd: str, imis: str, households: int, taps: int, status: str):
    r = _record(lgd)
    assert (r.imis_village_id, r.households, r.tap_connections, r.hgj_status) == (
        imis,
        households,
        taps,
        status,
    )
    assert r.population is None and r.wq is None


def test_kachandur_is_certified_with_schemes_still_ongoing():
    r = _record("442552")
    assert [(s.scheme_id, s.status) for s in r.schemes] == [
        ("40013723", "Ongoing"),
        ("40061307", "Ongoing"),
    ]
    assert r.schemes[0].kind == "Retrofitting"


def test_unknown_village_is_none():
    assert load_official("999999") is None


def test_district_totals():
    district = load_official_district()
    assert district is not None
    assert (district.district, district.report) == ("Durg", "J8")
    assert (district.villages, district.hgj_reported, district.hgj_certified) == (385, 164, 148)
    assert district.source.observed_at == datetime(2026, 10, 8, tzinfo=IST)


def test_age_note_counts_whole_years():
    note = official_age_note(_record("442569"), NOW)
    assert note == "Last official household tap test: 17 Aug 2023 (3 years ago)"


@pytest.mark.parametrize(
    ("tested", "expected"),
    [
        (date(2026, 10, 9), "today"),
        (date(2026, 10, 8), "1 day ago"),
        (date(2026, 9, 10), "29 days ago"),
        (date(2026, 9, 9), "1 month ago"),
        (date(2025, 10, 10), "11 months ago"),
        (date(2025, 10, 9), "1 year ago"),
        (date(2026, 10, 10), "in the future"),
    ],
)
def test_age_note_wording(tested: date, expected: str):
    record = _record("442569").model_copy(
        update={"wq": OfficialWaterQuality(last_household_test=tested)}
    )
    assert official_age_note(record, NOW).endswith(f"({expected})")


def test_age_note_without_a_test():
    assert official_age_note(_record("442570"), NOW) == "No official household tap test on record"


def test_age_note_needs_an_aware_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        official_age_note(_record("442569"), datetime(2026, 10, 9))


def test_every_master_village_has_a_matching_official_record():
    for village in load_villages():
        record = _record(village.lgd_code or "")
        assert record.imis_village_id == village.imis_village_code


def test_snapshot_holds_no_phone_numbers():
    text = SNAPSHOT_PATH.read_text("utf-8")
    assert "+91" not in text
    assert not re.search(r"(?<!\d)[6-9]\d{9}(?!\d)", text)
