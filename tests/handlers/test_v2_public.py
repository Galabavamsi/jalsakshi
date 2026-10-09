"""Residents' view (ARCHITECTURE.md §15.11): no login, cacheable, village-level facts only."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

import pytest

from jalsakshi.core.models import (
    Broadcast,
    BroadcastKind,
    BroadcastState,
    TicketOrigin,
    TicketReason,
    WaterAnswer,
)
from jalsakshi.core.tickets import TicketEventKind, new_ticket
from jalsakshi.handlers import calls, public, residents, tickets
from jalsakshi.store import Repository

from .fakes import (
    DAY,
    NOW,
    PHONES,
    VID,
    Clock,
    HttpEvent,
    V2Fakes,
    call,
    checkin,
    resident,
    v2_fakes,
    village,
    water_point,
)

NAMES = ("Ramesh Kumar", "Sita Devi")
PHONE_LIKE = re.compile(r"(\+?91)?[6-9]\d{9}")


@pytest.fixture
def v2(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fakes]:
    yield from v2_fakes(monkeypatch)


def get(path: str) -> tuple[int, object, dict[str, str]]:
    return call(public.handler, HttpEvent("GET", path))


@pytest.fixture
def busy(v2: V2Fakes, seeded: Repository, clock: Clock) -> Repository:
    """A village with points, named families, open and closed complaints and announcements."""
    seeded.put_village(village().model_copy(update={"name_hi": "टेस्टगाँव"}))
    seeded.put_water_point(water_point("wp-a", name="Main tank"))
    seeded.put_water_point(water_point("wp-old", active=False))
    for (hid, phone), name in zip(
        (("hh-r", "+919811110001"), ("hh-s", "+919811110002")), NAMES, strict=True
    ):
        seeded.put_household(
            resident(hid, phone, wpid="wp-a").model_copy(update={"display_name": name})
        )
    for hid in ("h1", "h2"):
        household = seeded.get_household(VID, hid)
        assert household is not None
        seeded.put_household(
            household.model_copy(update={"water_point_id": "wp-a", "display_name": "Gita Bai"})
        )
    village_ = seeded.get_village(VID)
    assert village_ is not None
    hh_r = seeded.get_household(VID, "hh-r")
    hh_s = seeded.get_household(VID, "hh-s")
    assert hh_r is not None and hh_s is not None
    residents.report_problem(
        seeded, village_, hh_r, TicketReason.NO_SUPPLY, origin=TicketOrigin.REPORT
    )
    residents.report_problem(
        seeded, village_, hh_s, TicketReason.NO_SUPPLY, origin=TicketOrigin.REPORT
    )
    residents.report_problem(seeded, village_, hh_s, TicketReason.LEAK, origin=TicketOrigin.CONSOLE)

    closed = seeded.open_ticket_if_none(
        new_ticket(VID, TicketReason.DIRTY, NOW, water_point_id="wp-a", number=9)
    )
    assert closed is not None
    for kind in (
        TicketEventKind.NOTIFIED,
        TicketEventKind.OPERATOR_FIXED,
        TicketEventKind.VERIFY_STARTED,
    ):
        tickets.apply_event(seeded, closed.id, kind, "test")
    clock.advance(hours=6)
    tickets.apply_event(seeded, closed.id, TicketEventKind.VERIFIED_OK, "test")

    for hid in ("hh-r", "hh-s"):
        seeded.put_checkin(
            checkin(hid, water=WaterAnswer.NO).model_copy(update={"water_point_id": "wp-a"})
        )
    calls.refresh_day(seeded, VID, DAY)
    for state, text in (
        (BroadcastState.SENT, "Kal paani nahi aayega."),
        (BroadcastState.DRAFT, "x"),
    ):
        seeded.put_broadcast(
            Broadcast(
                id=f"bc-{state.value.lower()}",
                village_id=VID,
                kind=BroadcastKind.SUPPLY_CHANGE,
                text_hi=text,
                state=state,
                created_by="console:alice",
                created_at=NOW,
                sent_at=NOW if state is BroadcastState.SENT else None,
            )
        )
    clock.advance(hours=2)
    return seeded


def test_village_view_has_no_personal_data(busy: Repository) -> None:
    status, body, headers = get(f"/public/villages/{VID}")
    assert status == 200 and headers["Cache-Control"] == "public, max-age=60"
    text = json.dumps(body, ensure_ascii=False)
    assert PHONE_LIKE.search(text) is None, PHONE_LIKE.search(text)
    assert "+91" not in text and "XXXX" not in text
    for secret in (*NAMES, "Gita Bai", *PHONES, "hh-r", "hh-s", "reporters", "household_id"):
        assert secret not in text, secret
    assert isinstance(body, dict)
    assert body["village"]["id"] == VID and body["village"]["name_hi"] == "टेस्टगाँव"


def test_village_view_content(busy: Repository) -> None:
    _, body, _ = get(f"/public/villages/{VID}")
    assert isinstance(body, dict)
    complaints = body["open_complaints"]
    assert [(c["number"], c["reason"], c["families"]) for c in complaints] == [
        (1, "NO_SUPPLY", 2),
        (2, "LEAK", 1),
    ]
    assert complaints[0]["water_point"] == "Main tank" and complaints[0]["state"] == "OPEN"
    assert complaints[0]["age_hours"] >= 8.0
    assert body["repairs_confirmed"] == {"count": 1, "median_hours": 6.0}
    assert [p["id"] for p in body["water_points"]] == ["wp-a"]  # inactive points hidden
    [today] = body["days"]
    assert today["date"] == DAY.isoformat() and today["status"] == "NO_SUPPLY"
    assert {"water_point_id": "wp-a", "status": "NO_SUPPLY"} in today["points"]
    assert [a["text_hi"] for a in body["announcements"]] == ["Kal paani nahi aayega."]
    assert body["families_reporting"] == 4  # h1, h2 and the two named families (h3: no consent)
    assert body["official"] is None and len(body["sources"]) == 2


def test_village_list_and_missing_village(busy: Repository) -> None:
    busy.put_village(village("v-off").model_copy(update={"active": False}))
    status, rows, headers = get("/public/villages")
    assert status == 200 and headers["Cache-Control"] == "public, max-age=60"
    assert rows == [{"id": VID, "name": "Testgaon", "name_hi": "टेस्टगाँव", "lgd_code": None}]
    assert get("/public/villages/nope")[0] == 404
    assert get("/public/villages/v-off")[0] == 404
    status, body, _ = get("/public/nothing-here")
    assert status == 404 and isinstance(body, dict) and body["error"]["code"] == "no_route"
