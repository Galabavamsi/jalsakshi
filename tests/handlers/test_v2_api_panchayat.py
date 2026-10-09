"""Gram Panchayat console routes (ARCHITECTURE.md §15.12): water points, adding families (who get
a consent call), the consent ledger, console complaints, water quality, analytics and summary."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from jalsakshi.core.models import (
    ConsentAction,
    ConsentStatus,
    TicketOrigin,
    TicketReason,
    WaterPointKind,
)
from jalsakshi.core.tickets import new_ticket
from jalsakshi.handlers import api, config, residents
from jalsakshi.store import Repository

from .fakes import (
    NOW,
    OUTBOUND_FN,
    PHONES,
    VID,
    HttpEvent,
    V2Fakes,
    call,
    checkin,
    resident,
    v2_fakes,
    water_point,
)

SECRETARY = {"username": "alice", "cognito:groups": "[PANCHAYAT_SECRETARY]"}
NEW_PHONE = "+919800000055"


@pytest.fixture
def v2(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fakes]:
    yield from v2_fakes(monkeypatch)


def get(path: str, query: dict[str, str] | None = None) -> Any:
    return call(api.handler, HttpEvent("GET", path, query=query or {}, claims=SECRETARY))


def post(path: str, body: Any = None) -> Any:
    return call(api.handler, HttpEvent("POST", path, body, claims=SECRETARY))


# --- water points --------------------------------------------------------------------------------


def test_create_list_and_update_a_water_point(v2: V2Fakes, seeded: Repository) -> None:
    body = {
        "id": "wp-main",
        "kind": "PIPED",
        "name": "Main tank",
        "name_hi": "मुख्य टंकी",
        "hamlet": "Upar para",
        "supply_window": "06:30-08:00",
        "operator_ids": ["op-1"],
        "quorum": 3,
        "lat": "21.25",
        "lon": 81.63,
    }
    status, created, _ = post(f"/api/villages/{VID}/water-points", body)
    assert status == 200
    assert created["location"] == {
        "lat": 21.25,
        "lon": 81.63,
        "source": "entered in the console",
        "accuracy_m": None,
    }
    assert created["provisional"] is False and created["quorum"] == 3
    status, listed, _ = get(f"/api/villages/{VID}/water-points")
    assert status == 200 and [p["id"] for p in listed] == ["wp-main"]

    status, updated, _ = post(
        f"/api/villages/{VID}/water-points", {"id": "wp-main", "name": "Tank"}
    )
    assert status == 200
    assert updated["name"] == "Tank" and updated["kind"] == "PIPED"
    assert updated["operator_ids"] == ["op-1"] and updated["location"]["lat"] == 21.25
    assert updated["supply_window"] == "06:30-08:00" and updated["name_hi"] == "मुख्य टंकी"


def test_naming_a_provisional_point_confirms_it(v2: V2Fakes, seeded: Repository) -> None:
    village = seeded.get_village(VID)
    assert village is not None
    provisional = residents.point_for_access(seeded, village, residents.AccessKind.HANDPUMP)
    assert provisional.provisional
    body = {"id": provisional.id, "name": "Handpump near school"}
    status, named, _ = post(f"/api/villages/{VID}/water-points", body)
    assert status == 200 and named["provisional"] is False and named["kind"] == "HANDPUMP"


def test_update_without_active_keeps_a_point_inactive(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_water_point(water_point("wp-old", WaterPointKind.HANDPUMP, active=False))
    status, body, _ = post(f"/api/villages/{VID}/water-points", {"id": "wp-old", "name": "Old"})
    assert status == 200 and body["active"] is False
    status, body, _ = post(f"/api/villages/{VID}/water-points", {"id": "wp-old", "active": True})
    assert body["active"] is True


def test_point_id_is_generated_when_missing(v2: V2Fakes, seeded: Repository) -> None:
    status, body, _ = post(f"/api/villages/{VID}/water-points", {"kind": "TANKER"})
    assert status == 200 and body["id"].startswith("wp-") and body["kind"] == "TANKER"
    assert seeded.get_water_point(VID, body["id"]) is not None


@pytest.mark.parametrize(
    "body",
    [
        {"id": "WP Main"},
        {"id": "wp-" + "x" * 40},
        {"id": "wp-a", "kind": "RIVER"},
        {"id": "wp-a", "supply_window": "6 to 8"},
        {"id": "wp-a", "lat": "north", "lon": 81.6},
        {"id": "wp-a", "lat": 95, "lon": 81.6},
        {"id": "wp-a", "operator_ids": "op-1"},
        {"id": "wp-a", "operator_ids": [1, 2]},
        {"id": "wp-a", "quorum": -1},
    ],
)
def test_water_point_validation(v2: V2Fakes, seeded: Repository, body: dict[str, Any]) -> None:
    status, payload, _ = post(f"/api/villages/{VID}/water-points", body)
    assert status == 400, payload
    assert payload["error"]["code"] == "invalid_request"
    assert seeded.list_water_points(VID) == []


def test_water_points_of_an_unknown_village_404(v2: V2Fakes, seeded: Repository) -> None:
    assert get("/api/villages/nope/water-points")[0] == 404
    assert post("/api/villages/nope/water-points", {"id": "wp-a"})[0] == 404


# --- adding families ---------------------------------------------------------------------------


def test_adding_a_family_queues_its_consent_call(v2: V2Fakes, seeded: Repository) -> None:
    body = {"phone": "+91 98000 00055", "access": "HANDPUMP", "display_name": " Ramesh "}
    status, out, _ = post(f"/api/villages/{VID}/households", body)
    assert status == 201 and out["call"] == "queued"
    household = out["household"]
    assert "phone_e164" not in household and household["phone_masked"] == "+91XXXXXX0055"
    assert NEW_PHONE not in json.dumps(out)
    hid = residents.new_household_id(NEW_PHONE)
    assert household["id"] == hid and household["consent_status"] == "NONE"
    [job] = v2.lambdas.events("register", function=OUTBOUND_FN)
    assert job == {"kind": "register", "village_id": VID, "household_id": hid}
    stored = seeded.get_household(VID, hid)
    assert stored is not None and stored.registered_via == "console"
    assert stored.display_name == "Ramesh" and stored.access is not None
    assert stored.consent_status is ConsentStatus.NONE and not stored.consent_given


@pytest.mark.parametrize(
    "body",
    [{"phone": "98000 00055"}, {"phone": "+1415555012"}, {}, {"phone": NEW_PHONE, "access": "X"}],
)
def test_adding_a_family_validates_the_body(v2: V2Fakes, seeded: Repository, body: Any) -> None:
    status, out, _ = post(f"/api/villages/{VID}/households", body)
    assert status == 400 and out["error"]["code"] == "invalid_request"
    assert v2.lambdas.invocations == []


def test_adding_a_consented_number_again_makes_no_call(v2: V2Fakes, seeded: Repository) -> None:
    status, out, _ = post(f"/api/villages/{VID}/households", {"phone": PHONES[0]})
    assert status == 200 and out == {**out, "call": "none"}
    assert out["household"]["id"] == "h1"  # matched by number, not by a new id
    assert v2.lambdas.invocations == []
    assert len(seeded.find_households_by_phone(PHONES[0])) == 1


def test_adding_a_known_unconsented_number_reuses_its_record(
    v2: V2Fakes, seeded: Repository
) -> None:
    status, out, _ = post(f"/api/villages/{VID}/households", {"phone": PHONES[3]})
    assert status == 201 and out["household"]["id"] == "h3"
    assert [h.id for h in seeded.find_households_by_phone(PHONES[3])] == ["h3"]
    assert v2.lambdas.events("register")[0]["household_id"] == "h3"


def test_a_family_that_declined_is_not_reset(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_household(resident("hh-no", NEW_PHONE, status=ConsentStatus.DECLINED))
    status, out, _ = post(f"/api/villages/{VID}/households", {"phone": NEW_PHONE})
    assert status == 409 and out["error"]["code"] == "consent_declined"
    stored = seeded.get_household(VID, "hh-no")
    assert stored is not None and stored.consent_status is ConsentStatus.DECLINED
    assert v2.lambdas.invocations == []


def test_adding_without_a_call(v2: V2Fakes, seeded: Repository) -> None:
    status, out, _ = post(f"/api/villages/{VID}/households", {"phone": NEW_PHONE, "call": False})
    assert status == 201 and out["call"] == "none" and v2.lambdas.invocations == []


def test_adding_when_outbound_is_not_configured_stores_nothing(
    v2: V2Fakes, seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JALSAKSHI_OUTBOUND_FN")
    config.settings.cache_clear()
    status, out, _ = post(f"/api/villages/{VID}/households", {"phone": NEW_PHONE})
    assert status == 503 and out["error"]["code"] == "not_configured"
    assert seeded.find_households_by_phone(NEW_PHONE) == []


# --- consent ledger --------------------------------------------------------------------------


def test_consent_ledger_is_masked_proof(v2: V2Fakes, seeded: Repository) -> None:
    residents.log_consent(
        seeded, VID, "h1", PHONES[0], ConsentAction.GRANTED, at=NOW, call_id="c1", digits="1"
    )
    residents.log_consent(
        seeded, VID, "h2", PHONES[1], ConsentAction.WITHDRAWN, at=NOW, call_id="c2", digits="9"
    )
    status, body, _ = get(f"/api/villages/{VID}/consents")
    assert status == 200
    assert [e["action"] for e in body["events"]] == ["GRANTED", "WITHDRAWN"]
    assert body["events"][0]["phone_masked"] == "+91XXXXXX0001"
    assert body["notice_version"] == "hi-2"
    assert body["notice_sha256"] == residents.notice_sha256()
    assert "DPDP Act 2023" in body["label"]
    text = json.dumps(body)
    assert PHONES[0] not in text and PHONES[1] not in text


# --- complaints from the console ----------------------------------------------------------------


def test_console_complaint_for_a_family(v2: V2Fakes, seeded: Repository) -> None:
    status, ticket, _ = post(
        f"/api/villages/{VID}/tickets", {"reason": "LEAK", "household_id": "h1"}
    )
    assert status == 201
    assert ticket["origin"] == TicketOrigin.CONSOLE.value and ticket["reason"] == "LEAK"
    assert ticket["reporters"] == ["h1"] and ticket["number"] == 1
    assert v2.sfn.names == [ticket["id"]]
    status, out, _ = post(f"/api/villages/{VID}/tickets", {"reason": "LEAK"})
    assert status == 422 and out["error"]["code"] == "household_required"
    status, out, _ = post(f"/api/villages/{VID}/tickets", {"reason": "FIRE", "household_id": "h1"})
    assert status == 400


# --- water quality ---------------------------------------------------------------------------


def test_quality_test_is_noted_on_the_open_dirty_ticket(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_water_point(water_point("wp-a"))
    dirty = seeded.open_ticket_if_none(
        new_ticket(VID, TicketReason.DIRTY, NOW, water_point_id="wp-a")
    )
    assert dirty is not None
    body = {
        "water_point_id": "wp-a",
        "method": "FTK",
        "result": "UNSAFE",
        "parameters": {"e_coli": "present", "turbidity_ntu": 8},
        "tested_at": "2026-10-08T09:00:00",
        "note": "  yellow colour ",
    }
    status, test, _ = post(f"/api/villages/{VID}/quality", body)
    assert status == 201
    assert test["result"] == "UNSAFE" and test["entered_by"] == "console:alice"
    assert test["parameters"] == {"e_coli": "present", "turbidity_ntu": "8"}
    tested_at = datetime.fromisoformat(test["tested_at"])
    assert tested_at == datetime(2026, 10, 8, 3, 30, tzinfo=UTC)  # 09:00 IST without a zone
    assert test["note"] == "yellow colour"
    ticket = seeded.get_ticket_by_id(dirty.id)
    assert ticket is not None
    assert ticket.events[-1].detail == {"note": "quality_test", "result": "UNSAFE", "method": "FTK"}
    status, listing, _ = get(f"/api/villages/{VID}/quality")
    assert status == 200 and [t["id"] for t in listing["tests"]] == [test["id"]]
    assert listing["official"] is None


def test_quality_test_without_an_open_dirty_ticket_adds_no_note(
    v2: V2Fakes, seeded: Repository
) -> None:
    seeded.put_water_point(water_point("wp-a"))
    no_supply = seeded.open_ticket_if_none(
        new_ticket(VID, TicketReason.NO_SUPPLY, NOW, water_point_id="wp-a")
    )
    assert no_supply is not None
    status, _, _ = post(
        f"/api/villages/{VID}/quality", {"water_point_id": "wp-a", "result": "SAFE"}
    )
    assert status == 201
    ticket = seeded.get_ticket_by_id(no_supply.id)
    assert ticket is not None and ticket.events == []


@pytest.mark.parametrize(
    "body",
    [
        {"result": "MAYBE"},
        {},
        {"result": "SAFE", "method": "SNIFF"},
        {"result": "SAFE", "tested_at": "yesterday"},
        {"result": "SAFE", "parameters": ["e_coli"]},
        {"result": "SAFE", "water_point_id": "wp-nowhere"},
    ],
)
def test_quality_validation(v2: V2Fakes, seeded: Repository, body: dict[str, Any]) -> None:
    status, out, _ = post(f"/api/villages/{VID}/quality", body)
    assert status == 400, out
    assert seeded.list_quality_tests(VID) == []


# --- analytics and summary ---------------------------------------------------------------------


def test_analytics_and_summary(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_checkin(checkin("h1"))
    status, body, _ = get(f"/api/villages/{VID}/analytics")
    assert status == 200
    assert {"village_id", "start", "end", "points", "village", "households", "broadcasts"} <= set(
        body
    )
    assert {"tickets_opened", "tickets_closed_verified", "source", "rule_note"} <= set(body)
    assert body["village_id"] == VID and body["source"]["freshness"] == "live"
    assert body["end"] == "2026-10-08" and body["start"] == "2026-09-09"
    assert body["households"]["registered"] == 3
    status, body, _ = get(
        f"/api/villages/{VID}/analytics", {"from": "2026-10-01", "to": "2026-10-08"}
    )
    assert status == 200 and body["start"] == "2026-10-01"
    status, _, _ = get(f"/api/villages/{VID}/analytics", {"from": "2026-10-09", "to": "2026-10-08"})
    assert status == 400

    status, summary, _ = get(f"/api/villages/{VID}/summary")
    assert status == 200
    assert {"village_id", "start", "end", "text_hi", "text_en", "numbers", "source"} <= set(summary)
    assert summary["start"] == "2026-10-02" and summary["end"] == "2026-10-08"
    assert summary["text_hi"] and summary["text_en"]
    assert PHONES[0] not in json.dumps(summary)
