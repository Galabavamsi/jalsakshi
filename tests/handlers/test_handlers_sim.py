"""Web-phone simulator routes: console calls, workflow pick-up, operator calls, Cedar denies."""

from __future__ import annotations

from typing import Any

from jalsakshi.core.models import (
    CallOutcome,
    CapturedVia,
    DayStatusValue,
    Purpose,
    TicketReason,
    TicketState,
    WaterAnswer,
)
from jalsakshi.core.tickets import TicketEventKind, new_ticket
from jalsakshi.handlers import calls, sfn_tasks, sim, tickets
from jalsakshi.store import Repository

from .fakes import DAY, NOW, VID, FakeSfn, HttpEvent, LambdaContext, call

CLAIMS = {"username": "alice", "cognito:groups": "[SARPANCH]"}


def start(body: dict[str, Any]) -> tuple[int, Any]:
    status, payload, _ = call(sim.handler, HttpEvent("POST", "/sim/calls", body, claims=CLAIMS))
    return status, payload


def press(call_id: str, body: dict[str, Any]) -> tuple[int, Any]:
    event = HttpEvent("POST", f"/sim/calls/{call_id}/input", body, claims=CLAIMS)
    status, payload, _ = call(sim.handler, event)
    return status, payload


def test_daily_call_end_to_end(seeded: Repository) -> None:
    status, body = start({"household_id": "h1", "purpose": "DAILY"})
    assert status == 200
    call_id = body["call_id"]
    kinds = [a["type"] for a in body["actions"]]
    assert kinds == ["play", "get_digits"]
    assert body["actions"][0]["audio_url"].startswith("https://cdn.example.test/prompts/hi/")
    for digits in ("1", "6", "1"):
        status, step = press(call_id, {"digits": digits})
        assert status == 200 and step["done"] is False
    status, step = press(call_id, {"digits": "#"})
    assert step["done"] is True and step["actions"][-1]["type"] == "hangup"
    [stored] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert stored.call_id == call_id and stored.captured_via is CapturedVia.SIMULATOR
    assert (stored.outcome, stored.water, stored.hours) == (
        CallOutcome.ANSWERED,
        WaterAnswer.YES,
        6,
    )
    day = seeded.get_day_status(VID, DAY)
    assert day is not None and day.status is DayStatusValue.UNVERIFIED
    assert day.counts.answered == 1
    status, again = press(call_id, {"digits": "1"})
    assert status == 200 and again == {"actions": [{"type": "hangup"}], "done": True}


def test_second_daily_call_same_day_is_denied(seeded: Repository) -> None:
    _, body = start({"household_id": "h1", "purpose": "DAILY"})
    press(body["call_id"], {"digits": "2"})
    press(body["call_id"], {"digits": "3"})
    press(body["call_id"], {"digits": "#"})
    status, denied = start({"household_id": "h1", "purpose": "DAILY"})
    assert status == 403
    assert denied["denied"] is True and denied["policy_id"] == "one-call-per-day"
    assert denied["reason_hi"] and denied["reason_en"]


def test_household_without_consent_is_denied(seeded: Repository) -> None:
    status, denied = start({"household_id": "h3", "purpose": "DAILY"})
    assert status == 403 and denied["policy_id"] == "consent-required"


def test_unknown_household_and_call(seeded: Repository) -> None:
    status, body = start({"household_id": "ghost", "purpose": "DAILY"})
    assert status == 404 and body["error"]["code"] == "not_found"
    status, body = press("sim_nope", {"digits": "1"})
    assert status == 404


def test_invalid_bodies_are_400(seeded: Repository) -> None:
    status, body = start({"household_id": "h1", "operator_id": "op-1", "purpose": "DAILY"})
    assert status == 400 and body["error"]["code"] == "invalid_request"
    _, started = start({"household_id": "h1", "purpose": "DAILY"})
    status, body = press(started["call_id"], {"digits": "12345678901"})
    assert status == 400


def test_timeouts_reprompt_then_move_on(seeded: Repository) -> None:
    _, body = start({"household_id": "h2", "purpose": "DAILY"})
    _, first = press(body["call_id"], {"timeout": True})
    assert [a["type"] for a in first["actions"]] == ["play", "get_digits"]
    _, second = press(body["call_id"], {"timeout": True})
    assert second["actions"][-1]["type"] == "record"
    _, done = press(body["call_id"], {"digits": "#"})
    assert done["done"] is True
    [stored] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert stored.outcome is CallOutcome.UNREACHABLE and stored.water is None


def test_pending_workflow_call_is_picked_up_and_resumes_the_task(
    seeded: Repository, sfn_fake: FakeSfn
) -> None:
    item = {
        "village_id": VID,
        "household_id": "h1",
        "date": DAY.isoformat(),
        "purpose": "DAILY",
        "attempt": 1,
    }
    placed = sfn_tasks.place_call({"task_token": "tok-7", "input": item}, LambdaContext())
    _, body = start({"household_id": "h1", "purpose": "DAILY"})
    assert body["call_id"] == placed["call_id"]
    press(body["call_id"], {"digits": "2"})
    press(body["call_id"], {"digits": "1"})
    _, done = press(body["call_id"], {"digits": "#"})
    assert done["done"] is True
    assert sfn_fake.outputs_for("tok-7") == [
        {"call_id": placed["call_id"], "outcome": "ANSWERED", "answered": True}
    ]
    assert calls.find_pending(seeded, "h1", Purpose.DAILY) is None
    assert seeded.get_day_status(VID, DAY) is None  # the workflow reconciles, not the call


def test_operator_call_needs_an_open_ticket(seeded: Repository) -> None:
    status, body = start({"operator_id": "op-1", "purpose": "OPERATOR"})
    assert status == 409 and body["error"]["code"] == "no_open_ticket"


def test_operator_reports_fix_by_keypad(seeded: Repository, sfn_fake: FakeSfn) -> None:
    ticket = seeded.open_ticket_if_none(new_ticket(VID, TicketReason.DIRTY, NOW))
    assert ticket is not None
    tickets.apply_event(seeded, ticket.id, TicketEventKind.NOTIFIED, "test")
    tickets.register_wait(seeded, ticket.id, "fix-3", "operator_fix")
    status, body = start({"operator_id": "op-1", "purpose": "OPERATOR"})
    assert status == 200
    prompts = [a.get("prompt_key") for a in body["actions"] if a["type"] == "play"]
    assert prompts[0] == "operator.greet"
    _, done = press(body["call_id"], {"digits": "1"})
    assert done["done"] is True
    stored = tickets.load_ticket(seeded, ticket.id)
    assert stored.state is TicketState.OPERATOR_REPORTED_FIXED
    assert stored.events[-1].actor == "operator:op-1"
    assert sfn_fake.outputs_for("fix-3")[0]["via"] == "call"


def test_operator_not_yet_keeps_ticket_assigned(seeded: Repository) -> None:
    ticket = seeded.open_ticket_if_none(new_ticket(VID, TicketReason.NO_SUPPLY, NOW))
    assert ticket is not None
    tickets.apply_event(seeded, ticket.id, TicketEventKind.NOTIFIED, "test")
    _, body = start({"operator_id": "op-1", "purpose": "OPERATOR"})
    _, done = press(body["call_id"], {"digits": "2"})
    assert done["done"] is True
    assert tickets.load_ticket(seeded, ticket.id).state is TicketState.ASSIGNED
