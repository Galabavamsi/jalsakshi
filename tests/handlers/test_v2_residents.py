"""Resident-side glue (ARCHITECTURE.md §15.1-§15.5): routing, water points, registration and
consent, complaints and their TicketFlow, per-point reconciling, and what residents hear."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from jalsakshi.core.models import (
    AccessKind,
    ConsentAction,
    ConsentStatus,
    DayCounts,
    DayStatus,
    DayStatusValue,
    NoteIssue,
    Operator,
    OperatorRole,
    PointStatus,
    Purpose,
    TicketOrigin,
    TicketReason,
    WaterAnswer,
    WaterPointKind,
)
from jalsakshi.core.tickets import Denied, TicketEventKind, new_ticket
from jalsakshi.handlers import config, residents, sfn_tasks, speech, tickets
from jalsakshi.store import Repository
from jalsakshi.voice.flow import ConsentAnswer

from .fakes import (
    DAY,
    NOW,
    PHONES,
    STAGE,
    TICKET_ARN,
    VID,
    Clock,
    LambdaContext,
    NamedFakeSfn,
    V2Fakes,
    checkin,
    resident,
    v2_fakes,
    village,
    water_point,
)

CTX = LambdaContext()


@pytest.fixture
def v2(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fakes]:
    yield from v2_fakes(monkeypatch)


def op(oid: str, role: OperatorRole, phone: str) -> Operator:
    return Operator(id=oid, role=role, phone_e164=phone, village_ids=[VID])


# --- routing ---------------------------------------------------------------------------------


def test_route_operator_chain_and_skip(v2: V2Fakes, seeded: Repository) -> None:
    mechanic = op("op-m", OperatorRole.HANDPUMP_MECHANIC, "+919800000044")
    sarpanch = op("op-s", OperatorRole.SARPANCH, "+919800000055")
    seeded.put_operator(mechanic)
    seeded.put_operator(sarpanch)
    seeded.put_water_point(
        water_point("wp-h", WaterPointKind.HANDPUMP, operator_ids=("ghost", "op-m"))
    )
    seeded.put_water_point(water_point("wp-p"))

    def routed(wpid: str | None, *skip: str) -> str | None:
        found = residents.route_operator(seeded, VID, wpid, skip=skip)
        return found.id if found else None

    assert routed("wp-h") == "op-m"  # the point's own operator (unknown ids are ignored)
    assert routed("wp-p") == "op-1"  # no operator on the point: the Nal Jal Mitra
    assert routed(None) == "op-1"
    assert routed("wp-missing") == "op-1"
    assert routed("wp-h", "op-m") == "op-1"
    assert routed("wp-h", "op-m", "op-1") == "op-s"  # then the sarpanch
    assert routed("wp-h", "op-m", "op-1", "op-s") is None
    assert routed("wp-p", "op-1") == "op-s"


def test_not_mine_lists_operators_who_disowned_a_ticket(v2: V2Fakes, seeded: Repository) -> None:
    ticket = seeded.open_ticket_if_none(new_ticket(VID, TicketReason.NO_SUPPLY, NOW))
    assert ticket is not None
    detail: dict[str, object] = {"note": "operator_reason", "code": "NOT_MINE", "not_mine": "op-1"}
    residents.update_ticket(seeded, ticket.id, lambda t: t, detail, "operator:op-1")
    residents.update_ticket(seeded, ticket.id, lambda t: t, {"note": "x"}, "test")
    stored = seeded.get_ticket_by_id(ticket.id)
    assert stored is not None and residents.not_mine(stored) == ["op-1"]
    assert sfn_tasks._not_mine(stored) == residents.not_mine(stored)


# --- water points ----------------------------------------------------------------------------


def test_point_for_access_reuses_or_creates_a_provisional_point(
    v2: V2Fakes, seeded: Repository
) -> None:
    village_ = seeded.get_village(VID)
    assert village_ is not None
    tap = residents.point_for_access(seeded, village_, AccessKind.HOUSE_TAP)
    assert tap.id == "wp-piped-1" and tap.kind is WaterPointKind.PIPED and tap.provisional
    assert tap.name == "Testgaon piped water supply"
    standpost = residents.point_for_access(seeded, village_, AccessKind.STANDPOST)
    assert standpost.id == tap.id  # both draw from the village's piped supply
    tanker = residents.point_for_access(seeded, village_, AccessKind.TANKER)
    assert tanker.kind is WaterPointKind.TANKER and tanker.id == "wp-tanker-1"


def test_point_for_access_never_overwrites_an_inactive_point(
    v2: V2Fakes, seeded: Repository
) -> None:
    retired = water_point(
        "wp-handpump-1", WaterPointKind.HANDPUMP, operator_ids=("op-1",), active=False
    )
    seeded.put_water_point(retired)
    village_ = seeded.get_village(VID)
    assert village_ is not None
    point = residents.point_for_access(seeded, village_, AccessKind.HANDPUMP)
    assert point.id == "wp-handpump-2" and point.provisional
    assert seeded.get_water_point(VID, "wp-handpump-1") == retired


def test_point_name_and_quorum(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_water_point(water_point("wp-q", quorum=4))
    seeded.put_water_point(water_point("wp-n"))
    village_ = seeded.get_village(VID)
    assert village_ is not None
    assert residents.point_quorum(seeded, village_, "wp-q") == 4
    assert residents.point_quorum(seeded, village_, "wp-n") == village_.quorum
    assert residents.point_quorum(seeded, village_, None) == village_.quorum
    assert residents.point_name(seeded, VID, "wp-q") == "टेस्टगाँव wp-q"
    assert residents.point_name(seeded, VID, None) is None
    assert residents.point_name(seeded, VID, "nope") is None


# --- registration and consent ----------------------------------------------------------------


def register(repo: Repository, hid: str, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = {
        "village_id": VID,
        "household_id": hid,
        "phone": "+919800000077",
        "call_id": "reg-1",
        "adult": True,
        "consent": ConsentAnswer.GRANTED,
        "digits": "1",
        "access": AccessKind.BOREWELL,
    }
    return residents.finish_registration(repo, **(defaults | kwargs))


def test_registration_updates_a_family_added_in_the_console(
    v2: V2Fakes, seeded: Repository
) -> None:
    added = resident("hh-c", "+919800000077", status=ConsentStatus.NONE).model_copy(
        update={"registered_via": "console", "display_name": "Sita", "active": True}
    )
    seeded.put_household(added)
    household = register(seeded, "hh-c")
    assert household is not None and household.registered_via == "console"
    assert household.display_name == "Sita" and household.consent_status is ConsentStatus.GRANTED
    assert household.water_point_id == "wp-borewell-1"
    assert (
        household.consent is not None and household.consent.evidence_ref == "consent-ledger:reg-1"
    )
    feed = seeded.list_activity(NOW - timedelta(hours=1))
    assert any(e.kind == "consent" and "+91XXXXXX0077" in e.text_en for e in feed)


def test_declining_marks_a_known_family_declined_and_inactive(
    v2: V2Fakes, seeded: Repository
) -> None:
    seeded.put_household(resident("hh-c", "+919800000077", status=ConsentStatus.NONE))
    assert register(seeded, "hh-c", consent=ConsentAnswer.DECLINED, digits="3") is None
    stored = seeded.get_household(VID, "hh-c")
    assert stored is not None and stored.consent_status is ConsentStatus.DECLINED
    assert not stored.active
    [event] = seeded.list_consent_events(VID)
    assert event.action is ConsentAction.DECLINED and event.digits == "3"


def test_registration_without_an_access_answer_has_no_point(
    v2: V2Fakes, seeded: Repository
) -> None:
    household = register(seeded, "hh-x", access=None)
    assert household is not None and household.access is None
    assert household.water_point_id is None and seeded.list_water_points(VID) == []


def test_withdraw_erases_the_household_and_keeps_a_masked_ledger_entry(
    v2: V2Fakes, seeded: Repository
) -> None:
    household = seeded.get_household(VID, "h2")
    assert household is not None
    residents.withdraw(seeded, household, call_id="c-9")
    assert seeded.get_household(VID, "h2") is None
    assert seeded.find_households_by_phone(PHONES[1]) == []
    [event] = seeded.list_consent_events(VID)
    assert (event.action, event.call_id, event.digits) == (ConsentAction.WITHDRAWN, "c-9", "9")
    assert event.phone_masked == "+91XXXXXX0002"


def test_notice_fingerprint_is_stable(v2: V2Fakes, seeded: Repository) -> None:
    assert residents.notice_sha256() == residents.notice_sha256()
    assert residents.new_household_id(PHONES[0]) == residents.new_household_id(PHONES[0])
    assert residents.new_household_id(PHONES[0]) != residents.new_household_id(PHONES[1])
    assert residents.new_household_id(PHONES[0]).startswith("hh-")


# --- complaints --------------------------------------------------------------------------------


def test_reporting_twice_from_the_same_family_changes_nothing(
    v2: V2Fakes, seeded: Repository
) -> None:
    village_ = seeded.get_village(VID)
    household = seeded.get_household(VID, "h1")
    assert village_ is not None and household is not None
    first = residents.report_problem(
        seeded, village_, household, TicketReason.NO_SUPPLY, origin=TicketOrigin.REPORT
    )
    again = residents.report_problem(
        seeded, village_, household, TicketReason.NO_SUPPLY, origin=TicketOrigin.REPORT
    )
    assert again.id == first.id and again.reporters == ["h1"] and again.events == []
    other = residents.report_problem(
        seeded, village_, household, TicketReason.DIRTY, origin=TicketOrigin.REPORT
    )
    assert other.id != first.id and other.number == 2  # one ticket per point and reason
    assert v2.sfn.names == [first.id, other.id]


def test_a_voice_issue_is_added_to_a_ticket_that_had_none(v2: V2Fakes, seeded: Repository) -> None:
    village_ = seeded.get_village(VID)
    household = seeded.get_household(VID, "h1")
    assert village_ is not None and household is not None
    residents.report_problem(
        seeded, village_, household, TicketReason.LEAK, origin=TicketOrigin.REPORT
    )
    issue = NoteIssue(
        issue=TicketReason.LEAK,
        summary_hi="pipe",
        summary_en="Leak",
        transcript="pipe",
        confidence=0.9,
    )
    joined = residents.report_problem(
        seeded, village_, household, TicketReason.LEAK, origin=TicketOrigin.VOICE_NOTE, issue=issue
    )
    assert joined.issue == issue and joined.reporters == ["h1"]
    assert joined.events[-1].detail["note"] == "another_report"


def test_start_ticket_flow_is_idempotent(v2: V2Fakes, seeded: Repository) -> None:
    ticket = new_ticket(VID, TicketReason.NO_SUPPLY, NOW, ticket_id="tkt_x")
    assert residents.start_ticket_flow(ticket) is True
    assert residents.start_ticket_flow(ticket) is False  # ExecutionAlreadyExists
    [(arn, payload)] = v2.sfn.executions
    assert arn == TICKET_ARN and v2.sfn.names == ["tkt_x"]
    assert payload["ticket_id"] == "tkt_x" and payload["date"] == DAY.isoformat()


def test_start_ticket_flow_without_a_workflow_or_on_other_errors(
    v2: V2Fakes, seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket = new_ticket(VID, TicketReason.NO_SUPPLY, NOW, ticket_id="tkt_y")

    class Throttled(NamedFakeSfn):
        def start_execution(self, **_: Any) -> dict[str, Any]:  # type: ignore[override]
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "StartExecution")

    config.use_client("stepfunctions", Throttled())
    with pytest.raises(ClientError):
        residents.start_ticket_flow(ticket)
    monkeypatch.delenv("JALSAKSHI_TICKET_SFN_ARN")
    config.settings.cache_clear()
    assert residents.start_ticket_flow(ticket) is False


def test_update_ticket_notes_and_mutates_in_one_save(v2: V2Fakes, seeded: Repository) -> None:
    ticket = seeded.open_ticket_if_none(new_ticket(VID, TicketReason.LEAK, NOW))
    assert ticket is not None
    result = residents.update_ticket(
        seeded,
        ticket.id,
        lambda t: t.model_copy(update={"quorum": 3}),
        {"note": "test"},
        "console:alice",
    )
    assert not isinstance(result, Denied)
    assert result.quorum == 3 and result.events[-1].detail == {"note": "test"}
    stored = seeded.get_ticket_by_id(ticket.id)
    assert stored == result
    missing = residents.update_ticket(seeded, "tkt_nope", lambda t: t, {}, "x")
    assert isinstance(missing, Denied)
    assert isinstance(residents.update_ticket(seeded, ticket.id, lambda t: t, {}, " "), Denied)


# --- reconciling per water point -------------------------------------------------------------


@pytest.fixture
def two_points(v2: V2Fakes, seeded: Repository) -> Repository:
    """wp-a: h1, h2. wp-b: h4, h5. Every family says no water today."""
    seeded.put_water_point(water_point("wp-a"))
    seeded.put_water_point(water_point("wp-b"))
    for hid, wpid in (("h1", "wp-a"), ("h2", "wp-a")):
        household = seeded.get_household(VID, hid)
        assert household is not None
        seeded.put_household(household.model_copy(update={"water_point_id": wpid}))
    for hid, phone in (("h4", "+919800000044"), ("h5", "+919800000045")):
        seeded.put_household(resident(hid, phone, wpid="wp-b"))
    for hid, wpid in (("h1", "wp-a"), ("h2", "wp-a"), ("h4", "wp-b"), ("h5", "wp-b")):
        seeded.put_checkin(
            checkin(hid, water=WaterAnswer.NO).model_copy(update={"water_point_id": wpid})
        )
    return seeded


def test_reconcile_opens_one_ticket_per_failing_point(
    v2: V2Fakes, two_points: Repository, clock: Clock
) -> None:
    out = sfn_tasks.reconcile_day({"village_id": VID, "date": DAY.isoformat()}, CTX)
    assert out["status"] == "NO_SUPPLY" and len(out["tickets_opened"]) == 2
    first, second = (two_points.get_ticket_by_id(t) for t in out["tickets_opened"])
    assert first is not None and second is not None
    assert out["ticket_id"] == first.id and out["ticket_reason"] == "NO_SUPPLY"
    assert {first.water_point_id, second.water_point_id} == {"wp-a", "wp-b"}
    by_point = {t.water_point_id: t for t in (first, second)}
    assert sorted(by_point["wp-a"].reporters) == ["h1", "h2"]
    assert sorted(by_point["wp-b"].reporters) == ["h4", "h5"]
    assert {first.number, second.number} == {1, 2}
    assert all(t.origin is TicketOrigin.RECONCILE and t.quorum == 2 for t in (first, second))
    # The CheckInRun starts TicketFlow for the first; the second is started by name here.
    assert v2.sfn.names == [second.id]
    status = two_points.get_day_status(VID, DAY)
    assert status is not None and len(status.points) == 2

    # Verification for wp-a calls only the families on wp-a.
    tickets.apply_event(two_points, by_point["wp-a"].id, TicketEventKind.NOTIFIED, "test")
    tickets.apply_event(two_points, by_point["wp-a"].id, TicketEventKind.OPERATOR_FIXED, "test")
    clock.advance(minutes=30)
    verify = sfn_tasks.start_verification(
        {"ticket_id": by_point["wp-a"].id, "verify": {"round": 0}}, CTX
    )
    assert sorted(h["household_id"] for h in verify["households"]) == ["h1", "h2"]

    again = sfn_tasks.reconcile_day({"village_id": VID, "date": DAY.isoformat()}, CTX)
    assert again["tickets_opened"] == [] and again["ticket_id"] is None
    assert len(v2.sfn.names) == 1
    for ticket in two_points.list_open_tickets(VID):
        assert ticket.events[-1].detail["note"] == "day_still_bad"


def test_a_later_verify_answer_does_not_hide_a_daily_reporter(
    v2: V2Fakes, two_points: Repository
) -> None:
    later = NOW + timedelta(hours=1)
    two_points.put_checkin(
        checkin("h1", water=WaterAnswer.YES, purpose=Purpose.VERIFY, at=later).model_copy(
            update={"water_point_id": "wp-a"}
        )
    )
    out = sfn_tasks.reconcile_day({"village_id": VID, "date": DAY.isoformat()}, CTX)
    tickets_ = [two_points.get_ticket_by_id(t) for t in out["tickets_opened"]]
    wp_a = next(t for t in tickets_ if t is not None and t.water_point_id == "wp-a")
    assert sorted(wp_a.reporters) == ["h1", "h2"]


def test_reconcile_skips_points_that_already_have_a_ticket(
    v2: V2Fakes, two_points: Repository
) -> None:
    village_ = two_points.get_village(VID)
    h1 = two_points.get_household(VID, "h1")
    assert village_ is not None and h1 is not None
    reported = residents.report_problem(
        two_points, village_, h1, TicketReason.NO_SUPPLY, origin=TicketOrigin.REPORT
    )
    out = sfn_tasks.reconcile_day({"village_id": VID, "date": DAY.isoformat()}, CTX)
    [opened] = out["tickets_opened"]
    ticket = two_points.get_ticket_by_id(opened)
    assert ticket is not None and ticket.water_point_id == "wp-b"
    assert two_points.get_open_ticket(
        VID, "wp-a", TicketReason.NO_SUPPLY
    ) == two_points.get_ticket_by_id(reported.id)


# --- what residents hear ---------------------------------------------------------------------


def test_status_text_without_data(v2: V2Fakes, seeded: Repository) -> None:
    village_ = seeded.get_village(VID)
    assert village_ is not None
    text = residents.status_text_hi(seeded, village_, DAY)
    assert text == (
        "Aaj Testgaon mein. Aaj ke liye abhi poori jaankari nahi hai. "
        "Abhi koi shikayat khuli nahi hai."
    )


def test_status_text_per_point_and_oldest_complaint(
    v2: V2Fakes, seeded: Repository, clock: Clock
) -> None:
    seeded.put_village(village().model_copy(update={"name_hi": "टेस्टगाँव"}))
    seeded.put_water_point(water_point("wp-a"))
    seeded.put_day_status(
        DayStatus(
            village_id=VID,
            date=DAY,
            status=DayStatusValue.NO_SUPPLY,
            counts=DayCounts(answered=2, no=2),
            rule_version="r2",
            computed_at=NOW,
            points=[
                PointStatus(
                    water_point_id="wp-a",
                    status=DayStatusValue.NO_SUPPLY,
                    counts=DayCounts(answered=2, no=2),
                ),
                PointStatus(
                    water_point_id=None,
                    status=DayStatusValue.SUPPLIED,
                    counts=DayCounts(answered=2, yes=2),
                ),
            ],
        )
    )
    seeded.open_ticket_if_none(new_ticket(VID, TicketReason.NO_SUPPLY, NOW - timedelta(days=2)))
    village_ = seeded.get_village(VID)
    assert village_ is not None
    text = residents.status_text_hi(seeded, village_, DAY)
    assert text.startswith("Aaj टेस्टगाँव mein. टेस्टगाँव wp-a: paani nahi aaya. gaon: paani aaya.")
    assert "Khuli shikayatein: 1." in text and "2 din se khuli hai" in text


def test_runtime_tts_needs_bucket_and_key(
    v2: V2Fakes, seeded: Repository, monkeypatch: pytest.MonkeyPatch, aws: dict[str, Any]
) -> None:
    assert speech.runtime_tts() is None  # no prompts bucket, no Sarvam key
    monkeypatch.setenv("JALSAKSHI_PROMPTS_BUCKET", "prompts-bucket")
    config.settings.cache_clear()
    assert speech.runtime_tts() is None  # still no key
    aws["ssm"].put_parameter(
        Name=f"/jalsakshi/{STAGE}/sarvam_api_key", Type="SecureString", Value="sk-test"
    )
    config.secrets.clear()
    tts = speech.runtime_tts()
    assert tts is not None and speech.runtime_tts() is tts  # built once, then cached
    auth = speech.vobiz_auth()
    assert (auth.auth_id, auth.auth_token) == ("MA_TEST", "vobiz-token")
