"""Step Functions task Lambdas: each task alone, then the whole loop through the glue."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from jalsakshi.core.models import (
    CallOutcome,
    CapturedVia,
    CleanAnswer,
    DayStatusValue,
    Purpose,
    TicketReason,
    TicketState,
    WaterAnswer,
)
from jalsakshi.core.tickets import TicketEventKind, new_ticket, transition
from jalsakshi.handlers import calls, config, sfn_tasks, tickets
from jalsakshi.handlers.dialer import DialError
from jalsakshi.store import Repository

from .fakes import DAY, NOW, PHONES, VID, Clock, FakeSfn, LambdaContext, checkin

CTX = LambdaContext()


def run(task: Any, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    event = {"task_token": token, "input": payload} if token else payload
    return task(event, CTX)


def item(hid: str = "h1", *, attempt: int = 1, purpose: str = "DAILY") -> dict[str, Any]:
    return {
        "village_id": VID,
        "household_id": hid,
        "date": DAY.isoformat(),
        "purpose": purpose,
        "attempt": attempt,
        "retries_left": 1,
        "ticket_id": None,
    }


def open_assigned_ticket(repo: Repository, reason: TicketReason = TicketReason.NO_SUPPLY) -> str:
    ticket = repo.open_ticket_if_none(new_ticket(VID, reason, NOW))
    assert ticket is not None
    tickets.apply_event(repo, ticket.id, TicketEventKind.NOTIFIED, "test")
    return ticket.id


def finish_sim_call(repo: Repository, call_id: str, digits: list[str]) -> None:
    """Drive a stored call through the engine like the simulator would."""
    from jalsakshi.voice import flow as ivr

    loaded = calls.load_call(repo, call_id)
    assert loaded is not None
    flow, _ = ivr.start(loaded.record.flow)
    done = False
    for key in digits:
        flow, _, done = ivr.on_input(flow, key)
    assert done
    record = loaded.record.model_copy(update={"flow": flow})
    calls.save_call(repo, record)
    calls.finish_call(repo, calls.LoadedCall(record, loaded.task_token), CapturedVia.SIMULATOR)


# --- CheckInRun tasks -----------------------------------------------------------------------------


def test_load_roster_lists_active_households_with_next_attempt(seeded: Repository) -> None:
    seeded.put_checkin(checkin("h2", water=None))
    out = run(sfn_tasks.load_roster, {"village_id": VID, "purpose": "DAILY"})
    assert out["village_id"] == VID and out["date"] == DAY.isoformat() and out["quorum"] == 2
    attempts = {h["household_id"]: h["attempt"] for h in out["households"]}
    assert attempts == {"h1": 1, "h2": 2, "h3": 1}
    assert all(h["retries_left"] == 1 for h in out["households"])


def test_load_roster_unknown_village_fails(seeded: Repository) -> None:
    with pytest.raises(sfn_tasks.TaskError):
        run(sfn_tasks.load_roster, {"village_id": "nope"})


def test_policy_check_allows_consented_household_in_hours(seeded: Repository) -> None:
    assert run(sfn_tasks.policy_check_call, item("h1"))["allowed"] is True


def test_policy_check_denies_without_consent(seeded: Repository) -> None:
    out = run(sfn_tasks.policy_check_call, item("h3"))
    assert out == {**out, "allowed": False, "policy_id": "consent-required"}
    assert out["reason_hi"]


def test_policy_check_allows_another_call_the_same_day(seeded: Repository) -> None:
    seeded.put_checkin(checkin("h1", water=None))
    assert run(sfn_tasks.policy_check_call, item("h1", attempt=2))["allowed"] is True
    seeded.put_checkin(checkin("h1", water=WaterAnswer.YES, attempt=2))
    assert run(sfn_tasks.policy_check_call, item("h1", attempt=3))["allowed"] is True


def test_policy_check_survives_an_unreadable_allowlist(
    seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied() -> frozenset[str]:
        raise PermissionError("ssm:GetParameter denied")

    monkeypatch.setattr(config, "allowed_numbers", denied)
    assert run(sfn_tasks.policy_check_call, item("h1"))["allowed"] is True


def test_policy_check_missing_household(seeded: Repository) -> None:
    out = run(sfn_tasks.policy_check_call, item("ghost"))
    assert out["allowed"] is False and out["policy_id"] == "household-missing"


def test_place_call_simulator_parks_token_and_pending_pointer(seeded: Repository) -> None:
    out = run(sfn_tasks.place_call, item("h1"), token="tok-1")
    assert out["status"] == "pending"
    call_id = out["call_id"]
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None and loaded.task_token == "tok-1"
    assert loaded.record.origin == "workflow" and loaded.record.attempt == 1
    pending = calls.find_pending(seeded, "h1", Purpose.DAILY)
    assert pending is not None and pending.record.call_id == call_id
    again = run(sfn_tasks.place_call, item("h1"), token="tok-2")
    assert again["call_id"] == call_id
    reloaded = calls.load_call(seeded, call_id)
    assert reloaded is not None and reloaded.task_token == "tok-2"


def test_place_call_requires_token(seeded: Repository) -> None:
    with pytest.raises(sfn_tasks.TaskError):
        run(sfn_tasks.place_call, item("h1"))


def vobiz_transport(sent: list[httpx.Request], status: int = 201) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, json={"request_uuid": "req-uuid-1", "message": "fired"})

    return httpx.MockTransport(respond)


def use_vobiz(
    monkeypatch: pytest.MonkeyPatch, sent: list[httpx.Request], status: int = 201
) -> None:
    monkeypatch.setenv("VOICE_PROVIDER", "vobiz")
    config.settings.cache_clear()
    config.use_http_client(httpx.Client(transport=vobiz_transport(sent, status)))


def test_place_call_vobiz_dials_once(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[httpx.Request] = []
    use_vobiz(monkeypatch, sent)
    out = run(sfn_tasks.place_call, item("h1"), token="tok-1")
    assert out["status"] == "dialled"
    assert len(sent) == 1
    body = json.loads(sent[0].content)
    assert body["to"] == PHONES[0] and body["from"] == "+918000000000"
    assert "/ivr/vobiz/s3cret-path-token/answer?call_id=" in body["answer_url"]
    assert sent[0].headers["X-Auth-ID"] == "MA_TEST"
    retry = run(sfn_tasks.place_call, item("h1"), token="tok-1b")
    assert retry["status"] == "already_dispatched" and len(sent) == 1
    loaded = calls.load_call(seeded, out["call_id"])
    assert loaded is not None and loaded.record.provider_call_uuid == "req-uuid-1"


def test_place_call_vobiz_refuses_numbers_off_the_allowlist(
    seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[httpx.Request] = []
    use_vobiz(monkeypatch, sent)
    seeded.put_household(
        seeded.get_household(VID, "h1").model_copy(update={"phone_e164": "+919999999999"})
    )
    with pytest.raises(DialError):
        run(sfn_tasks.place_call, item("h1"), token="tok-1")
    assert sent == []


def test_place_call_vobiz_http_error_fails_the_task(
    seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[httpx.Request] = []
    use_vobiz(monkeypatch, sent, status=401)
    with pytest.raises(DialError):
        run(sfn_tasks.place_call, item("h1"), token="tok-1")


def test_mark_unreachable_writes_unreachable_once(seeded: Repository) -> None:
    run(sfn_tasks.place_call, item("h1"), token="tok-1")
    state = {**item("h1"), "call_error": {"Error": "States.Timeout"}}
    out = run(sfn_tasks.mark_unreachable, state)
    assert out["answered"] is False and out["outcome"] == "UNREACHABLE"
    assert out["cause"] == "States.Timeout"
    stored = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert [(c.outcome, c.captured_via) for c in stored] == [
        (CallOutcome.UNREACHABLE, CapturedVia.SIMULATOR)
    ]
    assert calls.find_pending(seeded, "h1", Purpose.DAILY) is None
    run(sfn_tasks.mark_unreachable, state)
    assert len(seeded.list_checkins(VID, DAY, Purpose.DAILY)) == 1


def test_mark_unreachable_reports_a_call_that_finished_meanwhile(
    seeded: Repository, sfn_fake: FakeSfn
) -> None:
    placed = run(sfn_tasks.place_call, item("h1"), token="tok-1")
    sfn_fake.stale.add("tok-1")
    finish_sim_call(seeded, placed["call_id"], ["1", "4", "1", "#"])
    out = run(sfn_tasks.mark_unreachable, item("h1"))
    assert out["answered"] is True and out["outcome"] == "ANSWERED"


def test_reconcile_day_flags_no_supply(seeded: Repository) -> None:
    seeded.put_checkin(checkin("h1", water=WaterAnswer.NO))
    seeded.put_checkin(checkin("h2", water=WaterAnswer.NO))
    out = run(sfn_tasks.reconcile_day, {"village_id": VID, "date": DAY.isoformat()})
    assert out["status"] == "NO_SUPPLY" and out["ticket_reason"] == "NO_SUPPLY"
    assert out["ticket_id"].startswith("tkt_")
    stored = seeded.get_day_status(VID, DAY)
    assert stored is not None and stored.status is DayStatusValue.NO_SUPPLY


def test_reconcile_day_with_open_ticket_notes_instead_of_reopening(seeded: Repository) -> None:
    tid = open_assigned_ticket(seeded)
    seeded.put_checkin(checkin("h1", water=WaterAnswer.NO))
    seeded.put_checkin(checkin("h2", water=WaterAnswer.NO))
    out = run(sfn_tasks.reconcile_day, {"village_id": VID, "date": DAY.isoformat()})
    assert out["status"] == "NO_SUPPLY" and out["ticket_reason"] is None
    ticket = tickets.load_ticket(seeded, tid)
    assert ticket.events[-1].kind == "NOTE"
    assert ticket.events[-1].detail["note"] == "day_still_bad"


def test_a_different_problem_opens_its_own_ticket(seeded: Repository) -> None:
    open_assigned_ticket(seeded)  # NO_SUPPLY is open
    seeded.put_checkin(checkin("h1", water=WaterAnswer.YES, clean=CleanAnswer.NO))
    seeded.put_checkin(checkin("h2", water=WaterAnswer.YES, clean=CleanAnswer.NO))
    out = run(sfn_tasks.reconcile_day, {"village_id": VID, "date": DAY.isoformat()})
    assert out["status"] == "DIRTY" and out["ticket_reason"] == "DIRTY"
    dirty = tickets.load_ticket(seeded, out["ticket_id"])
    assert dirty.number is not None and sorted(dirty.reporters) == ["h1", "h2"]


# --- TicketFlow tasks -----------------------------------------------------------------------------


def test_open_ticket_once_per_village_and_replay_safe(seeded: Repository) -> None:
    payload = {"village_id": VID, "reason": "NO_SUPPLY", "ticket_id": "tkt_fixed_1"}
    first = run(sfn_tasks.open_ticket, payload)
    assert first == {"opened": True, "ticket_id": "tkt_fixed_1"}
    assert run(sfn_tasks.open_ticket, payload) == first
    other = run(sfn_tasks.open_ticket, {**payload, "ticket_id": "tkt_other"})
    assert other == {"opened": False, "ticket_id": "tkt_fixed_1"}


def test_notify_operator_assigns_and_waits(seeded: Repository) -> None:
    run(sfn_tasks.open_ticket, {"village_id": VID, "reason": "NO_SUPPLY", "ticket_id": "tkt_a"})
    out = run(sfn_tasks.notify_operator, {"ticket_id": "tkt_a"}, token="fix-1")
    assert out["status"] == "waiting"
    assert tickets.load_ticket(seeded, "tkt_a").state is TicketState.ASSIGNED
    wait = seeded.get_call_session(tickets.wait_key("tkt_a"))
    assert wait is not None and wait.task_token == "fix-1"
    pending = calls.find_pending(seeded, "op-1", Purpose.OPERATOR)
    assert pending is not None and pending.record.flow.ticket_id == "tkt_a"


def test_notify_operator_resumes_when_already_fixed(seeded: Repository, sfn_fake: FakeSfn) -> None:
    tid = open_assigned_ticket(seeded)
    tickets.apply_event(seeded, tid, TicketEventKind.OPERATOR_FIXED, "test")
    out = run(sfn_tasks.notify_operator, {"ticket_id": tid}, token="fix-1")
    assert out["status"] == "already_fixed"
    assert sfn_fake.outputs_for("fix-1") == [{"fixed": True, "state": "OPERATOR_REPORTED_FIXED"}]


def test_operator_fix_releases_the_wait(seeded: Repository, sfn_fake: FakeSfn) -> None:
    tid = open_assigned_ticket(seeded)
    tickets.register_wait(seeded, tid, "fix-9", "operator_fix")
    result = tickets.report_fixed(seeded, tid, "console:alice", "console", operator_id="op-1")
    assert not isinstance(result, tickets.Denied)
    assert result.state is TicketState.OPERATOR_REPORTED_FIXED
    assert sfn_fake.outputs_for("fix-9")[0]["fixed"] is True


def test_start_verification_calls_reporters_then_only_missing(seeded: Repository) -> None:
    seeded.put_checkin(checkin("h1", water=WaterAnswer.NO))
    seeded.put_checkin(checkin("h2", water=WaterAnswer.NO))
    tid = open_assigned_ticket(seeded)
    tickets.apply_event(seeded, tid, TicketEventKind.OPERATOR_FIXED, "test")
    first = run(sfn_tasks.start_verification, {"ticket_id": tid, "verify": {"round": 0}})
    assert first["round"] == 1 and first["skip"] is False
    assert [h["household_id"] for h in first["households"]] == ["h1", "h2"]
    assert all(h["purpose"] == "VERIFY" and h["retries_left"] == 0 for h in first["households"])
    assert tickets.load_ticket(seeded, tid).state is TicketState.VERIFYING
    seeded.put_checkin(checkin("h1", purpose=Purpose.VERIFY, at=NOW.replace(hour=6)))
    second = run(sfn_tasks.start_verification, {"ticket_id": tid, "verify": first})
    assert second["round"] == 2
    assert [h["household_id"] for h in second["households"]] == ["h2"]


def test_start_verification_skips_closed_ticket(seeded: Repository) -> None:
    tid = open_assigned_ticket(seeded)
    ticket = tickets.load_ticket(seeded, tid)
    for kind in (TicketEventKind.OPERATOR_FIXED, TicketEventKind.VERIFY_STARTED):
        tickets.apply_event(seeded, tid, kind, "test")
    tickets.apply_event(seeded, tid, TicketEventKind.VERIFIED_OK, "test")
    assert ticket.id == tid
    out = run(sfn_tasks.start_verification, {"ticket_id": tid})
    assert out["skip"] is True and out["households"] == []


@pytest.mark.parametrize(
    ("answers", "outcome", "state"),
    [
        ([WaterAnswer.YES, WaterAnswer.YES], "CLOSED_VERIFIED", TicketState.CLOSED_VERIFIED),
        ([WaterAnswer.YES, WaterAnswer.NO], "REOPENED", TicketState.REOPENED),
        ([WaterAnswer.YES], "PENDING", TicketState.VERIFYING),
    ],
)
def test_evaluate_verification(
    seeded: Repository,
    clock: Clock,
    answers: list[WaterAnswer],
    outcome: str,
    state: TicketState,
) -> None:
    tid = open_assigned_ticket(seeded)
    tickets.apply_event(seeded, tid, TicketEventKind.OPERATOR_FIXED, "test")
    tickets.apply_event(seeded, tid, TicketEventKind.VERIFY_STARTED, "test")
    clock.advance(minutes=5)
    for hid, water in zip(("h1", "h2"), answers, strict=False):
        seeded.put_checkin(checkin(hid, water=water, purpose=Purpose.VERIFY, at=clock()))
    out = run(sfn_tasks.evaluate_verification, {"ticket_id": tid, "verify": {"round": 1}})
    assert out["outcome"] == outcome and out["round"] == 1
    assert tickets.load_ticket(seeded, tid).state is state
    if state is TicketState.CLOSED_VERIFIED:
        assert seeded.get_open_ticket(VID) is None


def test_evaluate_ignores_answers_from_before_the_round(seeded: Repository, clock: Clock) -> None:
    tid = open_assigned_ticket(seeded)
    seeded.put_checkin(checkin("h1", water=WaterAnswer.NO, purpose=Purpose.VERIFY, at=NOW))
    clock.advance(minutes=1)
    tickets.apply_event(seeded, tid, TicketEventKind.OPERATOR_FIXED, "test")
    tickets.apply_event(seeded, tid, TicketEventKind.VERIFY_STARTED, "test")
    out = run(sfn_tasks.evaluate_verification, {"ticket_id": tid, "verify": {"round": 1}})
    assert out["outcome"] == "PENDING"


def test_escalate_marks_simulated_phed_and_waits(seeded: Repository) -> None:
    tid = open_assigned_ticket(seeded)
    state = {"ticket_id": tid, "escalation_cause": {"Error": "States.HeartbeatTimeout"}}
    out = run(sfn_tasks.escalate, state, token="esc-1")
    assert out["status"] == "waiting"
    ticket = tickets.load_ticket(seeded, tid)
    assert ticket.state is TicketState.ESCALATED
    assert ticket.events[-1].detail == {
        "to": "PHED_AE_SIM",
        "simulated": True,
        "cause": "States.HeartbeatTimeout",
    }
    again = run(sfn_tasks.escalate, state, token="esc-2")
    assert again["status"] == "waiting"
    assert len(tickets.load_ticket(seeded, tid).events) == len(ticket.events)


def test_escalate_resumes_at_once_when_fix_arrived(seeded: Repository, sfn_fake: FakeSfn) -> None:
    tid = open_assigned_ticket(seeded)
    tickets.apply_event(seeded, tid, TicketEventKind.OPERATOR_FIXED, "test")
    out = run(sfn_tasks.escalate, {"ticket_id": tid}, token="esc-1")
    assert out["status"] == "already_fixed"
    assert sfn_fake.outputs_for("esc-1")[0]["fixed"] is True


def test_ticket_id_is_required(seeded: Repository) -> None:
    with pytest.raises(sfn_tasks.TaskError):
        run(sfn_tasks.start_verification, {})


# --- the whole loop -------------------------------------------------------------------------------


def test_full_loop_check_in_to_verified_close(
    seeded: Repository, sfn_fake: FakeSfn, clock: Clock
) -> None:
    """CheckInRun then TicketFlow, as the state machines sequence the tasks."""
    roster = run(sfn_tasks.load_roster, {"village_id": VID, "purpose": "DAILY"})
    for n, call_item in enumerate(roster["households"]):
        if not run(sfn_tasks.policy_check_call, call_item)["allowed"]:
            continue
        placed = run(sfn_tasks.place_call, call_item, token=f"call-{n}")
        finish_sim_call(seeded, placed["call_id"], ["2", "3", "#"])  # no water; none; no note
        assert sfn_fake.outputs_for(f"call-{n}")[0]["answered"] is True
    day = run(sfn_tasks.reconcile_day, {"village_id": VID, "date": roster["date"]})
    assert day["status"] == "NO_SUPPLY"

    flow_state: dict[str, Any] = {
        "village_id": VID,
        "reason": day["ticket_reason"],
        "ticket_id": day["ticket_id"],
    }
    assert day["tickets_opened"] == [day["ticket_id"]]
    assert run(sfn_tasks.open_ticket, flow_state)["opened"] is True
    run(sfn_tasks.notify_operator, flow_state, token="fix-1")
    operator_call = calls.find_pending(seeded, "op-1", Purpose.OPERATOR)
    assert operator_call is not None
    assert operator_call.record.flow.reported_households == 2
    finish_sim_call(seeded, operator_call.record.call_id, ["1"])  # operator: fixed
    assert sfn_fake.outputs_for("fix-1")[0]["fixed"] is True

    clock.advance(minutes=30)
    verify = run(sfn_tasks.start_verification, {**flow_state, "verify": {"round": 0}})
    for n, call_item in enumerate(verify["households"]):
        assert run(sfn_tasks.policy_check_call, call_item)["allowed"] is True
        placed = run(sfn_tasks.place_call, call_item, token=f"verify-{n}")
        finish_sim_call(seeded, placed["call_id"], ["1"])  # water is back
    result = run(sfn_tasks.evaluate_verification, {**flow_state, "verify": verify})
    assert result["outcome"] == "CLOSED_VERIFIED" and result["yes"] == 2

    ticket = tickets.load_ticket(seeded, day["ticket_id"])
    assert ticket.state is TicketState.CLOSED_VERIFIED
    kinds = [e.kind for e in ticket.events]
    assert kinds == ["NOTIFIED", "OPERATOR_FIXED", "VERIFY_STARTED", "VERIFIED_OK"]
    assert seeded.get_open_ticket(VID) is None
    assert [e.kind for e in seeded.list_ticket_events(ticket.id)] == kinds
    feed = seeded.list_activity(NOW.replace(hour=0))
    assert {e.kind for e in feed} >= {"checkin_run", "call", "day_status", "ticket"}


def test_transition_helper_matches_core(seeded: Repository) -> None:
    """apply_event refuses what core refuses, without saving anything."""
    tid = open_assigned_ticket(seeded)
    before = tickets.load_ticket(seeded, tid)
    denied = tickets.apply_event(seeded, tid, TicketEventKind.VERIFIED_OK, "test")
    assert isinstance(denied, tickets.Denied)
    assert isinstance(transition(before, TicketEventKind.VERIFIED_OK, "t", NOW), tickets.Denied)
    assert tickets.load_ticket(seeded, tid) == before
