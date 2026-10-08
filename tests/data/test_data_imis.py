"""JJM IMIS Har Ghar Jal report parsing (jalsakshi.data.imis), offline from a saved page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
import pytest
from data_fakes import ClientFor, Recorder

from jalsakshi.core.models import Freshness
from jalsakshi.data.http import IST, DataSourceError
from jalsakshi.data.imis import (
    REPORT_URL,
    SOURCE_NAME,
    StateHGJ,
    fetch_state_hgj,
    parse_as_on,
    parse_state_hgj,
)

FIXTURE = "imis_hgj_village.html"
FETCHED_AT = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


@pytest.fixture
def page(fixture_text: Callable[[str], str]) -> str:
    return fixture_text(FIXTURE)


def _serve(html: str, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, text=html)


def test_fetch_returns_chhattisgarh_counts_with_source(
    page: str, client_for: ClientFor, recorder: Recorder
):
    result = fetch_state_hgj(client=client_for(_serve(page)))

    assert isinstance(result, StateHGJ)
    assert (result.state, result.villages, result.reported, result.certified) == (
        "Chhattisgarh",
        19658,
        7603,
        6594,
    )
    assert result.as_on == date(2026, 10, 7)
    assert result.source.source == SOURCE_NAME
    assert result.source.url == REPORT_URL
    assert result.source.freshness is Freshness.DAILY
    assert result.source.observed_at == datetime(2026, 10, 7, tzinfo=IST)
    assert result.source.fetched_at.tzinfo is not None
    assert str(recorder.requests[0].url) == REPORT_URL
    assert recorder.requests[0].method == "GET"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("goa", ("Goa", 373, 373, 373)),
        ("  CHHATTISGARH ", ("Chhattisgarh", 19658, 7603, 6594)),
        ("Andaman and Nicobar Islands", ("Andaman & Nicobar Islands", 265, 265, 265)),
    ],
)
def test_state_lookup_ignores_case_spacing_and_ampersand(
    page: str, name: str, expected: tuple[str, int, int, int]
):
    result = parse_state_hgj(page, name, fetched_at=FETCHED_AT)
    assert (result.state, result.villages, result.reported, result.certified) == expected


def test_total_row_is_not_mistaken_for_a_state(page: str):
    with pytest.raises(DataSourceError, match="not found"):
        parse_state_hgj(page, "Total", fetched_at=FETCHED_AT)


def test_unknown_state_raises(page: str):
    with pytest.raises(DataSourceError, match="'Atlantis' not found"):
        parse_state_hgj(page, "Atlantis", fetched_at=FETCHED_AT)


def test_counts_with_thousands_separators_parse(page: str):
    html = page.replace(">7603<", ">7,603<")
    assert parse_state_hgj(html, "Chhattisgarh", fetched_at=FETCHED_AT).reported == 7603


def test_non_numeric_count_raises(page: str):
    html = page.replace(">7603<", ">n/a<")
    with pytest.raises(DataSourceError, match="not a number"):
        parse_state_hgj(html, "Chhattisgarh", fetched_at=FETCHED_AT)


def test_as_on_falls_back_to_the_note_then_selected_option(page: str):
    without_script = page.replace("LastUpdatedOn = '07/10/2026';", "")
    assert parse_as_on(without_script) == date(2026, 10, 7)
    option = '<option selected="selected" value="2026-2027">As on 05/10/2026</option>'
    assert parse_as_on(f"<select><option>As on 01/04/2021</option>{option}</select>") == date(
        2026, 10, 5
    )


def test_missing_as_on_date_leaves_observed_at_empty(page: str):
    html = page.replace("LastUpdatedOn = '07/10/2026';", "").replace("as on 07/10/2026", "")
    result = parse_state_hgj(html, "Chhattisgarh", fetched_at=FETCHED_AT)
    assert result.as_on is None
    assert result.source.observed_at is None
    assert result.source.fetched_at == FETCHED_AT


def test_invalid_as_on_date_is_ignored():
    assert parse_as_on("LastUpdatedOn = '31/02/2026';") is None


def test_layout_change_is_detected(page: str):
    html = page.replace("No. of Har Ghar Jal Village", "No. of FHTC Village")
    with pytest.raises(DataSourceError, match="layout changed"):
        parse_state_hgj(html, "Chhattisgarh", fetched_at=FETCHED_AT)


def test_missing_table_raises():
    with pytest.raises(DataSourceError, match="table"):
        parse_state_hgj("<html><body>Runtime Error</body></html>", "Goa", fetched_at=FETCHED_AT)


def test_server_error_surfaces_as_data_source_error(client_for: ClientFor, recorder: Recorder):
    with pytest.raises(DataSourceError, match="HTTP 500"):
        fetch_state_hgj(client=client_for(_serve("oops", status=500)))
    assert len(recorder.requests) == 4
