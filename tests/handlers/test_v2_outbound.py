"""The outbound Lambda (ARCHITECTURE.md §15.4, §15.10): call-backs after missed calls, the
console's registration call, and the weekly summary. Every call passes Cedar first."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from jalsakshi.core.models import (
    ConsentStatus,
    Household,
    Operator,
    OperatorRole,
    Purpose,
    TicketReason,
)
from jalsakshi.core.tickets import new_ticket
from jalsakshi.handlers import calls, config, outbound, residents
from jalsakshi.store import Repository

from .fakes import (
    MORNING,
    NIGHT,
    NOW,
    PHONES,
    STAGE,
    VID,
    Clock,
    LambdaContext,
    V2Fakes,
    resident,
    run_call,
    v2_fakes,
    village,
    water_point,
)

NEW_PHONE = "+919800000077"


@pytest.fixture
def v2(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fakes]:
    yield from v2_fakes(monkeypatch)


def use_vobiz(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(201, json={"request_uuid": "req-uuid-1", "message": "fired"})

    monkeypatch.setenv("VOICE_PROVIDER", "vobiz")
    config.settings.cache_clear()
    config.use_http_client(httpx.Client(transport=httpx.MockTransport(respond)))
    return sent


def record_of(repo: Repository, out: dict[str, Any]) -> calls.CallRecord:
    loaded = calls.load_call(repo, str(out["call_id"]))
    assert loaded is not None
    return loaded.record


def queue_missed_calls(repo: Repository, phone: str, n: int) -> None:
    for i in range(n):
        repo.record_missed_call(phone, NOW - timedelta(hours=i + 1), {"callback": True})


# --- call-backs --------------------------------------------------------------------------------


def test_callback_to_a_consented_household_dials_the_report_menu(
    v2: V2Fakes, seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = use_vobiz(monkeypatch)
    seeded.put_water_point(water_point("wp-a"))
    out = outbound.handler(
        {"kind": "callback", "phone": PHONES[0], "missed_at": NOW.isoformat(), "delay_s": 0},
        LambdaContext(),
    )
    assert out["status"] == "dialled"
    [request] = sent
    body = json.loads(request.content)
    assert body["to"] == PHONES[0] and body["from"] == "+918000000000"
    assert f"/answer?call_id={out['call_id']}" in body["answer_url"]
    record = record_of(seeded, out)
    assert record.flow.purpose is Purpose.REPORT and record.flow.household_id == "h1"
    assert record.origin == "callback" and record.caller_initiated
    assert record.provider_call_uuid == "req-uuid-1"
    assert record.flow.message_text_hi and record.flow.message_text_hi.startswith("Aaj Testgaon")
    again = outbound.callback(seeded, PHONES[0], 0, NOW.isoformat())  # retried invocation
    assert again["status"] == "already_dialled" and len(sent) == 1
    feed = seeded.list_activity(NOW - timedelta(hours=1))
    assert any("Calling back a family (+91XXXXXX0001)" in e.text_en for e in feed)


def test_callback_off_the_allowlist_is_not_dialled(
    v2: V2Fakes, seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = use_vobiz(monkeypatch)
    seeded.put_household(resident("h9", "+919811111111"))
    out = outbound.callback(seeded, "+919811111111", 0, "m")
    assert out["status"] == "failed" and "not registered" in out["error"]
    assert sent == []


def test_callback_from_an_unknown_number_registers_into_the_inbound_village(
    v2: V2Fakes, seeded: Repository
) -> None:
    seeded.put_village(village("v-in").model_copy(update={"inbound": True}))
    out = outbound.callback(seeded, NEW_PHONE, 0, "m")
    assert out["status"] == "pending"
    record = record_of(seeded, out)
    assert record.flow.purpose is Purpose.REGISTER and record.flow.village_id == "v-in"
    assert record.flow.household_id == residents.new_household_id(NEW_PHONE)
    assert record.phone_e164 == NEW_PHONE and record.caller_initiated
    assert seeded.find_households_by_phone(NEW_PHONE) == []


def test_callback_from_an_unknown_number_without_an_inbound_village_is_ignored(
    v2: V2Fakes, seeded: Repository
) -> None:
    assert outbound.callback(seeded, NEW_PHONE, 0, "m") == {
        "status": "ignored",
        "reason": "no village takes missed calls",
    }


def test_family_added_by_the_secretary_registers_in_its_own_village(
    v2: V2Fakes, seeded: Repository
) -> None:
    seeded.put_village(village("v-in").model_copy(update={"inbound": True}))
    added = resident("hh-added", NEW_PHONE, status=ConsentStatus.NONE).model_copy(
        update={"registered_via": "console", "display_name": "Sita"}
    )
    seeded.put_household(added)
    out = outbound.callback(seeded, NEW_PHONE, 0, "m")
    record = record_of(seeded, out)
    assert record.flow.purpose is Purpose.REGISTER
    assert (record.flow.village_id, record.flow.household_id) == (VID, "hh-added")
    run_call(record.call_id, ["1", "1", "2", "#"])  # adult, agree, public tap, no name
    [household] = seeded.find_households_by_phone(NEW_PHONE)
    assert household.id == "hh-added" and household.village_id == VID
    assert household.consent_status is ConsentStatus.GRANTED
    assert household.registered_via == "console" and household.display_name == "Sita"
    assert seeded.list_households("v-in") == []


def test_a_family_that_declined_may_still_register_by_missed_call(
    v2: V2Fakes, seeded: Repository
) -> None:
    declined = resident("hh-no", NEW_PHONE, status=ConsentStatus.DECLINED)
    seeded.put_household(declined.model_copy(update={"active": False}))
    out = outbound.callback(seeded, NEW_PHONE, 0, "m")
    assert out["status"] == "pending"
    assert record_of(seeded, out).flow.purpose is Purpose.REGISTER


def test_callback_to_an_operator_runs_the_operator_flow(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_water_point(water_point("wp-a", operator_ids=("op-1",)))
    ticket = seeded.open_ticket_if_none(
        new_ticket(
            VID,
            TicketReason.LEAK,
            NOW,
            water_point_id="wp-a",
            reporters=["h1", "h2"],
            number=4,
        )
    )
    assert ticket is not None
    out = outbound.callback(seeded, PHONES[2], 0, "m")
    record = record_of(seeded, out)
    flow = record.flow
    assert flow.purpose is Purpose.OPERATOR and flow.operator_id == "op-1"
    assert (flow.ticket_id, flow.ticket_reason, flow.ticket_number) == (
        ticket.id,
        TicketReason.LEAK,
        4,
    )
    assert flow.reported_households == 2 and flow.water_point_name == "टेस्टगाँव wp-a"
    assert record.caller_initiated


def test_operator_without_a_routed_ticket_is_not_given_the_operator_flow(
    v2: V2Fakes, seeded: Repository
) -> None:
    out = outbound.callback(seeded, PHONES[2], 0, "m")
    assert out["status"] == "ignored"  # no open ticket and no inbound village


@pytest.mark.parametrize("who", ["household", "unknown", "operator"])
def test_sixth_callback_in_a_day_is_denied_by_cedar(
    v2: V2Fakes, seeded: Repository, who: str
) -> None:
    seeded.put_village(village("v-in").model_copy(update={"inbound": True}))
    seeded.open_ticket_if_none(new_ticket(VID, TicketReason.NO_SUPPLY, NOW))
    phone = {"household": PHONES[0], "unknown": NEW_PHONE, "operator": PHONES[2]}[who]
    queue_missed_calls(seeded, phone, 5)
    assert outbound.callback(seeded, phone, 0, "m5")["status"] == "pending"
    seeded.record_missed_call(phone, NOW, {"callback": True})  # the sixth: queued a call-back
    out = outbound.callback(seeded, phone, 0, "m6")
    assert out == {"status": "denied", "policy_id": "callback-limit"}
    feed = seeded.list_activity(NOW - timedelta(hours=1))
    assert any(e.kind == "policy_denied" for e in feed)


def test_rings_that_queued_nothing_do_not_use_up_the_limit(v2: V2Fakes, seeded: Repository) -> None:
    for minutes in range(10):
        seeded.record_missed_call(PHONES[0], NOW - timedelta(minutes=minutes), {"callback": False})
    seeded.record_missed_call(PHONES[0], NOW - timedelta(minutes=30), {"callback": True})
    assert calls.callbacks_today(seeded, PHONES[0]) == 1
    assert outbound.callback(seeded, PHONES[0], 0, "m")["status"] == "pending"


def test_callback_at_night_is_allowed_because_the_family_asked(
    v2: V2Fakes, seeded: Repository, clock: Clock
) -> None:
    clock.now = NIGHT
    out = outbound.callback(seeded, PHONES[0], 0, "m")
    assert out["status"] in {"dialled", "pending"}


def test_callback_without_caller_id_is_ignored(v2: V2Fakes, seeded: Repository) -> None:
    out = outbound.handler({"kind": "callback", "phone": ""}, LambdaContext())
    assert out == {"status": "ignored", "reason": "no caller id"}


def test_unknown_job_kind_is_ignored(v2: V2Fakes, seeded: Repository) -> None:
    assert outbound.handler({"kind": "nope"}, LambdaContext()) == {"status": "ignored"}
    assert outbound.handler("not a dict", LambdaContext()) == {"status": "ignored"}


# --- console registration call ------------------------------------------------------------------


def added(repo: Repository, status: ConsentStatus = ConsentStatus.NONE) -> Household:
    household = resident("hh-c", NEW_PHONE, status=status).model_copy(
        update={"registered_via": "console"}
    )
    repo.put_household(household)
    return household


def test_register_job_calls_the_added_family_once_a_day(v2: V2Fakes, seeded: Repository) -> None:
    added(seeded)
    payload = {"kind": "register", "village_id": VID, "household_id": "hh-c"}
    out = outbound.handler(payload, LambdaContext())
    assert out["status"] == "pending" and out["call_id"] == "reg-v-test-hh-c-20261008"
    record = record_of(seeded, out)
    assert record.flow.purpose is Purpose.REGISTER and record.phone_e164 == NEW_PHONE
    assert record.origin == "console" and not record.caller_initiated
    assert outbound.handler(payload, LambdaContext())["status"] == "already_dialled"


def test_register_job_respects_refusals_and_missing_households(
    v2: V2Fakes, seeded: Repository
) -> None:
    assert outbound.register(seeded, VID, "ghost") == {
        "status": "ignored",
        "reason": "household missing",
    }
    added(seeded, ConsentStatus.DECLINED)
    out = outbound.register(seeded, VID, "hh-c")
    assert out == {"status": "denied", "policy_id": "no-calls-after-withdrawal"}


def test_register_job_once_the_family_has_answered_today(v2: V2Fakes, seeded: Repository) -> None:
    household = added(seeded)
    residents.log_consent(
        seeded,
        VID,
        household.id,
        household.phone_e164,
        residents.ConsentAction.MINOR,
        at=NOW,
        call_id="earlier",
        digits="2",
    )
    out = outbound.register(seeded, VID, "hh-c")
    assert out == {"status": "denied", "policy_id": "one-call-per-day"}


# --- weekly summary ---------------------------------------------------------------------------


def test_weekly_summary_calls_sarpanch_and_secretary(
    v2: V2Fakes,
    seeded: Repository,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    aws: dict[str, Any],
) -> None:
    sent = use_vobiz(monkeypatch)
    sarpanch = Operator(
        id="op-s", role=OperatorRole.SARPANCH, phone_e164="+919800000055", village_ids=[VID]
    )
    secretary = Operator(
        id="op-sec",
        role=OperatorRole.PANCHAYAT_SECRETARY,
        phone_e164="+919800000066",
        village_ids=[VID],
    )
    seeded.put_operator(sarpanch)
    seeded.put_operator(secretary)
    numbers = ",".join([*PHONES[:3], "+919800000055", "+919800000066"])
    aws["ssm"].put_parameter(
        Name=f"/jalsakshi/{STAGE}/allowed_numbers", Type="StringList", Value=numbers, Overwrite=True
    )
    config.secrets.clear()
    clock.now = MORNING
    out = outbound.handler({"kind": "weekly_summary"}, LambdaContext())
    assert out == {"status": "done", "calls": 2}
    assert sorted(json.loads(r.content)["to"] for r in sent) == ["+919800000055", "+919800000066"]
    record = calls.load_call(seeded, "sum-v-test-op-s-20261008")
    assert record is not None and record.record.flow.purpose is Purpose.SUMMARY
    assert record.record.flow.message_text_hi
    assert outbound.handler({"kind": "weekly_summary"}, LambdaContext())["calls"] == 0


def test_summary_call_finishes_without_a_checkin(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_operator(
        Operator(
            id="op-s", role=OperatorRole.SARPANCH, phone_e164="+919800000055", village_ids=[VID]
        )
    )
    outbound.weekly_summaries(seeded)  # simulator: left pending, not "dialled"
    loaded = calls.load_call(seeded, "sum-v-test-op-s-20261008")
    assert loaded is not None
    run_call(loaded.record.call_id, ["1"])
    finished = calls.load_call(seeded, loaded.record.call_id)
    assert finished is not None and finished.record.finished
    assert seeded.list_checkins_between(VID, NOW.date(), NOW.date()) == []


def test_summary_for_inactive_villages_is_skipped(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_village(village().model_copy(update={"active": False}))
    assert outbound.weekly_summaries(seeded) == {"status": "done", "calls": 0}
