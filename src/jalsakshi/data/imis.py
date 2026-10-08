"""JJM IMIS Har Ghar Jal village report (Format J8): state-claimed and certified village counts.

The public report page is a plain HTML table, one row per state. The last three columns are
"No. of villages" and "No. of Har Ghar Jal Village: Reported, Certified". The page states its
"as on" date in a `LastUpdatedOn = 'dd/mm/yyyy'` script variable and in a red note above the table.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from html.parser import HTMLParser

import httpx
from pydantic import BaseModel, ConfigDict, Field

from jalsakshi.core.models import Freshness, SourceTag
from jalsakshi.data.http import IST, DataSourceError, borrow_client, get_response, utc_now

REPORT_URL = "https://ejalshakti.gov.in/JJM/JJMReports/Physical/JJMRep_HarGharJalVillage.aspx"
SOURCE_NAME = "JJM IMIS Har Ghar Jal village report (claimed by state)"
TABLE_ID = "tableReportTable"

_AS_ON_PATTERNS = (
    re.compile(r"LastUpdatedOn\s*=\s*['\"](\d{1,2}/\d{1,2}/\d{4})['\"]"),
    re.compile(r"Data entered as on\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE),
    re.compile(r"<option[^>]*\bselected\b[^>]*>\s*As on\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE),
)
_DIGITS = re.compile(r"[0-9]+")
_VILLAGE_HEADERS = ("no. of villages", "no. of har ghar jal village")
_COUNT_HEADERS = ("reported", "certified")


class StateHGJ(BaseModel):
    """Har Ghar Jal village counts for one state, as claimed in IMIS."""

    model_config = ConfigDict(frozen=True)

    state: str
    villages: int = Field(ge=0)
    reported: int = Field(ge=0)
    certified: int = Field(ge=0)
    as_on: date | None
    source: SourceTag


class _TableRows(HTMLParser):
    """Collects whitespace-normalised cell text, row by row, from the table with a given id."""

    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self._table_id = table_id
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.found = False
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._enter_table(dict(attrs).get("id"))
        elif self._depth == 1 and tag == "tr":
            self._flush_row()
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._flush_cell()
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth:
            if self._depth == 1:
                self._flush_row()
            self._depth -= 1
        elif self._depth == 1 and tag in ("td", "th"):
            self._flush_cell()
        elif self._depth == 1 and tag == "tr":
            self._flush_row()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def _enter_table(self, table_id: str | None) -> None:
        if self._depth:
            self._depth += 1
        elif table_id == self._table_id:
            self._depth = 1
            self.found = True

    def _flush_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if self._row:
            self.rows.append(self._row)
        self._row = None


def fetch_state_hgj(
    state_name: str = "Chhattisgarh", *, client: httpx.Client | None = None
) -> StateHGJ:
    """Fetch the IMIS Har Ghar Jal report and return the counts for `state_name`.

    Raises `DataSourceError` if the page cannot be fetched, its layout changed, or the state is
    missing.
    """
    with borrow_client(client) as http:
        response = get_response(http, REPORT_URL)
    return parse_state_hgj(response.text, state_name, fetched_at=utc_now())


def parse_state_hgj(
    html: str, state_name: str, *, fetched_at: datetime, url: str = REPORT_URL
) -> StateHGJ:
    """Parse one state's row and the "as on" date out of the report HTML."""
    rows = report_rows(html)
    _check_layout(rows)
    row = _state_row(rows, state_name)
    villages, reported, certified = (_count(cell) for cell in row[-3:])
    as_on = parse_as_on(html)
    source = SourceTag(
        source=SOURCE_NAME,
        url=url,
        observed_at=datetime.combine(as_on, time.min, tzinfo=IST) if as_on else None,
        fetched_at=fetched_at,
        freshness=Freshness.DAILY,
    )
    return StateHGJ(
        state=row[1],
        villages=villages,
        reported=reported,
        certified=certified,
        as_on=as_on,
        source=source,
    )


def report_rows(html: str) -> list[list[str]]:
    """All rows (header and data) of the report table, as lists of cell text."""
    parser = _TableRows(TABLE_ID)
    parser.feed(html)
    parser.close()
    if not parser.found:
        raise DataSourceError(f"IMIS report table #{TABLE_ID} not found")
    return parser.rows


def parse_as_on(html: str) -> date | None:
    """The report's "as on" date, or None if the page does not state one."""
    for pattern in _AS_ON_PATTERNS:
        match = pattern.search(html)
        if match is None:
            continue
        try:
            return datetime.strptime(match.group(1), "%d/%m/%Y").date()
        except ValueError:
            continue
    return None


def _check_layout(rows: list[list[str]]) -> None:
    """Guard against a silent column shift: the last header groups must be the village counts."""
    if len(rows) < 2:
        raise DataSourceError("IMIS report table has no header rows")
    groups = tuple(cell.casefold() for cell in rows[0][-2:])
    counts = tuple(cell.casefold() for cell in rows[1][-2:])
    if groups != _VILLAGE_HEADERS or counts != _COUNT_HEADERS:
        raise DataSourceError(f"IMIS report layout changed: header ends {rows[0][-2:]}")


def _state_row(rows: list[list[str]], state_name: str) -> list[str]:
    """The data row whose state-name cell matches `state_name`, ignoring case and spacing."""
    wanted = _normalise(state_name)
    for row in rows:
        if len(row) >= 5 and _normalise(row[1]) == wanted:
            return row
    raise DataSourceError(f"state {state_name!r} not found in IMIS Har Ghar Jal report")


def _normalise(text: str) -> str:
    return " ".join(text.replace("&", " and ").casefold().split())


def _count(cell: str) -> int:
    """Parse an integer count cell such as "7603" or "7,603"."""
    digits = cell.replace(",", "").strip()
    if not _DIGITS.fullmatch(digits):
        raise DataSourceError(f"IMIS count cell is not a number: {cell!r}")
    return int(digits)
