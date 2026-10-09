"""Store additions for v2: water points, phone lookup, consent ledger, per-point guards (§15)."""

from __future__ import annotations

from datetime import timedelta

from jalsakshi.core.models import (
    Broadcast,
    BroadcastKind,
    ConsentAction,
    ConsentEvent,
    Household,
    Operator,
    OperatorRole,
    QualityMethod,
    QualityResult,
    QualityTest,
    Ticket,
    TicketReason,
    TicketState,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.store import Repository

from .factories import DAY, NOW


def _ticket(tid: str, point: str | None, reason: TicketReason) -> Ticket:
    return Ticket(
        id=tid,
        village_id="v1",
        reason=reason,
        opened_at=NOW,
        updated_at=NOW,
        water_point_id=point,
    )


def test_water_points_round_trip(repo: Repository) -> None:
    tap = WaterPoint(id="wp1", village_id="v1", kind=WaterPointKind.PIPED, name="Tank")
    pump = WaterPoint(
        id="wp2", village_id="v1", kind=WaterPointKind.HANDPUMP, name="HP", active=False
    )
    repo.put_water_point(tap)
    repo.put_water_point(pump)
    assert repo.get_water_point("v1", "wp1") == tap
    assert [p.id for p in repo.list_water_points("v1")] == ["wp1", "wp2"]
    assert [p.id for p in repo.list_water_points("v1", active_only=True)] == ["wp1"]


def test_phone_lookup_finds_households_and_operators(repo: Repository) -> None:
    repo.put_household(Household(id="h1", village_id="v1", phone_e164="+919000000001"))
    repo.put_household(Household(id="h2", village_id="v2", phone_e164="+919000000001"))
    repo.put_operator(
        Operator(
            id="op1",
            role=OperatorRole.NAL_JAL_MITRA,
            phone_e164="+919000000001",
            village_ids=["v1"],
        )
    )
    roles = repo.lookup_phone("+919000000001")
    assert sorted(roles.households) == [("v1", "h1"), ("v2", "h2")]
    assert roles.operators == ["op1"]
    assert roles.known
    assert not repo.lookup_phone("+919999999999").known
    assert {h.id for h in repo.find_households_by_phone("+919000000001")} == {"h1", "h2"}


def test_changing_a_phone_moves_the_lookup(repo: Repository) -> None:
    repo.put_household(Household(id="h1", village_id="v1", phone_e164="+919000000001"))
    repo.put_household(Household(id="h1", village_id="v1", phone_e164="+919000000002"))
    assert not repo.lookup_phone("+919000000001").known
    assert repo.lookup_phone("+919000000002").households == [("v1", "h1")]


def test_one_open_ticket_per_point_and_reason(repo: Repository) -> None:
    assert repo.open_ticket_if_none(_ticket("t1", "wp1", TicketReason.NO_SUPPLY)) is not None
    assert repo.open_ticket_if_none(_ticket("t2", "wp1", TicketReason.NO_SUPPLY)) is None
    assert repo.open_ticket_if_none(_ticket("t3", "wp1", TicketReason.DIRTY)) is not None
    assert repo.open_ticket_if_none(_ticket("t4", "wp2", TicketReason.NO_SUPPLY)) is not None
    assert repo.open_ticket_if_none(_ticket("t5", None, TicketReason.NO_SUPPLY)) is not None
    assert {tk.id for tk in repo.list_open_tickets("v1")} == {"t1", "t3", "t4", "t5"}
    found = repo.get_open_ticket("v1", "wp1", TicketReason.NO_SUPPLY)
    assert found is not None and found.id == "t1"
    assert repo.get_open_ticket("v1", "wp9", TicketReason.NO_SUPPLY) is None
    assert repo.get_open_ticket("v1") is not None


def test_closing_releases_only_that_guard(repo: Repository) -> None:
    opened = repo.open_ticket_if_none(_ticket("t1", "wp1", TicketReason.NO_SUPPLY))
    repo.open_ticket_if_none(_ticket("t2", "wp1", TicketReason.DIRTY))
    assert opened is not None
    closed = opened.model_copy(
        update={"state": TicketState.CLOSED_VERIFIED, "updated_at": NOW + timedelta(hours=1)}
    )
    repo.save_ticket(closed, opened.updated_at)
    assert [tk.id for tk in repo.list_open_tickets("v1")] == ["t2"]
    assert repo.open_ticket_if_none(_ticket("t3", "wp1", TicketReason.NO_SUPPLY)) is not None


def test_ticket_numbers_count_up_per_village(repo: Repository) -> None:
    assert [repo.next_ticket_number("v1") for _ in range(3)] == [1, 2, 3]
    assert repo.next_ticket_number("v2") == 1


def test_consent_ledger_is_append_only(repo: Repository) -> None:
    event = ConsentEvent(
        village_id="v1",
        household_id="h1",
        phone_masked="+91XXXXXX0001",
        action=ConsentAction.GRANTED,
        notice_version="hi-1",
        notice_sha256="ab" * 32,
        channel="ivr_keypad",
        call_id="c1",
        digits="1",
        at=NOW,
    )
    assert repo.append_consent_event(event)
    assert not repo.append_consent_event(event)
    later = event.model_copy(update={"action": ConsentAction.WITHDRAWN, "at": NOW + timedelta(1)})
    assert repo.append_consent_event(later)
    assert [e.action for e in repo.list_consent_events("v1")] == [
        ConsentAction.GRANTED,
        ConsentAction.WITHDRAWN,
    ]


def test_missed_calls_are_logged_per_number(repo: Repository) -> None:
    repo.record_missed_call("+919000000001", NOW, {"call_uuid": "u1"})
    repo.record_missed_call("+919000000001", NOW + timedelta(minutes=5), {"call_uuid": "u2"})
    since = NOW + timedelta(minutes=1)
    assert [m["call_uuid"] for m in repo.list_missed_calls("+919000000001", since)] == ["u2"]
    assert len(repo.list_missed_calls("+919000000001", NOW)) == 2


def test_broadcasts_and_quality_tests(repo: Repository) -> None:
    first = Broadcast(
        id="b1",
        village_id="v1",
        kind=BroadcastKind.SUPPLY_CHANGE,
        text_hi="Kal subah paani nahi aayega.",
        created_by="console:sec",
        created_at=NOW,
    )
    second = first.model_copy(update={"id": "b2", "created_at": NOW + timedelta(hours=1)})
    repo.put_broadcast(first)
    repo.put_broadcast(second)
    assert [b.id for b in repo.list_broadcasts("v1")] == ["b2", "b1"]
    assert repo.get_broadcast("v1", "b1") == first
    test = QualityTest(
        id="q1",
        village_id="v1",
        water_point_id="wp1",
        tested_at=NOW,
        method=QualityMethod.FTK,
        result=QualityResult.UNSAFE,
        parameters={"bacteria": "present"},
        entered_by="console:sec",
    )
    repo.put_quality_test(test)
    assert repo.list_quality_tests("v1") == [test]


def test_checkins_between_spans_days_and_purposes(repo: Repository) -> None:
    from .factories import checkin

    repo.put_checkin(checkin("h1", day=DAY - timedelta(days=1)))
    repo.put_checkin(checkin("h1", day=DAY))
    repo.put_checkin(checkin("h2", day=DAY + timedelta(days=1)))
    found = repo.list_checkins_between("v1", DAY - timedelta(days=1), DAY)
    assert sorted((c.date, c.household_id) for c in found) == [
        (DAY - timedelta(days=1), "h1"),
        (DAY, "h1"),
    ]
