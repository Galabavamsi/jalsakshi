"""Console API routes: shapes from §13, masking, Cedar denies, ticket actions, brief, feed."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest

from jalsakshi.core.models import (
    CapturedVia,
    CleanAnswer,
    DayCounts,
    DayStatus,
    DayStatusValue,
    Purpose,
    TicketReason,
    TicketState,
    WaterAnswer,
)
from jalsakshi.core.tickets import TicketEventKind, new_ticket
from jalsakshi.handlers import api, config, tickets
from jalsakshi.handlers.context import context_key
from jalsakshi.store import Repository

from .fakes import (
    BUCKET,
    CHECKIN_ARN,
    DAY,
    NOW,
    VID,
    Clock,
    FakeSfn,
    HttpEvent,
    LambdaContext,
    call,
    checkin,
)

SECRETARY = {"username": "alice", "cognito:groups": "[PANCHAYAT_SECRETARY]"}
PHED = {"username": "bob", "cognito:groups": ["PHED_AE_SIM"]}


def get(path: str, query: dict[str, str] | None = None, claims: dict | None = None) -> Any:
    return call(api.handler, HttpEvent("GET", path, query=query or {}, claims=claims or SECRETARY))


def post(path: str, body: Any = None, claims: dict | None = None) -> Any:
    return call(api.handler, HttpEvent("POST", path, body, claims=claims or SECRETARY))


def day_status(status: DayStatusValue, *, day: Any = DAY, at: Any = NOW) -> DayStatus:
    return DayStatus(
        village_id=VID,
        date=day,
        status=status,
        counts=DayCounts(answered=2, yes=2),
        rule_version="r1",
        computed_at=at,
    )


def ticket_in(repo: Repository, *kinds: TicketEventKind) -> str:
    ticket = repo.open_ticket_if_none(new_ticket(VID, TicketReason.NO_SUPPLY, NOW))
    assert ticket is not None
    for kind in kinds:
        tickets.apply_event(repo, ticket.id, kind, "test")
    return ticket.id


def test_list_villages_shape(seeded: Repository) -> None:
    seeded.put_day_status(day_status(DayStatusValue.SUPPLIED))
    seeded.put_day_status(day_status(DayStatusValue.NO_SUPPLY, day=DAY - timedelta(days=1)))
    status, rows, _ = get("/api/villages")
    assert status == 200 and len(rows) == 1
    row = rows[0]
    assert row["village"]["id"] == VID
    assert row["today"]["status"] == "SUPPLIED"
    assert row["open_ticket"] is None
    observed = row["observed_7d"]
    assert {k: observed[k] for k in ("days", "supplied", "no_supply", "unverified")} == {
        "days": 2,
        "supplied": 1,
        "no_supply": 1,
        "unverified": 0,
    }
    assert observed["source"]["freshness"] == "live"


def test_simulator_answers_are_labelled_simulated(seeded: Repository) -> None:
    seeded.put_day_status(day_status(DayStatusValue.SUPPLIED))
    simulated = checkin("h1").model_copy(update={"captured_via": CapturedVia.SIMULATOR})
    seeded.put_checkin(simulated)
    _, rows, _ = get("/api/villages")
    source = rows[0]["observed_7d"]["source"]
    assert source["freshness"] == "simulated"
    assert source["source"] == api.CHECKIN_SOURCE_SIMULATED
    _, brief, _ = get(f"/api/villages/{VID}/brief")
    tally = next(s for s in brief["sources"] if s["source"] == api.CHECKIN_SOURCE_SIMULATED)
    assert tally["freshness"] == "simulated"


def test_village_detail_masks_phones_and_reads_context(
    seeded: Repository, aws: dict[str, Any]
) -> None:
    context = {"rain_7d_mm": {"value": 12.5, "source": {"source": "Open-Meteo"}}}
    aws["s3"].put_object(Bucket=BUCKET, Key=context_key(VID), Body=json.dumps(context))
    status, body, _ = get(f"/api/villages/{VID}")
    assert status == 200
    assert body["context"] == context
    household = body["households"][0]
    assert "phone_e164" not in household and household["phone_masked"] == "+91XXXXXX0001"
    assert body["operators"][0]["phone_e164"] == "+91XXXXXX0003"
    assert "+919800000001" not in json.dumps(body)


def test_unknown_village_is_404_envelope(seeded: Repository) -> None:
    status, body, _ = get("/api/villages/nope")
    assert status == 404 and body["error"]["code"] == "not_found"


def test_days_range_and_validation(seeded: Repository) -> None:
    seeded.put_day_status(day_status(DayStatusValue.SUPPLIED))
    status, days, _ = get(f"/api/villages/{VID}/days", {"from": "2026-10-01", "to": "2026-10-08"})
    assert status == 200 and [d["date"] for d in days] == ["2026-10-08"]
    status, body, _ = get(f"/api/villages/{VID}/days", {"from": "2026-10-09", "to": "2026-10-08"})
    assert status == 400 and body["error"]["code"] == "invalid_request"
    status, _, _ = get(f"/api/villages/{VID}/days", {"from": "08-10-2026"})
    assert status == 400


def test_checkins_masked_for_panchayat(seeded: Repository) -> None:
    seeded.put_checkin(checkin("h1", water=WaterAnswer.NO))
    status, rows, _ = get(f"/api/villages/{VID}/checkins", {"date": "2026-10-08"})
    assert status == 200
    assert rows[0]["household_id"] == "h1" and rows[0]["phone_masked"] == "+91XXXXXX0001"
    assert rows[0]["water"] == "NO"


def test_checkins_denied_for_department_role(seeded: Repository) -> None:
    status, body, _ = get(f"/api/villages/{VID}/checkins", claims=PHED)
    assert status == 403
    assert body["denied"] is True and body["policy_id"] == "no-household-view-for-dept"
    feed = seeded.list_activity(NOW - timedelta(hours=1))
    assert feed[-1].kind == "policy_denied"


def test_run_checkin_starts_the_workflow(seeded: Repository, sfn_fake: FakeSfn) -> None:
    status, body, _ = post(f"/api/villages/{VID}/checkin/run", {"purpose": "DAILY"})
    assert status == 200 and body["execution_arn"].endswith(":run-1")
    [(arn, payload)] = sfn_fake.executions
    assert arn == CHECKIN_ARN
    assert payload == {
        "village_id": VID,
        "purpose": "DAILY",
        "trigger": "console",
        "requested_by": "console:alice",
    }


def test_run_checkin_rejects_other_purposes_and_missing_workflow(
    seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, _, _ = post(f"/api/villages/{VID}/checkin/run", {"purpose": "VERIFY"})
    assert status == 400
    status, _, _ = post(f"/api/villages/{VID}/checkin/run", {"purpose": "BOGUS"})
    assert status == 400
    monkeypatch.delenv("JALSAKSHI_CHECKIN_SFN_ARN")
    config.settings.cache_clear()
    status, body, _ = post(f"/api/villages/{VID}/checkin/run", {})
    assert status == 503 and body["error"]["code"] == "not_configured"


def test_bad_json_is_400(seeded: Repository) -> None:
    event = HttpEvent("POST", f"/api/villages/{VID}/checkin/run", claims=SECRETARY).build()
    event["body"] = "{not json"
    response = api.handler(event, LambdaContext())
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "bad_json"


def test_unknown_route_is_404(seeded: Repository) -> None:
    status, body, _ = get("/api/nothing-here")
    assert status == 404 and body["error"]["code"] == "no_route"


def test_tickets_list_and_get(seeded: Repository) -> None:
    tid = ticket_in(seeded, TicketEventKind.NOTIFIED)
    status, rows, _ = get("/api/tickets", {"village_id": VID})
    assert status == 200 and [t["id"] for t in rows] == [tid]
    status, rows, _ = get("/api/tickets", {"state": "ASSIGNED"})
    assert [t["id"] for t in rows] == [tid]
    status, _, _ = get("/api/tickets", {"state": "WHATEVER"})
    assert status == 400
    status, ticket, _ = get(f"/api/tickets/{tid}")
    assert status == 200 and ticket["events"][0]["kind"] == "NOTIFIED"
    status, _, _ = get("/api/tickets/tkt_missing")
    assert status == 404


def test_operator_fixed_moves_ticket_and_resumes_workflow(
    seeded: Repository, sfn_fake: FakeSfn
) -> None:
    tid = ticket_in(seeded, TicketEventKind.NOTIFIED)
    tickets.register_wait(seeded, tid, "fix-1", "operator_fix")
    status, body, _ = post(f"/api/tickets/{tid}/operator-fixed", {"operator_id": "op-1"})
    assert status == 200 and body["state"] == "OPERATOR_REPORTED_FIXED"
    assert body["events"][-1]["actor"] == "console:alice"
    assert body["events"][-1]["detail"] == {"via": "console", "operator_id": "op-1"}
    assert sfn_fake.outputs_for("fix-1")[0]["fixed"] is True
    status, body, _ = post(f"/api/tickets/{tid}/operator-fixed", {"operator_id": "op-1"})
    assert status == 409 and body["error"]["code"] == "transition_denied"


def test_operator_fixed_validation(seeded: Repository) -> None:
    tid = ticket_in(seeded, TicketEventKind.NOTIFIED)
    status, _, _ = post(f"/api/tickets/{tid}/operator-fixed", {})
    assert status == 400
    status, _, _ = post(f"/api/tickets/{tid}/operator-fixed", {"operator_id": "ghost"})
    assert status == 404
    other = seeded.get_operator("op-1").model_copy(update={"id": "op-2", "village_ids": ["x"]})
    seeded.put_operator(other)
    status, body, _ = post(f"/api/tickets/{tid}/operator-fixed", {"operator_id": "op-2"})
    assert status == 422 and body["error"]["code"] == "operator_not_for_village"


def test_close_denied_without_household_quorum(seeded: Repository) -> None:
    tid = ticket_in(
        seeded,
        TicketEventKind.NOTIFIED,
        TicketEventKind.OPERATOR_FIXED,
        TicketEventKind.VERIFY_STARTED,
    )
    status, body, _ = post(f"/api/tickets/{tid}/close", {})
    assert status == 403
    assert body["policy_id"] == "verify-needs-quorum"
    assert "0" in body["reason_en"] and body["reason_hi"]
    stored = tickets.load_ticket(seeded, tid)
    assert stored.state is TicketState.VERIFYING
    assert stored.events[-1].detail["note"] == "close_denied"


def test_close_with_quorum_closes_and_releases_village(seeded: Repository, clock: Clock) -> None:
    tid = ticket_in(
        seeded,
        TicketEventKind.NOTIFIED,
        TicketEventKind.OPERATOR_FIXED,
        TicketEventKind.VERIFY_STARTED,
    )
    clock.advance(minutes=10)
    for hid in ("h1", "h2"):
        seeded.put_checkin(checkin(hid, purpose=Purpose.VERIFY, at=clock()))
    status, body, _ = post(f"/api/tickets/{tid}/close", {})
    assert status == 200 and body["state"] == "CLOSED_VERIFIED"
    assert seeded.get_open_ticket(VID) is None
    status, again, _ = post(f"/api/tickets/{tid}/close", {})
    assert status == 200 and again["state"] == "CLOSED_VERIFIED"


def test_close_refused_when_a_household_says_no(seeded: Repository, clock: Clock) -> None:
    tid = ticket_in(
        seeded,
        TicketEventKind.NOTIFIED,
        TicketEventKind.OPERATOR_FIXED,
        TicketEventKind.VERIFY_STARTED,
    )
    clock.advance(minutes=10)
    seeded.put_checkin(checkin("h1", purpose=Purpose.VERIFY, at=clock()))
    seeded.put_checkin(checkin("h2", purpose=Purpose.VERIFY, at=clock()))
    seeded.put_household(
        seeded.get_household(VID, "h3").model_copy(update={"consent": None, "id": "h4"})
    )
    seeded.put_checkin(checkin("h4", water=WaterAnswer.NO, purpose=Purpose.VERIFY, at=clock()))
    status, body, _ = post(f"/api/tickets/{tid}/close", {})
    assert status == 409 and body["error"]["code"] == "verification_failed"


def test_brief_template_with_sources(seeded: Repository) -> None:
    seeded.put_day_status(day_status(DayStatusValue.SUPPLIED))
    seeded.put_checkin(checkin("h1", water=WaterAnswer.YES, clean=CleanAnswer.YES))
    status, brief, _ = get(f"/api/villages/{VID}/brief")
    assert status == 200
    assert brief["generated_by"] == "template" and brief["markdown_hi"]
    assert brief["numbers"]["supplied"] == 1
    assert any(s["source"] == api.CHECKIN_SOURCE for s in brief["sources"])


def test_brief_denied_on_stale_data(seeded: Repository) -> None:
    seeded.put_day_status(day_status(DayStatusValue.SUPPLIED, at=NOW - timedelta(hours=30)))
    status, body, _ = get(f"/api/villages/{VID}/brief")
    assert status == 403 and body["policy_id"] == "stale-data"
    status, body, _ = get("/api/villages/v-test/brief", {"from": "2026-01-01", "to": "2026-10-08"})
    assert status == 400


def test_activity_feed_since(seeded: Repository) -> None:
    seeded.put_activity("call", VID, "one", "एक", at=NOW - timedelta(minutes=5))
    seeded.put_activity("call", VID, "two", "दो", at=NOW + timedelta(minutes=1))
    status, rows, _ = get("/api/activity", {"since": (NOW - timedelta(minutes=1)).isoformat()})
    assert status == 200 and [r["text_en"] for r in rows] == ["two"]
    status, rows, _ = get("/api/activity")
    assert [r["text_en"] for r in rows] == ["one", "two"]
    status, _, _ = get("/api/activity", {"since": "2026-10-08T05:00:00"})
    assert status == 400


def test_department_role_is_most_restrictive_group() -> None:
    assert api._groups("[SARPANCH PHED_EE_SIM]") == ["SARPANCH", "PHED_EE_SIM"]
    assert api._groups(["A", "B"]) == ["A", "B"]
    assert api._groups(None) == []


def test_me_reports_role_and_allowed_actions(seeded: Repository) -> None:
    status, body, _ = get("/api/me")
    assert status == 200
    assert body["role"] == "PANCHAYAT_SECRETARY"
    assert body["can_approve_announcements"] is False
    sarpanch = {**SECRETARY, "cognito:groups": "[SARPANCH]"}
    status, body, _ = get("/api/me", claims=sarpanch)
    assert body["role"] == "SARPANCH" and body["can_approve_announcements"] is True
