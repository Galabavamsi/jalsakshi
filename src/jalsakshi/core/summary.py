"""Weekly summary for the sarpanch: a fixed Hindi template filled from analytics (§15.10).

Pure and deterministic: no LLM, no clock reads; the same analytics always give the same words.
The Hindi text is spoken by TTS on a phone call, so it is plain romanised Hindi in short
sentences, with numbers as digits. The English text is the same summary for the console.

Every number in either text is also in `WeeklySummary.numbers`, so tests and the console can
check that the spoken words match the analytics. (Names are not numbers: a point called
"Standpost 2" puts a digit in the text that is not in `numbers`.)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, ConfigDict

from jalsakshi.core.analytics import PointAnalytics, VillageAnalytics
from jalsakshi.core.models import Freshness, SourceTag, Village, WaterPoint

MAX_POINTS = 3
"""Water points named in the summary (worst reliability first)."""
MAX_CHARS_HI = 600
"""Hindi text budget; extra point sentences are dropped (worst kept) to stay within it."""
CLOSING_HI = "Poori report JalSakshi console par hai."
CLOSING_EN = "The full report is on the JalSakshi console."
_LABELLED = frozenset({Freshness.SIMULATED, Freshness.REPLAY})

type Numbers = dict[str, int | float | None]


class WeeklySummary(BaseModel):
    """The summary text in Hindi (spoken) and English (console), with the numbers it uses."""

    model_config = ConfigDict(frozen=True)

    village_id: str
    start: date
    end: date
    text_hi: str
    text_en: str
    numbers: Numbers
    source: SourceTag


@dataclass(frozen=True, slots=True)
class _Sentence:
    hi: str
    en: str
    numbers: Numbers = field(default_factory=dict)


def weekly_summary_text(
    village: Village, analytics: VillageAnalytics, water_points: Sequence[WaterPoint]
) -> WeeklySummary:
    """Fill the weekly template: greeting, up to 3 points, complaints, closing (5-7 sentences)."""
    head = [_greeting(village, analytics)]
    points = _point_sentences(village, analytics, water_points)
    tail = [_open_sentence(analytics), _closed_sentence(analytics), _closing()]
    while len(points) > 1 and len(_join(head + points + tail, "hi")) > MAX_CHARS_HI:
        points = points[:-1]
    sentences = head + points + tail
    numbers: Numbers = {}
    for sentence in sentences:
        numbers.update(sentence.numbers)
    return WeeklySummary(
        village_id=analytics.village_id,
        start=analytics.start,
        end=analytics.end,
        text_hi=_join(sentences, "hi"),
        text_en=_join(sentences, "en"),
        numbers=numbers,
        source=analytics.source,
    )


def _join(sentences: Sequence[_Sentence], language: str) -> str:
    return " ".join(getattr(sentence, language) for sentence in sentences)


# --- sentences -----------------------------------------------------------------------------------


def _greeting(village: Village, analytics: VillageAnalytics) -> _Sentence:
    households = analytics.households
    registered, consented = households.registered, households.consented
    freshness = analytics.source.freshness
    label_hi = f", {freshness.value} data se" if freshness in _LABELLED else ""
    label_en = f", from {freshness.value} data" if freshness in _LABELLED else ""
    return _Sentence(
        hi=(
            f"Namaste, {village.name_hi or village.name} gaon ki saptahik JalSakshi report"
            f"{label_hi}: {registered} ghar jude hain, {consented} ne sahmati di hai."
        ),
        en=(
            f"Namaste, weekly JalSakshi report for {village.name}{label_en}: "
            f"{_count(registered, 'household')} registered, {consented} consented."
        ),
        numbers={"households_registered": registered, "households_consented": consented},
    )


def _point_sentences(
    village: Village, analytics: VillageAnalytics, water_points: Sequence[WaterPoint]
) -> list[_Sentence]:
    """One sentence per point, worst reliability first; points with no data come last."""
    points = analytics.points or [analytics.village]
    named = {p.id: p for p in water_points}
    rest_of_village = any(p.water_point_id is not None for p in points)
    ranked = sorted(enumerate(points), key=lambda item: _worst_first(item[1], item[0]))
    sentences = []
    for _, point in ranked[:MAX_POINTS]:
        label_hi, label_en = _labels(point, named, village, rest_of_village)
        sentences.append(_point_sentence(point, label_hi, label_en))
    return sentences


def _worst_first(point: PointAnalytics, index: int) -> tuple[bool, float, int, int]:
    return (point.reliability_pct is None, point.reliability_pct or 0.0, -point.no_supply, index)


def _labels(
    point: PointAnalytics,
    named: Mapping[str, WaterPoint],
    village: Village,
    rest_of_village: bool,
) -> tuple[str, str]:
    """How the point is named aloud (Hindi name first) and on the console."""
    wid = point.water_point_id
    if wid is not None and wid in named:
        known = named[wid]
        return known.name_hi or known.name, known.name
    if wid is not None:
        return point.name or wid, point.name or wid
    if rest_of_village:
        return "baaki gaon", "the rest of the village"
    return f"{village.name_hi or village.name} gaon", village.name


def _point_sentence(point: PointAnalytics, label_hi: str, label_en: str) -> _Sentence:
    days = point.days_in_period
    if point.observed == 0:
        return _Sentence(
            hi=f"Pichhle {days} din mein {label_hi} ki jaankari nahi mili.",
            en=f"Last {days} days at {label_en}: no information received.",
            numbers={"days": days},
        )
    key = point.water_point_id or "village"
    extra_hi = extra_en = ""
    if point.partial:
        extra_hi += f", {point.partial} din thoda aaya"
        extra_en += f", partly on {point.partial}"
    if point.dirty:
        extra_hi += f", {point.dirty} din gandla paani"
        extra_en += f", dirty on {point.dirty}"
    return _Sentence(
        hi=(
            f"Pichhle {days} din mein {label_hi}: {point.supplied} din paani aaya, "
            f"{point.no_supply} din nahi aaya{extra_hi}, {point.unknown} din ki jaankari nahi."
        ),
        en=(
            f"Last {days} days at {label_en}: water came on {_count(point.supplied, 'day')}, "
            f"did not come on {point.no_supply}{extra_en}, no information for {point.unknown}."
        ),
        numbers={
            "days": days,
            f"{key}.supplied": point.supplied,
            f"{key}.no_supply": point.no_supply,
            f"{key}.partial": point.partial,
            f"{key}.dirty": point.dirty,
            f"{key}.unknown": point.unknown,
        },
    )


def _open_sentence(analytics: VillageAnalytics) -> _Sentence:
    """Open complaints, and how long the oldest has been open (days, or hours under a day)."""
    tickets = analytics.village.open_tickets
    count = len(tickets)
    if count == 0:
        return _Sentence(
            hi="Abhi koi shikayat khuli nahi hai.",
            en="No complaint is open now.",
            numbers={"open_complaints": 0},
        )
    oldest = max(t.age_hours for t in tickets)
    days, hours = int(oldest // 24), int(oldest)
    numbers: Numbers = {"open_complaints": count}
    if days >= 1:
        age_hi, age_en = f"{days} din", _count(days, "day")
        numbers["oldest_open_days"] = days
    elif hours >= 1:
        age_hi, age_en = f"{hours} ghante", _count(hours, "hour")
        numbers["oldest_open_hours"] = hours
    else:
        age_hi, age_en = "kuch der", "under an hour"
    if count == 1:
        return _Sentence(
            hi=f"1 shikayat {age_hi} se khuli hai.",
            en=f"1 complaint is open, for {age_en}.",
            numbers=numbers,
        )
    return _Sentence(
        hi=f"{count} shikayat khuli hain, sabse purani {age_hi} se.",
        en=f"{count} complaints are open; the oldest for {age_en}.",
        numbers=numbers,
    )


def _closed_sentence(analytics: VillageAnalytics) -> _Sentence:
    """Complaints closed after households confirmed water, and the median repair time."""
    closed = analytics.tickets_closed_verified
    if closed == 0:
        return _Sentence(
            hi="Is dauran koi shikayat gharon ki pushti se band nahi hui.",
            en="No complaint was closed with household confirmation in this period.",
            numbers={"closed_verified": 0},
        )
    numbers: Numbers = {"closed_verified": closed}
    hi = f"{closed} shikayat gharon ki pushti ke baad band hui"
    en = f"{_count(closed, 'complaint')} closed after households confirmed water was back"
    median = analytics.median_repair_hours
    if median is not None:
        hours = int(median + 0.5)
        if hours >= 1:
            hi += f", marammat mein aam taur par {hours} ghante lage"
            en += f"; median repair time {_count(hours, 'hour')}"
            numbers["median_repair_hours"] = hours
        else:
            hi += ", marammat mein aam taur par ek ghante se kam laga"
            en += "; median repair time under an hour"
    return _Sentence(hi=hi + ".", en=en + ".", numbers=numbers)


def _closing() -> _Sentence:
    return _Sentence(hi=CLOSING_HI, en=CLOSING_EN)


def _count(n: int, noun: str) -> str:
    """'1 day', '3 days' (English only; the Hindi nouns used here do not change)."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
