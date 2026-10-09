"""v2 Vobiz webhooks end to end: missed calls, registration, the REPORT menu, stop, operator
reasons, daily fallbacks and voice-note hand-off (ARCHITECTURE.md §15.3-§15.7)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest

from jalsakshi.core.models import (
    AccessKind,
    BlockerCode,
    CallOutcome,
    ConsentAction,
    ConsentStatus,
    Fallback,
    OperatorRole,
    Purpose,
    TicketOrigin,
    TicketReason,
    WaterAnswer,
    WaterPointKind,
)
from jalsakshi.core.tickets import new_ticket
from jalsakshi.handlers import calls, config, ivr_vobiz, outbound, residents, sfn_tasks, speech
from jalsakshi.handlers.ivr_vobiz import REJECT_XML, normalise_phone
from jalsakshi.store import Repository
from jalsakshi.voice.actions import Play

from .fakes import (
    DAY,
    MORNING,
    NIGHT,
    NOTES_FN,
    OUTBOUND_FN,
    PHONES,
    TICKET_ARN,
    VID,
    Clock,
    LambdaContext,
    V2Fakes,
    next_turn,
    operator,
    run_call,
    v2_fakes,
    village,
    vobiz_post,
    water_point,
    xml_root,
)

CDN = "https://cdn.example.test/prompts/hi"
NEW_PHONE = "+919800000077"


@pytest.fixture
def v2(seeded: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[V2Fakes]:
    yield from v2_fakes(monkeypatch)


def missed(phone: str) -> tuple[int, str]:
    return vobiz_post("inbound", form={"From": phone, "To": "+918000000000"})


def on_point(repo: Repository, wpid: str, *hids: str, quorum: int | None = None) -> None:
    repo.put_water_point(water_point(wpid, quorum=quorum))
    for hid in hids:
        household = repo.get_household(VID, hid)
        assert household is not None
        repo.put_household(household.model_copy(update={"water_point_id": wpid}))


def inbound_village(repo: Repository) -> None:
    repo.put_village(village().model_copy(update={"inbound": True, "name_hi": "टेस्टगाँव"}))


def callback_call(repo: Repository, phone: str, missed_at: str = "m1") -> str:
    out = outbound.callback(repo, phone, 0, missed_at)
    assert out["status"] == "pending", out
    return str(out["call_id"])


def plays(xml: str) -> list[str]:
    """Text of each top-level Play/Speak element (audio URL or spoken text)."""
    return [el.text or "" for el in xml_root(xml) if el.tag in {"Play", "Speak"}]


# --- missed calls --------------------------------------------------------------------------------


def test_missed_call_in_hours_is_rejected_and_queues_one_callback(
    v2: V2Fakes, seeded: Repository, clock: Clock
) -> None:
    clock.now = MORNING
    status, xml = missed("09800000001")  # local format: normalised to +91
    assert status == 200 and '<Hangup reason="rejected"' in xml and xml == REJECT_XML
    [logged] = seeded.list_missed_calls(PHONES[0], MORNING - timedelta(minutes=1))
    assert logged["call_uuid"] == "vobiz-call-1" and logged["callback"] is True
    [job] = v2.lambdas.events("callback", function=OUTBOUND_FN)
    assert job["phone"] == PHONES[0] and job["delay_s"] == 0
    assert datetime.fromisoformat(job["missed_at"]) >= MORNING
    assert v2.scheduler.schedules == {}

    clock.advance(minutes=1)
    _, again = missed(PHONES[0])
    assert again == REJECT_XML
    assert len(v2.lambdas.events("callback")) == 1  # cooldown: logged, not called back
    assert [m["callback"] for m in seeded.list_missed_calls(PHONES[0], MORNING)] == [True, False]
    feed = seeded.list_activity(MORNING - timedelta(hours=1))
    assert any(e.kind == "missed_call" and PHONES[0] not in e.text_en for e in feed)


def test_rings_inside_the_cooldown_do_not_delay_the_next_callback(
    v2: V2Fakes, seeded: Repository, clock: Clock
) -> None:
    clock.now = MORNING
    missed(PHONES[0])
    clock.advance(minutes=1)
    missed(PHONES[0])  # suppressed, but shown in the console feed
    feed = seeded.list_activity(MORNING - timedelta(hours=1))
    assert any("already on its way" in e.text_en for e in feed)
    clock.advance(minutes=1.5)  # 2.5 min after the first call-back, 1.5 after the suppressed ring
    missed(PHONES[0])
    assert len(v2.lambdas.events("callback")) == 2
    assert calls.callbacks_today(seeded, PHONES[0]) == 2


def test_missed_call_at_night_is_called_back_straight_away(
    v2: V2Fakes, seeded: Repository, clock: Clock
) -> None:
    clock.now = NIGHT  # 22:30 IST: the family asked for the call, so hours do not apply
    status, xml = missed(PHONES[0])
    assert status == 200 and xml == REJECT_XML
    [job] = v2.lambdas.events("callback")
    assert job["phone"] == PHONES[0]
    assert v2.scheduler.schedules == {}


@pytest.mark.parametrize("caller", ["", "anonymous", "0000000000", "+14155550123", "12345"])
def test_withheld_or_garbage_caller_id_is_rejected_without_a_callback(
    v2: V2Fakes, seeded: Repository, clock: Clock, caller: str
) -> None:
    clock.now = MORNING
    form = {"To": "+918000000000"} | ({"From": caller} if caller else {})
    status, xml = vobiz_post("inbound", form=form)
    assert status == 200 and xml == REJECT_XML
    assert v2.lambdas.invocations == [] and v2.scheduler.schedules == {}


def test_missed_call_is_rejected_even_when_queueing_fails(
    v2: V2Fakes, seeded: Repository, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def throttled(**_: Any) -> None:
        raise RuntimeError("Lambda throttled")

    monkeypatch.setattr(v2.lambdas, "invoke", throttled)
    clock.now = MORNING
    status, xml = missed(PHONES[0])
    assert status == 200 and xml == REJECT_XML


def test_inbound_with_a_wrong_token_is_404(v2: V2Fakes, seeded: Repository) -> None:
    from .fakes import HttpEvent, call

    event = HttpEvent("POST", "/ivr/vobiz/wrong/inbound", form={"CallUUID": "x", "From": "1"})
    status, _, _ = call(ivr_vobiz.handler, event)
    assert status == 404 and v2.lambdas.invocations == []


def test_night_missed_call_without_a_scheduler_is_only_logged(
    v2: V2Fakes, seeded: Repository, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JALSAKSHI_SCHEDULER_GROUP")
    config.settings.cache_clear()
    clock.now = NIGHT
    assert missed(PHONES[0])[1] == REJECT_XML
    assert v2.scheduler.schedules == {}
    assert len(seeded.list_missed_calls(PHONES[0], NIGHT - timedelta(minutes=1))) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9800000001", "+919800000001"),
        ("09800000001", "+919800000001"),
        ("+919800000001", "+919800000001"),
        ("919800000001", "+919800000001"),
        ("+91 98000-00001", "+919800000001"),
        ("+14155550123", None),
        ("+447700900123", None),
        ("0000000000", None),
        ("+910123456789", None),
        ("", None),
        (None, None),
        ("anonymous", None),
    ],
)
def test_normalise_phone(raw: str | None, expected: str | None) -> None:
    assert normalise_phone(raw) == expected


# --- REGISTER --------------------------------------------------------------------------------


def test_registration_call_creates_household_point_and_ledger(
    v2: V2Fakes, seeded: Repository
) -> None:
    inbound_village(seeded)
    call_id = callback_call(seeded, NEW_PHONE)
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None and loaded.record.flow.purpose is Purpose.REGISTER
    hid = residents.new_household_id(NEW_PHONE)
    assert seeded.get_household(VID, hid) is None  # created only on consent

    replies = run_call(call_id, ["1", "1", "3", "#"])  # adult, agree, handpump
    assert plays(replies[0])[:2] == [f"{CDN}/register.greet.mp3", f"{CDN}/register.notice.mp3"]
    assert plays(replies[-1]) == [f"{CDN}/register.done.mp3"]
    assert next_turn(replies[-1]) is None and "<Hangup" in replies[-1]

    household = seeded.get_household(VID, hid)
    assert household is not None
    assert household.consent_status is ConsentStatus.GRANTED and household.active
    assert household.access is AccessKind.HANDPUMP and household.registered_via == "ivr"
    assert household.consent is not None and household.consent.channel == "ivr_keypad"
    assert household.consent.notice_version == "hi-2" and household.consent.call_id == call_id
    point = seeded.get_water_point(VID, household.water_point_id or "")
    assert point is not None and point.kind is WaterPointKind.HANDPUMP and point.provisional
    assert point.id == "wp-handpump-1" and point.name_hi == "टेस्टगाँव हैंडपंप"
    assert seeded.find_households_by_phone(NEW_PHONE) == [household]

    [event] = seeded.list_consent_events(VID)
    assert event.action is ConsentAction.GRANTED and event.household_id == hid
    assert event.phone_masked == "+91XXXXXX0077" and NEW_PHONE not in event.model_dump_json()
    assert event.notice_sha256 == residents.notice_sha256() and len(event.notice_sha256) == 64
    assert (event.notice_version, event.channel, event.digits) == ("hi-2", "ivr_keypad", "1")
    assert event.call_id == call_id
    finished = calls.load_call(seeded, call_id)
    assert finished is not None and finished.record.finished


@pytest.mark.parametrize(
    ("keys", "action"),
    [(["1", "3"], ConsentAction.DECLINED), (["2"], ConsentAction.MINOR)],
)
def test_registration_refusals_write_only_the_ledger(
    v2: V2Fakes, seeded: Repository, keys: list[str], action: ConsentAction
) -> None:
    inbound_village(seeded)
    call_id = callback_call(seeded, NEW_PHONE)
    replies = run_call(call_id, list(keys))
    closing = "register.declined" if action is ConsentAction.DECLINED else "register.minor"
    assert plays(replies[-1]) == [f"{CDN}/{closing}.mp3"]
    [event] = seeded.list_consent_events(VID)
    assert event.action is action and event.phone_masked == "+91XXXXXX0077"
    assert seeded.get_household(VID, residents.new_household_id(NEW_PHONE)) is None
    assert seeded.find_households_by_phone(NEW_PHONE) == []
    assert seeded.list_water_points(VID) == []


def test_registration_silence_writes_nothing(v2: V2Fakes, seeded: Repository) -> None:
    inbound_village(seeded)
    call_id = callback_call(seeded, NEW_PHONE)
    replies = run_call(call_id, [None, None])  # no key, twice
    assert plays(replies[-1]) == [f"{CDN}/register.no_answer.mp3"]
    assert seeded.list_consent_events(VID) == []
    assert seeded.find_households_by_phone(NEW_PHONE) == []


def test_silence_at_the_consent_question_is_never_consent(v2: V2Fakes, seeded: Repository) -> None:
    inbound_village(seeded)
    call_id = callback_call(seeded, NEW_PHONE)
    run_call(call_id, ["1", None, "7"])  # adult, then timeout and an invalid key
    assert seeded.list_consent_events(VID) == []
    assert seeded.find_households_by_phone(NEW_PHONE) == []


def test_hearing_the_notice_again_then_agreeing(v2: V2Fakes, seeded: Repository) -> None:
    inbound_village(seeded)
    call_id = callback_call(seeded, NEW_PHONE)
    replies = run_call(call_id, ["1", "2", "1", "1", "#"])  # adult, notice again, agree, house tap
    gather = xml_root(replies[2]).find("Gather")
    assert plays(replies[2]) == [f"{CDN}/register.notice.mp3"] and gather is not None
    household = seeded.get_household(VID, residents.new_household_id(NEW_PHONE))
    assert household is not None and household.access is AccessKind.HOUSE_TAP
    assert household.water_point_id == "wp-piped-1"


def test_hangup_during_registration_finishes_without_consent(
    v2: V2Fakes, seeded: Repository
) -> None:
    inbound_village(seeded)
    call_id = callback_call(seeded, NEW_PHONE)
    run_call(call_id, ["1"])
    vobiz_post("status", {"call_id": call_id}, {"Event": "Hangup", "CallStatus": "completed"})
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None and loaded.record.finished
    assert seeded.list_consent_events(VID) == []


# --- REPORT ------------------------------------------------------------------------------------


def test_report_no_water_opens_numbered_ticket_and_announces_it(
    v2: V2Fakes, seeded: Repository
) -> None:
    on_point(seeded, "wp-a", "h1", "h2", quorum=3)
    call_id = callback_call(seeded, PHONES[0])
    replies = run_call(call_id, ["1"])
    assert plays(replies[0])[0] == f"{CDN}/report.greet.mp3"
    assert plays(replies[-1]) == [f"{CDN}/report.ack.mp3", f"{CDN}/report.number.n1.mp3"]
    assert [el.tag for el in xml_root(replies[-1])][-1] == "Hangup"

    [report] = seeded.list_checkins(VID, DAY, Purpose.REPORT)
    assert (report.water, report.outcome, report.water_point_id) == (
        WaterAnswer.NO,
        CallOutcome.ANSWERED,
        "wp-a",
    )
    assert report.household_id == "h1" and report.call_id == call_id and report.attempt == 1
    ticket = seeded.get_open_ticket(VID, "wp-a", TicketReason.NO_SUPPLY)
    assert ticket is not None
    assert (ticket.number, ticket.origin, ticket.reporters, ticket.quorum) == (
        1,
        TicketOrigin.REPORT,
        ["h1"],
        1,
    )
    [(arn, payload)] = v2.sfn.executions
    assert arn == TICKET_ARN and v2.sfn.names == [ticket.id]
    assert payload == {
        "village_id": VID,
        "reason": "NO_SUPPLY",
        "ticket_id": ticket.id,
        "date": DAY.isoformat(),
    }
    day = seeded.get_day_status(VID, DAY)
    assert day is not None
    [point] = [p for p in day.points if p.water_point_id == "wp-a"]
    assert point.counts.no == 1
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None and loaded.record.ticket_number == 1

    # A second family reporting the same problem joins the same complaint.
    second = callback_call(seeded, PHONES[1])
    replies = run_call(second, ["1"])
    assert plays(replies[-1])[-1] == f"{CDN}/report.number.n1.mp3"
    joined = seeded.get_open_ticket(VID, "wp-a", TicketReason.NO_SUPPLY)
    assert joined is not None and joined.id == ticket.id
    assert joined.reporters == ["h1", "h2"] and joined.quorum == 2  # min(point quorum 3, 2)
    assert joined.events[-1].kind == "NOTE"
    assert joined.events[-1].detail == {"note": "another_report", "household_id": "h2"}
    assert len(v2.sfn.executions) == 1
    assert len(seeded.list_checkins(VID, DAY, Purpose.REPORT)) == 2


def test_report_dirty_water_opens_a_dirty_ticket(v2: V2Fakes, seeded: Repository) -> None:
    on_point(seeded, "wp-a", "h1")
    run_call(callback_call(seeded, PHONES[0]), ["2"])
    [report] = seeded.list_checkins(VID, DAY, Purpose.REPORT)
    assert report.water is WaterAnswer.YES and report.clean is not None
    ticket = seeded.get_open_ticket(VID, "wp-a", TicketReason.DIRTY)
    assert ticket is not None and ticket.number == 1


def test_report_option_4_plays_status_then_the_menu_again(v2: V2Fakes, seeded: Repository) -> None:
    on_point(seeded, "wp-a", "h1")
    call_id = callback_call(seeded, PHONES[0])
    replies = run_call(call_id, ["4"])
    status_text = plays(replies[-1])[0]
    assert status_text.startswith("Aaj Testgaon mein.")
    root = xml_root(replies[-1])
    assert [el.tag for el in root] == ["Speak", "Gather", "Redirect"]
    assert root[1][0].text == f"{CDN}/report.menu.mp3"
    assert next_turn(replies[-1]) == 2
    assert seeded.list_checkins(VID, DAY, Purpose.REPORT) == []

    turn = next_turn(replies[-1])
    _, xml = vobiz_post("digits", {"call_id": call_id, "turn": str(turn)}, {"Digits": "1"})
    assert plays(xml)[-1] == f"{CDN}/report.number.n1.mp3"


def test_report_status_uses_runtime_tts_when_available(v2: V2Fakes, seeded: Repository) -> None:
    class FakeTts:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def ensure(self, text: str) -> str:
            self.texts.append(text)
            return f"{CDN}/dyn/{len(self.texts)}.mp3"

    tts = FakeTts()
    speech.use_tts(tts)  # type: ignore[arg-type]
    call_id = callback_call(seeded, PHONES[0])
    replies = run_call(call_id, ["4"])
    assert plays(replies[-1])[0] == f"{CDN}/dyn/1.mp3"
    assert tts.texts and tts.texts[0].startswith("Aaj Testgaon mein.")


def test_report_stop_erases_the_household(v2: V2Fakes, seeded: Repository) -> None:
    call_id = callback_call(seeded, PHONES[0])
    replies = run_call(call_id, ["9", "9"])
    assert plays(replies[1]) == [] and xml_root(replies[1]).find("Gather") is not None
    assert plays(replies[-1]) == [f"{CDN}/stop.done.mp3"]
    assert seeded.get_household(VID, "h1") is None
    assert seeded.find_households_by_phone(PHONES[0]) == []
    assert seeded.lookup_phone(PHONES[0]).households == []
    [event] = seeded.list_consent_events(VID)
    assert event.action is ConsentAction.WITHDRAWN and event.household_id == "h1"
    assert event.phone_masked == "+91XXXXXX0001" and event.digits == "9"
    assert seeded.list_checkins(VID, DAY, Purpose.REPORT) == []
    assert seeded.list_open_tickets(VID) == []


def test_report_stop_cancelled_keeps_the_household(v2: V2Fakes, seeded: Repository) -> None:
    replies = run_call(callback_call(seeded, PHONES[0]), ["9", "0"])
    assert plays(replies[-1]) == [f"{CDN}/stop.cancelled.mp3"]
    assert seeded.get_household(VID, "h1") is not None
    assert seeded.list_consent_events(VID) == []


def test_report_invalid_twice_says_bye_and_opens_nothing(v2: V2Fakes, seeded: Repository) -> None:
    replies = run_call(callback_call(seeded, PHONES[0]), ["7", "8"])
    assert plays(replies[-1]) == [f"{CDN}/report.bye.mp3"]
    assert seeded.list_open_tickets(VID) == []


def test_report_note_hands_the_recording_to_the_notes_lambda(
    v2: V2Fakes, seeded: Repository
) -> None:
    call_id = callback_call(seeded, PHONES[0])
    replies = run_call(call_id, ["3"])
    record = xml_root(replies[-1]).find("Record")
    assert record is not None and record.get("maxLength") == "25"
    url = "https://media.vobiz.ai/recordings/rec-1.mp3"
    form = {"RecordUrl": url, "RecordingDuration": "7", "RecordingID": "rec-1"}
    status, _ = vobiz_post("recording", {"call_id": call_id}, form)
    assert status == 200
    assert v2.lambdas.events(function=NOTES_FN) == [
        {"call_id": call_id, "recording_url": url, "recording_id": "rec-1"}
    ]
    vobiz_post("recording", {"call_id": call_id}, form)  # Vobiz retries the callback
    assert len(v2.lambdas.events(function=NOTES_FN)) == 1
    loaded = calls.load_call(seeded, call_id)
    assert loaded is not None and loaded.record.flow.answers.note_recording_url == url

    turn = next_turn(replies[-1])
    _, xml = vobiz_post("digits", {"call_id": call_id, "turn": str(turn)})
    assert plays(xml) == [f"{CDN}/report.note_ack.mp3"]
    assert seeded.list_checkins(VID, DAY, Purpose.REPORT) == []  # the notes Lambda decides


def test_skipped_or_unknown_recordings_are_ignored(v2: V2Fakes, seeded: Repository) -> None:
    call_id = callback_call(seeded, PHONES[0])
    run_call(call_id, ["3"])
    url = "https://media.vobiz.ai/recordings/rec-1.mp3"
    vobiz_post("recording", {"call_id": call_id}, {"RecordUrl": url, "RecordingDuration": "0"})
    vobiz_post("recording", {"call_id": "nope"}, {"RecordUrl": url, "RecordingDuration": "5"})
    vobiz_post("recording", {"call_id": call_id}, {"RecordingDuration": "5"})
    assert v2.lambdas.invocations == []


# --- DAILY -----------------------------------------------------------------------------------


def place_daily(token: str, hid: str = "h1") -> str:
    item = {"village_id": VID, "household_id": hid, "date": DAY.isoformat(), "purpose": "DAILY"}
    out = sfn_tasks.place_call({"task_token": token, "input": item}, LambdaContext())
    return str(out["call_id"])


def test_daily_call_stop_withdraws_and_resumes_the_workflow(
    v2: V2Fakes, seeded: Repository
) -> None:
    call_id = place_daily("tok-stop")
    replies = run_call(call_id, ["9", "9"])
    assert plays(replies[-1]) == [f"{CDN}/stop.done.mp3"]
    assert seeded.get_household(VID, "h1") is None
    [event] = seeded.list_consent_events(VID)
    assert event.action is ConsentAction.WITHDRAWN
    [stored] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert stored.outcome is CallOutcome.UNREACHABLE
    assert v2.sfn.outputs_for("tok-stop")[0]["answered"] is False


def test_daily_no_water_then_bought_stores_the_fallback(v2: V2Fakes, seeded: Repository) -> None:
    on_point(seeded, "wp-a", "h1")
    call_id = place_daily("tok-fb")
    replies = run_call(call_id, ["2", "2", None])  # no water, bought it, skip the note
    assert plays(replies[-1]) == [f"{CDN}/household.bye.mp3"]
    [stored] = seeded.list_checkins(VID, DAY, Purpose.DAILY)
    assert stored.water is WaterAnswer.NO and stored.fallback is Fallback.BOUGHT
    assert stored.water_point_id == "wp-a"
    assert v2.sfn.outputs_for("tok-fb")[0]["answered"] is True


def test_daily_question_names_the_familys_own_source(v2: V2Fakes, seeded: Repository) -> None:
    household = seeded.get_household(VID, "h1")
    assert household is not None
    seeded.put_household(household.model_copy(update={"access": AccessKind.HANDPUMP}))
    call_id = place_daily("t")
    replies = run_call(call_id, [])
    gather = xml_root(replies[0]).find("Gather")
    assert gather is not None and gather[0].text == f"{CDN}/household.q_water_handpump.mp3"


# --- OPERATOR reasons ---------------------------------------------------------------------------


def operator_call(repo: Repository, wpid: str | None = None) -> tuple[str, str]:
    """An open, notified ticket and its pending operator call: (ticket id, call id)."""
    ticket = repo.open_ticket_if_none(
        new_ticket(VID, TicketReason.NO_SUPPLY, MORNING, water_point_id=wpid, number=7)
    )
    assert ticket is not None
    sfn_tasks.notify_operator(
        {"task_token": "fix-1", "input": {"ticket_id": ticket.id}}, LambdaContext()
    )
    pending = calls.find_pending(repo, "op-1", Purpose.OPERATOR)
    assert pending is not None
    return ticket.id, pending.record.call_id


@pytest.mark.parametrize(
    ("key", "blocker", "closing"),
    [
        ("2", BlockerCode.PARTS_NEEDED, "operator.ack_reason"),
        ("3", BlockerCode.NO_POWER, "operator.ack_reason"),
        ("4", BlockerCode.PIPE_BROKEN, "operator.ack_reason"),
        ("5", BlockerCode.NOT_MINE, "operator.ack_not_mine"),
    ],
)
def test_operator_reason_keys_note_the_blocker(
    v2: V2Fakes, seeded: Repository, key: str, blocker: BlockerCode, closing: str
) -> None:
    tid, call_id = operator_call(seeded)
    replies = run_call(call_id, [key])
    assert plays(replies[-1]) == [f"{CDN}/{closing}.mp3"]
    ticket = seeded.get_ticket_by_id(tid)
    assert ticket is not None and ticket.blocker is blocker
    note = ticket.events[-1]
    assert note.kind == "NOTE" and note.actor == "operator:op-1"
    expected: dict[str, Any] = {"note": "operator_reason", "code": blocker.value}
    if blocker is BlockerCode.NOT_MINE:
        expected["not_mine"] = "op-1"
    assert note.detail == expected
    assert ticket.state.value == "ASSIGNED"  # a reason never moves the ticket
    assert v2.sfn.outputs_for("fix-1") == []  # the workflow keeps waiting for a fix


def finish_note(call_id: str, last_reply: str) -> str:
    """The operator ends the spoken note with # (no recording): the closing prompt."""
    _, xml = vobiz_post("digits", {"call_id": call_id, "turn": str(next_turn(last_reply))})
    return xml


def test_key_6_asks_for_the_operators_own_words(v2: V2Fakes, seeded: Repository) -> None:
    tid, call_id = operator_call(seeded)
    replies = run_call(call_id, ["6"])
    assert plays(replies[-1]) == [f"{CDN}/operator.q_note.mp3"]
    assert xml_root(replies[-1]).find("Record") is not None
    assert plays(finish_note(call_id, replies[-1])) == [f"{CDN}/operator.ack_note.mp3"]
    ticket = seeded.get_ticket_by_id(tid)
    assert ticket is not None and ticket.blocker is BlockerCode.OTHER
    assert ticket.state.value == "ASSIGNED"
    assert v2.lambdas.events("panchayat_alert") == []


def test_key_7_sends_the_complaint_to_the_sarpanch(v2: V2Fakes, seeded: Repository) -> None:
    tid, call_id = operator_call(seeded)
    replies = run_call(call_id, ["7"])
    assert plays(replies[-1]) == [f"{CDN}/operator.q_note.mp3"]
    closing = finish_note(call_id, replies[-1])
    assert plays(closing) == [f"{CDN}/operator.ack_panchayat.mp3"]
    ticket = seeded.get_ticket_by_id(tid)
    assert ticket is not None and ticket.blocker is BlockerCode.NEEDS_PANCHAYAT
    assert ticket.state.value == "ESCALATED"
    escalated = ticket.events[-1]
    assert escalated.kind == "ESCALATED" and escalated.actor == "operator:op-1"
    assert escalated.detail == {"to": "SARPANCH", "by": "op-1", "simulated": False}
    [job] = v2.lambdas.events("panchayat_alert", function=OUTBOUND_FN)
    assert job["ticket_id"] == tid and job["delay_s"] == calls.PANCHAYAT_ALERT_DELAY_S
    assert v2.sfn.outputs_for("fix-1") == []  # still waiting for a fix
    feed = seeded.list_activity(MORNING - timedelta(hours=1))
    assert any("sent to the Sarpanch" in e.text_en for e in feed)


def test_the_sarpanch_hears_the_complaint_and_the_operators_words(
    v2: V2Fakes, seeded: Repository
) -> None:
    sarpanch = operator("op-s", phone="+919800000055").model_copy(
        update={"role": OperatorRole.SARPANCH}
    )
    seeded.put_operator(sarpanch)
    tid, call_id = operator_call(seeded)
    replies = run_call(call_id, ["7"])
    finish_note(call_id, replies[-1])
    words = {"note": "operator_voice", "transcript": "मोटर जल गई है, ब्लॉक से नई चाहिए"}
    residents.update_ticket(seeded, tid, lambda t: t, words, "operator:op-1")
    [job] = v2.lambdas.events("panchayat_alert", function=OUTBOUND_FN)
    out = outbound.handler({**job, "delay_s": 0}, LambdaContext())
    assert out["status"] == "pending"
    loaded = calls.load_call(seeded, out["call_id"])
    assert loaded is not None
    flow = loaded.record.flow
    assert flow.purpose is Purpose.ALERT and flow.operator_id == "op-s"
    assert flow.ticket_id == tid and loaded.record.origin == "alert"
    message = flow.message_text_hi or ""
    assert message.startswith("Shikayat kramank 7: paani nahi aaya.")
    assert "मोटर जल गई है" in message
    alert = run_call(out["call_id"], ["1"])
    assert plays(alert[-1]) == [f"{CDN}/alert.bye.mp3"]
    ticket = seeded.get_ticket_by_id(tid)
    assert ticket is not None and ticket.events[-1].detail["note"] == "sarpanch_told"


def test_operator_called_again_on_request_gets_a_new_call(v2: V2Fakes, seeded: Repository) -> None:
    tid, first = operator_call(seeded)
    ticket = seeded.get_ticket_by_id(tid)
    assert ticket is not None
    sfn_tasks.call_operator(seeded, ticket)  # a repeat of the workflow's own call: deduped
    assert calls.find_pending(seeded, "op-1", Purpose.OPERATOR) is not None
    again = {"kind": "operator_call", "ticket_id": tid, "requested_at": "2026-10-08T06:00:00+00:00"}
    outbound.handler(again, LambdaContext())
    loaded = calls.load_call(seeded, f"operator-{tid}-c20261008060000")
    assert loaded is not None and loaded.record.flow.operator_id == "op-1"
    assert loaded.record.call_id != first


def test_without_a_sarpanch_the_secretary_is_called_and_without_either_it_is_logged(
    v2: V2Fakes, seeded: Repository
) -> None:
    tid, call_id = operator_call(seeded)
    replies = run_call(call_id, ["7"])
    finish_note(call_id, replies[-1])
    assert outbound.panchayat_alert(seeded, tid)["status"] == "ignored"
    feed = seeded.list_activity(MORNING - timedelta(hours=1))
    assert any("no Sarpanch or Secretary" in e.text_en for e in feed)
    secretary = operator("op-sec", phone="+919800000066").model_copy(
        update={"role": OperatorRole.PANCHAYAT_SECRETARY}
    )
    seeded.put_operator(secretary)
    out = outbound.panchayat_alert(seeded, tid, requested_at="2026-10-08T05:00:00+00:00")
    assert out["status"] == "pending"
    loaded = calls.load_call(seeded, out["call_id"])
    assert loaded is not None and loaded.record.flow.operator_id == "op-sec"


def test_not_mine_routes_the_next_notice_and_callbacks_to_the_next_person(
    v2: V2Fakes, seeded: Repository
) -> None:
    sarpanch = operator("op-s", phone="+919800000055").model_copy(
        update={"role": OperatorRole.SARPANCH}
    )
    seeded.put_operator(sarpanch)
    tid, call_id = operator_call(seeded)
    run_call(call_id, ["5"])
    ticket = seeded.get_ticket_by_id(tid)
    assert ticket is not None and residents.not_mine(ticket) == ["op-1"]
    routed = residents.route_operator(seeded, VID, None, skip=residents.not_mine(ticket))
    assert routed is not None and routed.id == "op-s"
    # The operator who disowned it no longer gets it on a missed call; the sarpanch does.
    assert outbound.callback(seeded, PHONES[2], 0, "a")["status"] == "ignored"
    out = outbound.callback(seeded, "+919800000055", 0, "b")
    loaded = calls.load_call(seeded, out["call_id"])
    assert loaded is not None and loaded.record.flow.operator_id == "op-s"
    assert loaded.record.flow.ticket_id == tid


def test_operator_fixed_key_still_reports_the_fix(v2: V2Fakes, seeded: Repository) -> None:
    tid, call_id = operator_call(seeded)
    replies = run_call(call_id, ["1"])
    assert plays(replies[-1]) == [f"{CDN}/operator.ack_fixed.mp3"]
    ticket = seeded.get_ticket_by_id(tid)
    assert ticket is not None and ticket.state.value == "OPERATOR_REPORTED_FIXED"
    assert ticket.blocker is None
    assert v2.sfn.outputs_for("fix-1")[0]["fixed"] is True


def test_operator_call_names_the_complaint_and_place(v2: V2Fakes, seeded: Repository) -> None:
    seeded.put_water_point(water_point("wp-a", operator_ids=("op-1",)))
    _, call_id = operator_call(seeded, "wp-a")
    replies = run_call(call_id, [])
    texts = plays(replies[0])
    assert texts[0] == f"{CDN}/operator.greet.mp3"
    assert texts[-1] == "Yeh shikayat kramank saat hai. Jagah: टेस्टगाँव wp-a."


def test_dynamic_audio_failure_never_breaks_the_call(
    v2: V2Fakes, seeded: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenTts:
        def ensure(self, text: str) -> str:
            raise RuntimeError("sarvam down")

    speech.use_tts(BrokenTts())  # type: ignore[arg-type]
    actions = [Play(prompt_key="dyn.report_status", text_hi="Aaj sab theek hai.")]
    assert speech.with_dynamic_audio(actions) == actions
