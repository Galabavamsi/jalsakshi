"""Repair-ticket state machine (ARCHITECTURE.md §5). Pure: every call returns a new Ticket.

    OPEN --NOTIFIED--> ASSIGNED --OPERATOR_FIXED--> OPERATOR_REPORTED_FIXED
    OPERATOR_REPORTED_FIXED --VERIFY_STARTED--> VERIFYING
    VERIFYING --VERIFIED_OK--> CLOSED_VERIFIED       (a quorum of households confirmed water)
    VERIFYING --VERIFY_FAILED--> REOPENED --NOTIFIED--> ASSIGNED
    any unresolved state --ESCALATED--> ESCALATED    (48 h with no state change; PHED simulated)
    ESCALATED --OPERATOR_FIXED--> OPERATOR_REPORTED_FIXED   (escalated repairs are still verified)
    NOTE is allowed in every state and never changes it.

Cedar (policy/) guards who may apply the sensitive events; this module only knows states.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from jalsakshi.core.ids import new_id
from jalsakshi.core.models import (
    BlockerCode,
    Ticket,
    TicketEvent,
    TicketOrigin,
    TicketReason,
    TicketState,
)

ESCALATION_HOURS = 48


class TicketEventKind(StrEnum):
    NOTIFIED = "NOTIFIED"
    OPERATOR_FIXED = "OPERATOR_FIXED"
    VERIFY_STARTED = "VERIFY_STARTED"
    VERIFIED_OK = "VERIFIED_OK"
    VERIFY_FAILED = "VERIFY_FAILED"
    ESCALATED = "ESCALATED"
    NOTE = "NOTE"


@dataclass(frozen=True, slots=True)
class Denied:
    """A transition that the state machine refuses, with a plain-language reason."""

    reason: str


OPEN_STATES: frozenset[TicketState] = frozenset(TicketState) - {TicketState.CLOSED_VERIFIED}
"""States in which a ticket still counts as open (blocks a second ticket for the village)."""

ESCALATABLE_STATES: frozenset[TicketState] = OPEN_STATES - {TicketState.ESCALATED}
"""Unresolved states that escalate after `ESCALATION_HOURS` without a state change."""

_TRANSITIONS: dict[TicketEventKind, dict[TicketState, TicketState]] = {
    TicketEventKind.NOTIFIED: {
        TicketState.OPEN: TicketState.ASSIGNED,
        TicketState.REOPENED: TicketState.ASSIGNED,
    },
    TicketEventKind.OPERATOR_FIXED: {
        TicketState.ASSIGNED: TicketState.OPERATOR_REPORTED_FIXED,
        TicketState.ESCALATED: TicketState.OPERATOR_REPORTED_FIXED,
    },
    TicketEventKind.VERIFY_STARTED: {
        TicketState.OPERATOR_REPORTED_FIXED: TicketState.VERIFYING,
    },
    TicketEventKind.VERIFIED_OK: {TicketState.VERIFYING: TicketState.CLOSED_VERIFIED},
    TicketEventKind.VERIFY_FAILED: {TicketState.VERIFYING: TicketState.REOPENED},
    TicketEventKind.ESCALATED: dict.fromkeys(ESCALATABLE_STATES, TicketState.ESCALATED),
    TicketEventKind.NOTE: {state: state for state in TicketState},
}


def new_ticket(
    village_id: str,
    reason: TicketReason,
    at: datetime,
    *,
    ticket_id: str | None = None,
    water_point_id: str | None = None,
    origin: TicketOrigin = TicketOrigin.RECONCILE,
    reporters: Sequence[str] = (),
    quorum: int | None = None,
    number: int | None = None,
) -> Ticket:
    """Create an OPEN ticket opened at `at` (id from `new_id("tkt")` unless given)."""
    _require_aware(at)
    return Ticket(
        id=ticket_id or new_id("tkt", at=at),
        village_id=village_id,
        reason=TicketReason(reason),
        state=TicketState.OPEN,
        opened_at=at,
        updated_at=at,
        water_point_id=water_point_id,
        origin=TicketOrigin(origin),
        reporters=list(dict.fromkeys(reporters)),
        quorum=quorum,
        number=number,
    )


def report_quorum(point_quorum: int, reporters: int) -> int:
    """Households needed to close a resident-reported ticket: never more than reported it.

    One family's complaint can be closed by that family's own confirmation; a problem many
    families reported needs the point's usual quorum (§15.5).
    """
    if point_quorum < 1:
        raise ValueError(f"quorum must be at least 1, got {point_quorum}")
    return max(1, min(point_quorum, reporters))


def with_reporter(ticket: Ticket, household_id: str, point_quorum: int) -> Ticket:
    """Add a reporting household; for resident-opened tickets the quorum grows with them.

    Pure bookkeeping, no event (the caller adds a NOTE). Returns the ticket unchanged when the
    household is already a reporter.
    """
    if household_id in ticket.reporters:
        return ticket
    reporters = [*ticket.reporters, household_id]
    quorum = ticket.quorum
    if ticket.origin is not TicketOrigin.RECONCILE:
        quorum = report_quorum(point_quorum, len(reporters))
    return ticket.model_copy(update={"reporters": reporters, "quorum": quorum})


def closing_quorum(ticket: Ticket, default: int) -> int:
    """Households that must confirm water before this ticket may close."""
    return ticket.quorum or default


BLOCKER_KEYS: dict[str, BlockerCode] = {
    "2": BlockerCode.PARTS_NEEDED,
    "3": BlockerCode.NO_POWER,
    "4": BlockerCode.PIPE_BROKEN,
    "5": BlockerCode.NOT_MINE,
}
"""Operator call keys 2-5 (§15.7); 1 means fixed."""


def allowed_events(state: TicketState) -> frozenset[TicketEventKind]:
    """Event kinds that `transition` accepts in `state` (e.g. to show console buttons)."""
    return frozenset(kind for kind, moves in _TRANSITIONS.items() if TicketState(state) in moves)


def transition(
    ticket: Ticket,
    kind: TicketEventKind | str,
    actor: str,
    at: datetime,
    detail: Mapping[str, Any] | None = None,
) -> Ticket | Denied:
    """Apply one event: return a new Ticket with the event appended, or Denied with a reason.

    `at` must be timezone-aware and not earlier than `ticket.updated_at`, so the event log stays
    in time order. The input ticket is never modified.
    """
    _require_aware(at)
    try:
        event_kind = TicketEventKind(kind)
    except ValueError:
        return Denied(f"Unknown ticket event {kind!r}.")
    if not actor.strip():
        return Denied("Every ticket event needs an actor.")
    if at < ticket.updated_at:
        return Denied("Event time is earlier than the ticket's last update.")
    target = _TRANSITIONS[event_kind].get(ticket.state)
    if target is None:
        return Denied(f"{event_kind} is not allowed while the ticket is {ticket.state}.")
    event = TicketEvent(
        at=at,
        actor=actor,
        kind=event_kind.value,
        from_state=ticket.state,
        to_state=target,
        detail=dict(detail or {}),
    )
    return ticket.model_copy(
        update={"state": target, "updated_at": at, "events": [*ticket.events, event]}
    )


def is_open(ticket: Ticket) -> bool:
    """True until the ticket is CLOSED_VERIFIED."""
    return ticket.state in OPEN_STATES


def last_progress_at(ticket: Ticket) -> datetime:
    """Time of the last state change (NOTE events do not count), or `opened_at` if none."""
    changes = [
        event.at
        for event in ticket.events
        if event.to_state is not None and event.to_state != event.from_state
    ]
    return max(changes, default=ticket.opened_at)


def needs_escalation(ticket: Ticket, now: datetime, hours: int = ESCALATION_HOURS) -> bool:
    """True when an unresolved ticket has gone `hours` without a state change."""
    if hours <= 0:
        raise ValueError(f"hours must be positive, got {hours}")
    if ticket.state not in ESCALATABLE_STATES:
        return False
    return now - last_progress_at(ticket) >= timedelta(hours=hours)


def _require_aware(at: datetime) -> None:
    """Ticket times are stored and compared as aware datetimes."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("naive datetime: ticket event times must be timezone-aware")
