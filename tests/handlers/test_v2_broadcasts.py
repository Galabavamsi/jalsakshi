"""Announcements end to end (ARCHITECTURE.md §15.8): a secretary drafts, only the sarpanch may
approve (Cedar), sending is queued to the outbound Lambda, at most two go out a week, only
consenting households on the target point are called, and the calls count deliveries."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

from jalsakshi.core.models import BroadcastState, Purpose
from jalsakshi.handlers import api, calls, outbound, speech
from jalsakshi.store import Repository

from .fakes import (
    NIGHT,
    NOW,
    OUTBOUND_FN,
    VID,
    Clock,
    HttpEvent,
    LambdaContext,
    V2Fakes,
    call,
    resident,
    run_call,
    v2_fakes,
    vobiz_post,
    water_point,
    xml_root,
)

SECRETARY = {"username": "alice", "cognito:groups": "[PANCHAYAT_SECRETARY]"}
SARPANCH = {"username": "sunita", "cognito:groups": ["SARPANCH"]}
TEXT = "Kal subah paani ki supply band rahegi. Tanki ki safai hogi."


@pytest.fixture
def v2(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fakes]:
    yield from v2_fakes(monkeypatch)


@pytest.fixture
def points(seeded: Repository) -> Repository:
    """wp-a: h1 (consented) and h3 (no consent); wp-b: h2 (consented)."""
    seeded.put_water_point(water_point("wp-a"))
    seeded.put_water_point(water_point("wp-b"))
    for hid, wpid in (("h1", "wp-a"), ("h3", "wp-a"), ("h2", "wp-b")):
        household = seeded.get_household(VID, hid)
        assert household is not None
        seeded.put_household(household.model_copy(update={"water_point_id": wpid}))
    return seeded


def post(path: str, body: Any = None, claims: dict[str, Any] | None = None) -> Any:
    return call(api.handler, HttpEvent("POST", path, body, claims=claims or SECRETARY))


def draft(text: str = TEXT, **extra: Any) -> str:
    status, body, _ = post(f"/api/villages/{VID}/broadcasts", {"text_hi": text, **extra})
    assert status == 201, body
    return str(body["id"])


def act(bid: str, action: str, claims: dict[str, Any] | None = None) -> tuple[int, Any]:
    status, body, _ = post(f"/api/villages/{VID}/broadcasts/{bid}/{action}", claims=claims)
    return status, body


def approved(**extra: Any) -> str:
    bid = draft(**extra)
    status, body = act(bid, "approve", SARPANCH)
    assert status == 200, body
    return bid


def deliver(v2: V2Fakes) -> dict[str, Any]:
    """Run the outbound Lambda for the last queued broadcast job."""
    job = v2.lambdas.events("broadcast", function=OUTBOUND_FN)[-1]
    return outbound.handler(job, LambdaContext())


def test_draft_approve_send_deliver(v2: V2Fakes, points: Repository) -> None:
    status, body, _ = post(
        f"/api/villages/{VID}/broadcasts",
        {"text_hi": f"  {TEXT}  ", "kind": "SUPPLY_CHANGE", "water_point_id": "wp-a"},
    )
    assert status == 201
    assert body["state"] == "DRAFT" and body["text_hi"] == TEXT
    assert body["created_by"] == "console:alice" and body["water_point_id"] == "wp-a"
    bid = body["id"]

    status, denied = act(bid, "approve")  # the secretary may not approve
    assert status == 403
    assert denied["denied"] is True and denied["policy_id"] == "broadcast-needs-sarpanch"
    assert denied["reason_hi"] and denied["reason_en"]
    stored = points.get_broadcast(VID, bid)
    assert stored is not None and stored.state is BroadcastState.DRAFT

    status, body = act(bid, "approve", SARPANCH)
    assert status == 200
    assert body["state"] == "APPROVED" and body["approved_by"] == "console:sunita"
    assert body["approved_at"] is not None
    assert act(bid, "approve", SARPANCH)[0] == 409  # only a DRAFT can be approved

    status, body = act(bid, "send")
    assert status == 202 and body["queued"] is True and body["id"] == bid
    [job] = v2.lambdas.events("broadcast", function=OUTBOUND_FN)
    assert job == {"kind": "broadcast", "village_id": VID, "broadcast_id": bid}

    out = deliver(v2)
    assert out == {"broadcast_id": bid, "recipients": 1}
    sent = points.get_broadcast(VID, bid)
    assert sent is not None and sent.state is BroadcastState.SENT and sent.recipients == 1
    assert sent.sent_at is not None
    assert calls.load_call(points, f"bc-{bid}-h1") is not None
    assert calls.load_call(points, f"bc-{bid}-h2") is None  # other water point
    assert calls.load_call(points, f"bc-{bid}-h3") is None  # no consent

    replies = run_call(f"bc-{bid}-h1", ["1"])
    root = xml_root(replies[0])
    assert root[0].text and root[0].text.endswith("/broadcast.greet.mp3")
    assert root[1].tag == "Speak" and root[1].text == TEXT  # no runtime TTS in this test
    loaded = calls.load_call(points, f"bc-{bid}-h1")
    assert loaded is not None and loaded.record.flow.purpose is Purpose.BROADCAST
    done = points.get_broadcast(VID, bid)
    assert done is not None and (done.delivered, done.heard) == (1, 1)


def test_village_wide_broadcast_counts_only_answered_calls(v2: V2Fakes, points: Repository) -> None:
    bid = approved()
    act(bid, "send")
    assert deliver(v2)["recipients"] == 2  # h1 and h2 (h3 has no consent)
    run_call(f"bc-{bid}-h1", ["2", "1"])  # hear it again, then "heard"
    unanswered = {"Event": "Hangup", "CallStatus": "no-answer"}
    vobiz_post("status", {"call_id": f"bc-{bid}-h2"}, unanswered)
    done = points.get_broadcast(VID, bid)
    assert done is not None and (done.delivered, done.heard) == (1, 1)
    finished = calls.load_call(points, f"bc-{bid}-h2")
    assert finished is not None and finished.record.finished


def test_picked_up_but_not_confirmed_is_delivered_not_heard(
    v2: V2Fakes, points: Repository
) -> None:
    bid = approved()
    act(bid, "send")
    deliver(v2)
    run_call(f"bc-{bid}-h1", [])
    vobiz_post("status", {"call_id": f"bc-{bid}-h1"}, {"Event": "Hangup"})
    done = points.get_broadcast(VID, bid)
    assert done is not None and (done.delivered, done.heard) == (1, 0)


def test_third_send_in_a_week_is_denied(v2: V2Fakes, points: Repository, clock: Clock) -> None:
    for _ in range(2):
        bid = approved()
        assert act(bid, "send")[0] == 202
        deliver(v2)
        clock.advance(hours=1)
    third = approved()
    status, body = act(third, "send")
    assert status == 403 and body["policy_id"] == "broadcast-weekly-limit"
    assert len(v2.lambdas.events("broadcast")) == 2
    _, listing, _ = call(api.handler, HttpEvent("GET", f"/api/villages/{VID}/broadcasts"))
    assert listing["sent_last_7_days"] == 2 and listing["weekly_limit"] == 2
    assert listing["broadcasts"][0]["id"] == third  # newest first

    clock.advance(days=7)
    assert act(third, "send")[0] == 202  # a week later the slot is free again


def test_unapproved_sends_are_denied_but_night_sends_go_out(
    v2: V2Fakes, points: Repository, clock: Clock
) -> None:
    bid = draft()
    status, body = act(bid, "send")
    assert status == 403 and body["policy_id"] == "broadcast-not-approved"
    act(bid, "approve", SARPANCH)
    clock.now = NIGHT
    status, body = act(bid, "send")
    assert status == 202  # no calling-hours rule any more
    assert len(v2.lambdas.events("broadcast")) == 1


def test_outbound_job_for_a_broadcast_that_may_not_go_out_is_denied(
    v2: V2Fakes, points: Repository
) -> None:
    bid = draft()
    job = {"kind": "broadcast", "village_id": VID, "broadcast_id": bid}
    assert outbound.handler(job, LambdaContext()) == {
        "status": "denied",
        "policy_id": "broadcast-not-approved",
    }


def test_cancel(v2: V2Fakes, points: Repository) -> None:
    bid = draft()
    status, body = act(bid, "cancel")
    assert status == 200 and body["state"] == "CANCELLED"
    status, body = act(bid, "send")
    assert status == 403 and body["policy_id"] == "broadcast-not-approved"
    sent = approved()
    act(sent, "send")
    deliver(v2)
    status, body = act(sent, "cancel")
    assert status == 409 and body["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"text_hi": "   "}, 400),
        ({"text_hi": "x" * 401}, 400),
        ({"text_hi": TEXT, "kind": "PARTY"}, 400),
        ({"text_hi": TEXT, "water_point_id": "wp-nowhere"}, 400),
    ],
)
def test_draft_validation(v2: V2Fakes, points: Repository, body: Any, status: int) -> None:
    got, payload, _ = post(f"/api/villages/{VID}/broadcasts", body)
    assert got == status and payload["error"]["code"] == "invalid_request"
    assert points.list_broadcasts(VID) == []


def test_unknown_broadcast_or_action_is_404(v2: V2Fakes, points: Repository) -> None:
    assert act("bc_nope", "approve", SARPANCH)[0] == 404
    bid = draft()
    status, body = act(bid, "explode")
    assert status == 404 and body["error"]["code"] == "not_found"


def test_approval_prerenders_the_announcement_audio(v2: V2Fakes, points: Repository) -> None:
    class FakeTts:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def ensure_all(self, text: str) -> list[str]:
            self.texts.append(text)
            return []

    tts = FakeTts()
    speech.use_tts(tts)  # type: ignore[arg-type]
    approved()
    assert tts.texts == [TEXT]


def test_approval_survives_a_tts_failure(v2: V2Fakes, points: Repository) -> None:
    class BrokenTts:
        def ensure_all(self, text: str) -> list[str]:
            raise RuntimeError("sarvam down")

    speech.use_tts(BrokenTts())  # type: ignore[arg-type]
    bid = approved()
    stored = points.get_broadcast(VID, bid)
    assert stored is not None and stored.state is BroadcastState.APPROVED


def test_withdrawn_households_are_not_recipients(v2: V2Fakes, points: Repository) -> None:
    points.put_household(
        resident("h7", "+919800000077", wpid="wp-a").model_copy(update={"active": False})
    )
    bid = approved(water_point_id="wp-a")
    act(bid, "send")
    assert deliver(v2)["recipients"] == 1


def test_sent_announcements_age_out_of_the_weekly_count(
    v2: V2Fakes, points: Repository, clock: Clock
) -> None:
    from jalsakshi.handlers import broadcasts

    bid = approved()
    act(bid, "send")
    deliver(v2)
    assert broadcasts.sent_last_week(points, VID) == 1
    clock.now = NOW + timedelta(days=8)
    assert broadcasts.sent_last_week(points, VID) == 0
