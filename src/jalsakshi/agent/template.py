"""Deterministic Hindi rendering for the Gram Sabha brief.

``template_markdown`` is the always-valid fallback. ``banner`` and ``sources_section`` are also
wrapped around the agent's text, so source and freshness labels never depend on a model.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Final

from jalsakshi.agent.evidence import BriefInput, TicketFacts, ticket_facts, to_ist_date
from jalsakshi.core.models import Freshness, SourceTag, TicketReason, TicketState

NOT_AVAILABLE: Final = "जानकारी उपलब्ध नहीं"
DASH: Final = "—"

HINDI_MONTHS: Final = (
    "जनवरी",
    "फ़रवरी",
    "मार्च",
    "अप्रैल",
    "मई",
    "जून",
    "जुलाई",
    "अगस्त",
    "सितंबर",
    "अक्टूबर",
    "नवंबर",
    "दिसंबर",
)

REASON_HI: Final = {
    TicketReason.NO_SUPPLY: "पानी नहीं आया",
    TicketReason.DIRTY: "गंदा पानी",
}

STATE_HI: Final = {
    TicketState.OPEN: "खुली",
    TicketState.ASSIGNED: "नल जल मित्र को सौंपी गई",
    TicketState.OPERATOR_REPORTED_FIXED: "ऑपरेटर ने ठीक बताया, पुष्टि बाकी",
    TicketState.VERIFYING: "घरों से पुष्टि हो रही है",
    TicketState.CLOSED_VERIFIED: "घरों की पुष्टि से बंद",
    TicketState.REOPENED: "दोबारा खुली",
    TicketState.ESCALATED: "सरपंच को भेजी गई",
}

FRESHNESS_HI: Final = {
    Freshness.LIVE: "लाइव",
    Freshness.DAILY: "दैनिक",
    Freshness.ANNUAL: "वार्षिक",
    Freshness.MODEL: "मॉडल अनुमान",
    Freshness.SIMULATED: "सिम्युलेटेड",
    Freshness.REPLAY: "रीप्ले",
}

NOT_REAL: Final = frozenset({Freshness.SIMULATED, Freshness.REPLAY})

FOOTER: Final = "_यह पत्र JalSakshi ने घरों के फ़ोन जवाबों से बनाया है। हर संख्या ऊपर दिए स्रोतों से है।_"


def hindi_date(day: date) -> str:
    """Date as "7 अक्टूबर 2026"."""
    return f"{day.day} {HINDI_MONTHS[day.month - 1]} {day.year}"


def yes_no(value: bool | None) -> str:
    """Hindi yes / no / unknown."""
    if value is None:
        return NOT_AVAILABLE
    return "हाँ" if value else "नहीं"


def template_markdown(inp: BriefInput) -> str:
    """The complete deterministic sheet: same input, same text."""
    sections = [
        banner(inp),
        _title(inp),
        _summary_section(inp),
        _days_section(inp),
        _tickets_section(inp),
        _discussion_section(inp),
        sources_section(inp),
    ]
    return "\n\n".join(s for s in sections if s) + "\n"


def wrap_agent_markdown(inp: BriefInput, body: str) -> str:
    """Agent prose with the deterministic banner and sources section around it."""
    return "\n\n".join(s for s in (banner(inp), body.strip(), sources_section(inp)) if s) + "\n"


def banner(inp: BriefInput) -> str:
    """Visible notice when any source is simulated or replayed; empty otherwise."""
    if not any(s.freshness in NOT_REAL for s in inp.all_sources()):
        return ""
    return "> **सूचना:** इस पत्र में सिम्युलेटेड या रीप्ले डेटा शामिल है (simulated / replay), असली रिकॉर्ड नहीं।"


def sources_section(inp: BriefInput) -> str:
    """Every source with its freshness, observation and fetch dates."""
    lines = [_source_line(s) for s in inp.all_sources()] or ["- स्रोत की जानकारी नहीं दी गई।"]
    return "\n".join(["## स्रोत", *lines, "", FOOTER])


def _source_line(source: SourceTag) -> str:
    parts = [f"{FRESHNESS_HI[source.freshness]} ({source.freshness.value})"]
    if source.observed_at is not None:
        parts.append(f"देखा गया: {_hindi_day(source.observed_at)}")
    parts.append(f"लिया गया: {_hindi_day(source.fetched_at)}")
    if source.url:
        parts.append(f"<{source.url}>")
    return f"- **{source.source}**: " + "; ".join(parts)


def _title(inp: BriefInput) -> str:
    village = inp.village
    return "\n".join(
        [
            f"# जल साक्ष्य पत्र: {village.name}",
            "",
            f"**अवधि:** {hindi_date(inp.period_from)} से {hindi_date(inp.period_to)} तक  ",
            f"**ब्लॉक / ज़िला:** {village.block}, {village.district}",
        ]
    )


def _summary_section(inp: BriefInput) -> str:
    village, summary = inp.village, inp.summary
    cite = _cite([village.claimed_source] if village.claimed_source else [])
    lines = [
        "## सारांश",
        f"- राज्य का हर घर जल दावा: {yes_no(village.claimed_hgj)}{cite}",
        f"- हर घर जल प्रमाणित: {yes_no(village.hgj_certified)}{cite}",
    ]
    if summary.days == 0:
        lines.append("- इस अवधि में घरों से कोई जानकारी नहीं मिली।")
    else:
        lines.append(
            f"- घरों ने {summary.days} दिनों की जानकारी दी। इनमें {summary.supplied} दिन "
            f"पूरा पानी आया ({summary.supplied_pct}% दिन)।"
        )
    return "\n".join(lines)


def _days_section(inp: BriefInput) -> str:
    s = inp.summary
    rows = [
        ("पूरा पानी आया", s.supplied),
        ("आंशिक पानी", s.partial),
        ("पानी नहीं आया", s.no_supply),
        ("गंदा पानी", s.dirty),
        ("पुष्टि नहीं (पर्याप्त जवाब नहीं)", s.unverified),
        ("कुल दिन", s.days),
    ]
    table = ["| दिन की स्थिति | दिन |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows)]
    cited = _names(inp.sources) or "नीचे देखें"
    return "\n".join(["## घरों की गवाही", *table, "", f"स्रोत: {cited}"])


def _tickets_section(inp: BriefInput) -> str:
    s = inp.summary
    median = s.median_hours_to_verified_fix
    median_text = f"{median} घंटे" if median is not None else NOT_AVAILABLE
    lines = [
        "## मरम्मत शिकायतें",
        f"- इस अवधि में खुली शिकायतें: {s.tickets_opened}",
        f"- घरों की पुष्टि से बंद शिकायतें: {s.tickets_closed_verified}",
        f"- पुष्टि सहित मरम्मत का मध्य समय: {median_text}",
    ]
    facts = ticket_facts(inp.tickets)
    if not facts:
        return "\n".join([*lines, "- कोई शिकायत सूची में नहीं है।"])
    header = "| शिकायत | कारण | स्थिति | खुली | पुष्टि से बंद | घंटे |"
    table = [header, "|---|---|---|---|---|---|", *(_ticket_row(f) for f in facts)]
    return "\n".join([*lines, "", *table])


def _ticket_row(f: TicketFacts) -> str:
    closed = hindi_date(f.closed_verified_on) if f.closed_verified_on else DASH
    hours = f.hours_to_verified_fix if f.hours_to_verified_fix is not None else DASH
    cells = [f"`{f.id}`", REASON_HI[f.reason], STATE_HI[f.state], hindi_date(f.opened_on)]
    return "| " + " | ".join([*cells, closed, str(hours)]) + " |"


def _discussion_section(inp: BriefInput) -> str:
    village, s = inp.village, inp.summary
    points: list[str] = []
    if s.no_supply or s.dirty:
        points.append("जिन दिनों पानी नहीं आया या गंदा आया, उनका कारण नल जल मित्र से पूछें।")
    if any(t.state != TicketState.CLOSED_VERIFIED for t in inp.tickets):
        points.append("खुली शिकायतें घरों की पुष्टि के बाद ही बंद मानी जाएँ।")
    if village.claimed_hgj and (s.no_supply or s.partial or s.dirty):
        points.append("हर घर जल प्रमाणन से पहले घरों की यह गवाही देखी जाए।")
    if s.unverified:
        points.append("जिन दिनों पुष्टि नहीं हुई, वहाँ और घरों को जोड़ने पर विचार करें।")
    if not points:
        points.append("घरों से रोज़ की जानकारी जारी रखें।")
    return "\n".join(["## ग्राम सभा में चर्चा के बिंदु", *(f"- {p}" for p in points)])


def _names(sources: Sequence[SourceTag]) -> str:
    return "; ".join(s.source for s in sources)


def _cite(sources: Sequence[SourceTag]) -> str:
    names = _names(sources)
    return f" (स्रोत: {names})" if names else ""


def _hindi_day(moment: datetime) -> str:
    return hindi_date(to_ist_date(moment))
