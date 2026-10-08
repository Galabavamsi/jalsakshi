"""Repair verification: do the households confirm the water is back? (ARCHITECTURE.md §4).

The operator's "fixed" is never trusted on its own. After it, the same households are called
with purpose VERIFY, and only their latest answers decide: any NO reopens the ticket, a quorum of
YES closes it, and anything else keeps it pending (retry, then escalate). PARTIAL neither
confirms nor reopens.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from jalsakshi.core.models import CallOutcome, CheckIn, Purpose, WaterAnswer
from jalsakshi.core.reconcile import is_answered, latest_attempts
from jalsakshi.core.tickets import TicketEventKind


class VerifyOutcome(StrEnum):
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    REOPENED = "REOPENED"
    PENDING = "PENDING"


class VerifyResult(BaseModel):
    """Outcome of one verification round, with the counts that justify it."""

    model_config = ConfigDict(frozen=True)

    outcome: VerifyOutcome
    yes: int
    no: int
    unreachable: int


_TICKET_EVENTS: dict[VerifyOutcome, TicketEventKind] = {
    VerifyOutcome.CLOSED_VERIFIED: TicketEventKind.VERIFIED_OK,
    VerifyOutcome.REOPENED: TicketEventKind.VERIFY_FAILED,
}


def evaluate_verification(
    checkins: Iterable[CheckIn], quorum: int, *, since: datetime | None = None
) -> VerifyResult:
    """Decide a verification round from VERIFY check-ins (latest attempt per household).

    Pass the check-ins of one ticket's village. `since` (usually the VERIFY_STARTED time) drops
    answers from earlier rounds, so an old NO cannot reopen a ticket that was fixed again.
    """
    if quorum < 1:
        raise ValueError(f"quorum must be at least 1, got {quorum}")
    rounds = (
        checkin
        for checkin in checkins
        if checkin.purpose == Purpose.VERIFY and (since is None or checkin.captured_at >= since)
    )
    latest = latest_attempts(rounds)
    answered = [checkin for checkin in latest if is_answered(checkin)]
    yes = sum(checkin.water == WaterAnswer.YES for checkin in answered)
    no = sum(checkin.water == WaterAnswer.NO for checkin in answered)
    unreachable = sum(checkin.outcome == CallOutcome.UNREACHABLE for checkin in latest)
    return VerifyResult(outcome=_outcome(yes, no, quorum), yes=yes, no=no, unreachable=unreachable)


def ticket_event_for(outcome: VerifyOutcome) -> TicketEventKind | None:
    """Map a verification outcome to the ticket event to apply (None while pending)."""
    return _TICKET_EVENTS.get(VerifyOutcome(outcome))


def _outcome(yes: int, no: int, quorum: int) -> VerifyOutcome:
    """Any NO reopens; otherwise a quorum of YES closes; otherwise keep waiting."""
    if no > 0:
        return VerifyOutcome.REOPENED
    if yes >= quorum:
        return VerifyOutcome.CLOSED_VERIFIED
    return VerifyOutcome.PENDING
