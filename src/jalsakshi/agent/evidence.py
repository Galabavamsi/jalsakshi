"""Gram Sabha brief types and the deterministic facts both the agent and the template use.

Pure code: no Strands or AWS imports. Every number the brief may show is derived here.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Final, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from jalsakshi.core.models import (
    DayStatus,
    DayStatusValue,
    SourceTag,
    Ticket,
    TicketReason,
    TicketState,
    Village,
)

IST: Final = timezone(timedelta(hours=5, minutes=30), "IST")

Number = int | float


class BriefSummary(BaseModel):
    """Computed numbers for one village and period (all counts are days or tickets)."""

    days: int = Field(ge=0)
    supplied: int = Field(ge=0)
    no_supply: int = Field(ge=0)
    partial: int = Field(ge=0)
    dirty: int = Field(ge=0)
    unverified: int = Field(ge=0)
    tickets_opened: int = Field(ge=0)
    tickets_closed_verified: int = Field(ge=0)
    median_hours_to_verified_fix: float | None = Field(default=None, ge=0)

    @field_validator("median_hours_to_verified_fix")
    @classmethod
    def _round_hours(cls, value: float | None) -> float | None:
        return None if value is None else round_hours(value)

    @property
    def supplied_pct(self) -> int | None:
        """Share of observed days with full supply, as a whole percent (None with no days)."""
        if self.days == 0:
            return None
        return int(100 * self.supplied / self.days + 0.5)

    def numbers(self) -> dict[str, Number | None]:
        """The summary plus derived values: exactly what the brief may cite."""
        return {**self.model_dump(), "supplied_pct": self.supplied_pct}

    @classmethod
    def from_records(
        cls,
        days: Sequence[DayStatus],
        tickets: Sequence[Ticket],
        period_from: date,
        period_to: date,
    ) -> BriefSummary:
        """Aggregate stored day statuses and tickets for the period (IST dates, inclusive)."""
        in_period = [d for d in days if period_from <= d.date <= period_to]
        count = {value: sum(d.status == value for d in in_period) for value in DayStatusValue}
        opened = [t for t in tickets if period_from <= to_ist_date(t.opened_at) <= period_to]
        closed_hours = [
            hours
            for t in tickets
            if _closed_within(t, period_from, period_to)
            and (hours := hours_to_verified_fix(t)) is not None
        ]
        return cls(
            days=len(in_period),
            supplied=count[DayStatusValue.SUPPLIED],
            no_supply=count[DayStatusValue.NO_SUPPLY],
            partial=count[DayStatusValue.PARTIAL],
            dirty=count[DayStatusValue.DIRTY],
            unverified=count[DayStatusValue.UNVERIFIED],
            tickets_opened=len(opened),
            tickets_closed_verified=len(closed_hours),
            median_hours_to_verified_fix=statistics.median(closed_hours) if closed_hours else None,
        )


class BriefInput(BaseModel):
    """Everything the brief may say. Nothing outside this reaches the agent."""

    village: Village
    period_from: date
    period_to: date
    summary: BriefSummary
    tickets: list[Ticket] = Field(default_factory=list)
    sources: list[SourceTag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_period(self) -> Self:
        if self.period_from > self.period_to:
            raise ValueError("period_from must not be after period_to")
        return self

    def all_sources(self) -> list[SourceTag]:
        """Given sources plus the village's claimed-status source, without duplicates."""
        merged = list(self.sources)
        claimed = self.village.claimed_source
        if claimed is not None and claimed not in merged:
            merged.append(claimed)
        return merged


class Brief(BaseModel):
    """The Gram Sabha evidence sheet, as served by ``GET /api/villages/{vid}/brief``."""

    markdown_hi: str
    numbers: dict[str, Number | None]
    generated_by: Literal["agent", "template"]
    sources: list[SourceTag]
    generated_at: datetime
    model_id: str | None = None


@dataclass(frozen=True, slots=True)
class TicketFacts:
    """One ticket reduced to the facts a brief may cite."""

    id: str
    reason: TicketReason
    state: TicketState
    opened_on: date
    closed_verified_on: date | None
    hours_to_verified_fix: float | None


def round_hours(value: float) -> float:
    """Hours are shown with one decimal everywhere, so they compare exactly."""
    return round(float(value), 1)


def to_ist_date(moment: datetime) -> date:
    """Calendar date in IST; naive datetimes are treated as UTC."""
    return _aware(moment).astimezone(IST).date()


def closed_verified_at(ticket: Ticket) -> datetime | None:
    """When households confirmed the fix, or None if the ticket is not CLOSED_VERIFIED."""
    for event in reversed(ticket.events):
        if event.to_state == TicketState.CLOSED_VERIFIED:
            return event.at
    return ticket.updated_at if ticket.state == TicketState.CLOSED_VERIFIED else None


def hours_to_verified_fix(ticket: Ticket) -> float | None:
    """Hours from opening to household-verified closure, one decimal."""
    closed = closed_verified_at(ticket)
    if closed is None:
        return None
    seconds = (_aware(closed) - _aware(ticket.opened_at)).total_seconds()
    return round_hours(max(seconds, 0.0) / 3600)


def ticket_facts(tickets: Sequence[Ticket]) -> list[TicketFacts]:
    """Tickets as citeable facts, oldest first (stable order for determinism)."""
    ordered = sorted(tickets, key=lambda t: (_aware(t.opened_at), t.id))
    return [
        TicketFacts(
            id=t.id,
            reason=t.reason,
            state=t.state,
            opened_on=to_ist_date(t.opened_at),
            closed_verified_on=_maybe_ist_date(closed_verified_at(t)),
            hours_to_verified_fix=hours_to_verified_fix(t),
        )
        for t in ordered
    ]


def allowed_numbers(inp: BriefInput) -> set[Number]:
    """Every number the brief text may contain (dates and identifiers are handled separately)."""
    values: set[Number] = {v for v in inp.summary.numbers().values() if v is not None}
    values.add(len(inp.tickets))
    values.update(
        f.hours_to_verified_fix
        for f in ticket_facts(inp.tickets)
        if f.hours_to_verified_fix is not None
    )
    return values


def identifiers(inp: BriefInput) -> list[str]:
    """Strings that may contain digits but are names or ids, not quantities."""
    village = inp.village
    candidates = [
        village.id,
        village.name,
        village.block,
        village.district,
        village.imis_village_code,
        *(t.id for t in inp.tickets),
        *(s.source for s in inp.all_sources()),
        *(s.url for s in inp.all_sources()),
    ]
    return [c for c in candidates if c]


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _closed_within(ticket: Ticket, period_from: date, period_to: date) -> bool:
    closed = closed_verified_at(ticket)
    return closed is not None and period_from <= to_ist_date(closed) <= period_to


def _maybe_ist_date(moment: datetime | None) -> date | None:
    return None if moment is None else to_ist_date(moment)
