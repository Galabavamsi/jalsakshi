"""Number validator for generated briefs (docs/ARCHITECTURE.md section 10).

Every number in the text must equal an allowed (tool) value. Dates, clock times, ordered-list
markers and caller-supplied identifiers (ticket ids, source names) are not quantities and are
removed first. Devanagari digits and unambiguous Hindi number words are checked too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from typing import Final

ASCII_DIGITS: Final = str.maketrans("०१२३४५६७८९", "0123456789")
TOLERANCE: Final = 1e-6

_HINDI_MONTHS: Final = (
    "जनवरी|फ़रवरी|फरवरी|मार्च|अप्रैल|अप्रेल|मई|जून|जुलाई|अगस्त|सितंबर|सितम्बर|अक्टूबर|अक्तूबर|"
    "नवंबर|नवम्बर|दिसंबर|दिसम्बर"
)
_EN_MONTHS: Final = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    "sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
# Devanagari letters and signs (U+0900-U+0963, U+0971-U+097F): no digits or dandas.
_DEVANAGARI: Final = f"{chr(0x0900)}-{chr(0x0963)}{chr(0x0971)}-{chr(0x097F)}"
_LETTER: Final = f"A-Za-z{_DEVANAGARI}"
_MONTHS: Final = f"(?<![{_LETTER}])(?:{_HINDI_MONTHS}|{_EN_MONTHS})(?![{_LETTER}])"

_ISO_DATE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})"  # date
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"  # optional time
)
_DMY_DATE = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?!\d)")
_DAY_MONTH = re.compile(rf"(?<!\d)(\d{{1,2}})\s*{_MONTHS}\.?(?:,?\s*(\d{{4}}))?(?!\d)", re.I)
_MONTH_DAY = re.compile(rf"{_MONTHS}\.?\s+(\d{{1,2}})(?:,?\s*(\d{{4}}))?(?!\d)", re.I)
_MONTH_YEAR = re.compile(rf"{_MONTHS}\.?,?\s*(\d{{4}})(?!\d)", re.I)
_CLOCK = re.compile(r"(?<!\d)([01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?!\d)")
_LIST_MARKER = re.compile(r"(?m)^\s*\d{1,2}[.)]\s+")
_NUMBER = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")
_GROUPED = re.compile(r"\d{1,3}(?:,\d{2,3})*,\d{3}")
_DEVANAGARI_WORD = re.compile(f"[{_DEVANAGARI}]+")

# Unambiguous number words only: "एक" (also an article) and "दो" (also "give") are left out.
HINDI_NUMBER_WORDS: Final[dict[str, int]] = {
    "तीन": 3,
    "चार": 4,
    "पाँच": 5,
    "पांच": 5,
    "छह": 6,
    "छः": 6,
    "सात": 7,
    "आठ": 8,
    "नौ": 9,
    "दस": 10,
    "ग्यारह": 11,
    "बारह": 12,
    "तेरह": 13,
    "चौदह": 14,
    "पंद्रह": 15,
    "पन्द्रह": 15,
    "सोलह": 16,
    "सत्रह": 17,
    "अठारह": 18,
    "उन्नीस": 19,
    "बीस": 20,
    "तीस": 30,
    "चालीस": 40,
    "पचास": 50,
    "साठ": 60,
    "सत्तर": 70,
    "अस्सी": 80,
    "नब्बे": 90,
    "सौ": 100,
    "हज़ार": 1000,
    "हजार": 1000,
}


def validate_numbers(
    markdown: str,
    allowed: set[int | float],
    *,
    ignore: Iterable[str] = (),
) -> bool:
    """True when every number in ``markdown`` is in ``allowed`` (dates and ``ignore`` excepted)."""
    return not invented_numbers(markdown, allowed, ignore=ignore)


def invented_numbers(
    markdown: str,
    allowed: set[int | float],
    *,
    ignore: Iterable[str] = (),
) -> list[float]:
    """Numbers in ``markdown`` that are not allowed, in order of appearance."""
    text = strip_non_quantities(markdown, ignore)
    return [value for value in extract_numbers(text) if not _is_allowed(value, allowed)]


def strip_non_quantities(markdown: str, ignore: Iterable[str] = ()) -> str:
    """Normalise digits and blank out identifiers, valid dates, times and list markers."""
    text = markdown.translate(ASCII_DIGITS)
    for token in sorted({t.translate(ASCII_DIGITS) for t in ignore if t}, key=len, reverse=True):
        text = text.replace(token, " ")
    text = _ISO_DATE.sub(lambda m: _blank_if_date(m, int(m[1]), int(m[2]), int(m[3])), text)
    text = _DMY_DATE.sub(lambda m: _blank_if_date(m, int(m[3]), int(m[2]), int(m[1])), text)
    text = _DAY_MONTH.sub(lambda m: _blank_if_day(m, int(m[1])), text)
    text = _MONTH_DAY.sub(lambda m: _blank_if_day(m, int(m[1])), text)
    text = _MONTH_YEAR.sub(" ", text)
    text = _CLOCK.sub(" ", text)
    return _LIST_MARKER.sub(" ", text)


def extract_numbers(text: str) -> list[float]:
    """Digit numbers (with 1,234 or 1,23,456 grouping) and Hindi number words, as floats."""
    values: list[float] = []
    for token in _NUMBER.findall(text.translate(ASCII_DIGITS)):
        values.extend(_parse_number(token))
    values.extend(
        float(HINDI_NUMBER_WORDS[word])
        for word in _DEVANAGARI_WORD.findall(text)
        if word in HINDI_NUMBER_WORDS
    )
    return values


def _parse_number(token: str) -> list[float]:
    whole, _, fraction = token.partition(".")
    suffix = f".{fraction}" if fraction else ""
    if "," not in whole or _GROUPED.fullmatch(whole):
        return [float(whole.replace(",", "") + suffix)]
    parts = whole.split(",")
    return [float(p) for p in parts[:-1]] + [float(parts[-1] + suffix)]


def _is_allowed(value: float, allowed: set[int | float]) -> bool:
    return any(abs(value - float(a)) <= TOLERANCE for a in allowed)


def _blank_if_date(match: re.Match[str], year: int, month: int, day: int) -> str:
    try:
        date(year, month, day)
    except ValueError:
        return match[0]
    return " "


def _blank_if_day(match: re.Match[str], day: int) -> str:
    return " " if 1 <= day <= 31 else match[0]
