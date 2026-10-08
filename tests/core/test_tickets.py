from datetime import datetime, timedelta
from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from jalsakshi.core.ids import id_timestamp
from jalsakshi.core.models import Ticket, TicketEvent, TicketReason, TicketState
from jalsakshi.core.tickets import (
    ESCALATABLE_STATES,
    OPEN_STATES,
    Denied,
    TicketEventKind,
    allowed_events,
    is_open,
    last_progress_at,
    needs_escalation,
    new_ticket,
    transition,
)

from .helpers import T0

S = TicketState
K = TicketEventKind
UNRESOLVED = (S.OPEN, S.ASSIGNED, S.OPERATOR_REPORTED_FIXED, S.VERIFYING, S.REOPENED)

# The §5 diagram, written out independently of the implementation's table.
EXPECTED: dict[tuple[TicketState, TicketEventKind], TicketState] = {
    (S.OPEN, K.NOTIFIED): S.ASSIGNED,
    (S.REOPENED, K.NOTIFIED): S.ASSIGNED,
    (S.ASSIGNED, K.OPERATOR_FIXED): S.OPERATOR_REPORTED_FIXED,
    (S.ESCALATED, K.OPERATOR_FIXED): S.OPERATOR_REPORTED_FIXED,
    (S.OPERATOR_REPORTED_FIXED, K.VERIFY_STARTED): S.VERIFYING,
    (S.VERIFYING, K.VERIFIED_OK): S.CLOSED_VERIFIED,
    (S.VERIFYING, K.VERIFY_FAILED): S.REOPENED,
    **{(state, K.ESCALATED): S.ESCALATED for state in UNRESOLVED},
    **{(state, K.NOTE): state for state in S},
}
INVALID = [(state, kind) for state, kind in product(S, K) if (state, kind) not in EXPECTED]


def ticket_in(state: TicketState, *, updated_at: datetime = T0) -> Ticket:
    return Ticket(
        id="tkt_test",
        village_id="v1",
        reason=TicketReason.NO_SUPPLY,
        state=state,
        opened_at=T0,
        updated_at=updated_at,
    )


def run(ticket: Ticket, *kinds: TicketEventKind, start: datetime = T0) -> Ticket:
    """Apply events one hour apart, failing the test on any Denied."""
    for hour, kind in enumerate(kinds, start=1):
        result = transition(ticket, kind, "tester", start + timedelta(hours=hour))
        assert isinstance(result, Ticket), (kind, result)
        ticket = result
    return ticket


# --- every (state, event) pair ------------------------------------------------------------------


def test_table_covers_every_pair() -> None:
    assert len(EXPECTED) + len(INVALID) == len(S) * len(K)


@pytest.mark.parametrize(("state", "kind", "target"), [(*key, to) for key, to in EXPECTED.items()])
def test_valid_transition(state: TicketState, kind: TicketEventKind, target: TicketState) -> None:
    ticket = ticket_in(state)
    at = T0 + timedelta(minutes=5)
    result = transition(ticket, kind, "op:nal-jal-mitra", at, {"call_id": "c1"})
    assert isinstance(result, Ticket)
    assert (result.state, result.updated_at) == (target, at)
    assert result.events == [
        TicketEvent(
            at=at,
            actor="op:nal-jal-mitra",
            kind=kind.value,
            from_state=state,
            to_state=target,
            detail={"call_id": "c1"},
        )
    ]
    assert (ticket.state, ticket.updated_at, ticket.events) == (state, T0, [])  # input untouched


@pytest.mark.parametrize(("state", "kind"), INVALID)
def test_invalid_transition_is_denied(state: TicketState, kind: TicketEventKind) -> None:
    result = transition(ticket_in(state), kind, "system", T0)
    assert isinstance(result, Denied)
    assert kind.value in result.reason and state.value in result.reason


@pytest.mark.parametrize("state", list(S))
def test_allowed_events_matches_the_table(state: TicketState) -> None:
    assert allowed_events(state) == {kind for (s, kind) in EXPECTED if s == state}


# --- whole journeys -----------------------------------------------------------------------------


def test_happy_path_closes_only_after_verification() -> None:
    ticket = run(
        new_ticket("v1", TicketReason.NO_SUPPLY, T0, ticket_id="tkt_x"),
        K.NOTIFIED,
        K.OPERATOR_FIXED,
        K.VERIFY_STARTED,
        K.VERIFIED_OK,
    )
    assert ticket.state == S.CLOSED_VERIFIED
    assert [e.to_state for e in ticket.events] == [
        S.ASSIGNED,
        S.OPERATOR_REPORTED_FIXED,
        S.VERIFYING,
        S.CLOSED_VERIFIED,
    ]
    assert ticket.updated_at == T0 + timedelta(hours=4)
    assert not is_open(ticket)


def test_operator_fixed_alone_cannot_close() -> None:
    fixed = run(ticket_in(S.ASSIGNED), K.OPERATOR_FIXED)
    assert isinstance(transition(fixed, K.VERIFIED_OK, "op", T0 + timedelta(days=1)), Denied)


def test_failed_verification_reopens_and_loops() -> None:
    ticket = run(
        ticket_in(S.OPEN),
        K.NOTIFIED,
        K.OPERATOR_FIXED,
        K.VERIFY_STARTED,
        K.VERIFY_FAILED,
        K.NOTIFIED,
        K.OPERATOR_FIXED,
        K.VERIFY_STARTED,
        K.VERIFIED_OK,
    )
    assert [e.kind for e in ticket.events].count(K.VERIFY_FAILED) == 1
    assert S.REOPENED in [e.to_state for e in ticket.events]
    assert ticket.state == S.CLOSED_VERIFIED


def test_escalated_repair_must_still_be_verified() -> None:
    escalated = run(ticket_in(S.ASSIGNED), K.ESCALATED)
    assert isinstance(transition(escalated, K.VERIFIED_OK, "sim", T0 + timedelta(days=3)), Denied)
    closed = run(
        escalated, K.OPERATOR_FIXED, K.VERIFY_STARTED, K.VERIFIED_OK, start=T0 + timedelta(1)
    )
    assert closed.state == S.CLOSED_VERIFIED


def test_note_is_logged_without_changing_state() -> None:
    noted = transition(ticket_in(S.VERIFYING), K.NOTE, "console:varun", T0, {"text": "called"})
    assert isinstance(noted, Ticket)
    assert noted.state == S.VERIFYING
    assert noted.events[-1].from_state == noted.events[-1].to_state == S.VERIFYING


# --- guards -------------------------------------------------------------------------------------


def test_plain_string_kind_is_accepted() -> None:
    result = transition(ticket_in(S.OPEN), "NOTIFIED", "system", T0)
    assert isinstance(result, Ticket) and result.state == S.ASSIGNED


def test_unknown_kind_is_denied() -> None:
    result = transition(ticket_in(S.OPEN), "TELEPORT", "system", T0)
    assert isinstance(result, Denied) and "Unknown" in result.reason


@pytest.mark.parametrize("actor", ["", "   "])
def test_blank_actor_is_denied(actor: str) -> None:
    result = transition(ticket_in(S.OPEN), K.NOTIFIED, actor, T0)
    assert isinstance(result, Denied) and "actor" in result.reason


def test_event_before_last_update_is_denied() -> None:
    ticket = ticket_in(S.OPEN, updated_at=T0 + timedelta(hours=1))
    assert isinstance(transition(ticket, K.NOTIFIED, "system", T0), Denied)
    assert isinstance(transition(ticket, K.NOTIFIED, "system", T0 + timedelta(hours=1)), Ticket)


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        transition(ticket_in(S.OPEN), K.NOTIFIED, "system", datetime(2026, 10, 9, 11, 0))


def test_detail_is_copied() -> None:
    detail = {"call_id": "c1"}
    result = transition(ticket_in(S.OPEN), K.NOTIFIED, "system", T0, detail)
    detail["call_id"] = "changed"
    assert isinstance(result, Ticket) and result.events[0].detail == {"call_id": "c1"}


# --- creation and openness ----------------------------------------------------------------------


def test_new_ticket() -> None:
    ticket = new_ticket("v1", TicketReason.DIRTY, T0)
    assert ticket.id.startswith("tkt_") and id_timestamp(ticket.id) == T0
    assert (ticket.state, ticket.reason, ticket.events) == (S.OPEN, TicketReason.DIRTY, [])
    assert ticket.opened_at == ticket.updated_at == T0
    with pytest.raises(ValueError, match="naive"):
        new_ticket("v1", TicketReason.DIRTY, datetime(2026, 10, 9))


@pytest.mark.parametrize("state", list(S))
def test_is_open(state: TicketState) -> None:
    assert is_open(ticket_in(state)) is (state != S.CLOSED_VERIFIED)
    assert (state in OPEN_STATES) is (state != S.CLOSED_VERIFIED)


# --- escalation ---------------------------------------------------------------------------------


@pytest.mark.parametrize("state", UNRESOLVED)
def test_unresolved_ticket_escalates_at_48h(state: TicketState) -> None:
    ticket = ticket_in(state)
    assert not needs_escalation(ticket, T0 + timedelta(hours=47, minutes=59))
    assert needs_escalation(ticket, T0 + timedelta(hours=48))
    assert set(UNRESOLVED) == ESCALATABLE_STATES


@pytest.mark.parametrize("state", [S.CLOSED_VERIFIED, S.ESCALATED])
def test_resolved_or_escalated_never_escalates(state: TicketState) -> None:
    assert not needs_escalation(ticket_in(state), T0 + timedelta(days=30))


def test_state_change_resets_the_clock_but_a_note_does_not() -> None:
    assigned = run(ticket_in(S.OPEN), K.NOTIFIED)  # state change at T0+1h
    noted = transition(assigned, K.NOTE, "console", T0 + timedelta(hours=40))
    assert isinstance(noted, Ticket)
    assert last_progress_at(noted) == T0 + timedelta(hours=1)
    assert not needs_escalation(noted, T0 + timedelta(hours=48, minutes=59))
    assert needs_escalation(noted, T0 + timedelta(hours=49))


def test_last_progress_defaults_to_opened_at() -> None:
    assert last_progress_at(ticket_in(S.OPEN)) == T0


def test_custom_threshold_and_bad_threshold() -> None:
    assert needs_escalation(ticket_in(S.ASSIGNED), T0 + timedelta(hours=2), hours=2)
    with pytest.raises(ValueError, match="hours"):
        needs_escalation(ticket_in(S.ASSIGNED), T0, hours=0)


# --- any event sequence keeps a consistent, append-only log -------------------------------------


@settings(max_examples=300, deadline=None)
@given(st.lists(st.sampled_from(list(K)), max_size=30))
def test_random_event_sequences_follow_the_table(kinds: list[TicketEventKind]) -> None:
    ticket = new_ticket("v1", TicketReason.NO_SUPPLY, T0, ticket_id="tkt_p")
    applied = 0
    for minute, kind in enumerate(kinds):
        before = ticket
        result = transition(ticket, kind, "prop", T0 + timedelta(minutes=minute))
        if isinstance(result, Denied):
            assert (before.state, kind) not in EXPECTED
            continue
        assert result.state == EXPECTED[(before.state, kind)]
        assert result.events[:-1] == before.events
        applied += 1
        ticket = result
    assert len(ticket.events) == applied
    for earlier, later in zip(ticket.events, ticket.events[1:], strict=False):
        assert earlier.to_state == later.from_state and earlier.at <= later.at
