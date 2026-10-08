"""Number validator: every number must be a tool value; dates and ids are not quantities."""

from __future__ import annotations

import pytest

from jalsakshi.agent.numbers import extract_numbers, invented_numbers, validate_numbers


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("7 दिन में 3 दिन पानी, 26.5 घंटे", {7, 3, 26.5}),
        ("७ दिन, २६.५ घंटे", {7, 26.5}),
        ("43% दिन", {43}),
        ("26.50 घंटे", {26.5}),
        ("12 घंटे", {12.0}),
        ("1,20,000 लीटर और 12,345", {120000, 12345}),
        ("5,10 दिन", {5, 10}),
        ("एक गाँव, दो बातें", set()),
        ("तीन दिन", {3}),
        ("कोई संख्या नहीं", set()),
    ],
)
def test_accepts_only_allowed_numbers(text: str, allowed: set[int | float]) -> None:
    assert validate_numbers(text, allowed)


@pytest.mark.parametrize(
    ("text", "allowed", "invented"),
    [
        ("9 दिन", {7}, [9.0]),
        ("८ दिन", {7}, [8.0]),
        ("26.4 घंटे", {26.5}, [26.4]),
        ("60% दिन", {43}, [60.0]),
        ("तीन दिन", {7}, [3.0]),
        ("सौ प्रतिशत", {43}, [100.0]),
        ("5 marks", set(), [5.0]),
        ("2026-13-45", set(), [2026.0, 13.0, 45.0]),
    ],
)
def test_rejects_invented_numbers(
    text: str, allowed: set[int | float], invented: list[float]
) -> None:
    assert not validate_numbers(text, allowed)
    assert invented_numbers(text, allowed) == invented


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-07 को",
        "2026-10-07T10:30:00+05:30",
        "07/10/2026 और 7-10-2026 और 07.10.2026",
        "7 अक्टूबर 2026 से 12 अक्तूबर तक",
        "October 7, 2026 and 7 Oct",
        "अक्टूबर 2026",
        "१ अक्टूबर २०२६",
        "10:30 बजे",
        "1. पहला\n2. दूसरा",
    ],
)
def test_dates_times_and_list_markers_are_not_quantities(text: str) -> None:
    assert validate_numbers(text, set())


def test_ignored_identifiers_are_skipped() -> None:
    text = "शिकायत TKT-0042 (CGWB 2025 के अनुसार) बंद"
    assert not validate_numbers(text, set())
    assert validate_numbers(text, set(), ignore=["TKT-0042", "CGWB 2025"])


def test_extract_numbers_reads_digits_and_words() -> None:
    assert extract_numbers("3 और चार, ५.५") == [3.0, 5.5, 4.0]
