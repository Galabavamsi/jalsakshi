"""AI advice on a complaint: de-identified facts, fixed rules, the Jev client and the template."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from jalsakshi.agent import overview
from jalsakshi.agent.models import accepts_temperature, inference_config
from jalsakshi.agent.overview import (
    JEV_URL,
    OPENAI_URL,
    ComplaintFacts,
    NextStep,
    facts_for,
    suggest,
    suggest_rules,
    template_overview,
)
from jalsakshi.agent.reader import ReaderError
from jalsakshi.core.models import BlockerCode, Ticket, TicketEvent, TicketReason, TicketState

NOW = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)


def ticket(
    *events: TicketEvent, hours: int = 30, state: TicketState = TicketState.ASSIGNED
) -> Ticket:
    return Ticket(
        id="t1",
        village_id="v1",
        reason=TicketReason.NO_SUPPLY,
        state=state,
        opened_at=NOW - timedelta(hours=hours),
        updated_at=NOW,
        number=7,
        reporters=["hh-a", "hh-b"],
        events=list(events),
    )


def event(kind: str, hours_ago: float, actor: str = "system", **detail: Any) -> TicketEvent:
    return TicketEvent(at=NOW - timedelta(hours=hours_ago), actor=actor, kind=kind, detail=detail)


def facts(**update: Any) -> ComplaintFacts:
    base = ComplaintFacts(
        number=7,
        problem="no water",
        status="pump operator told",
        hours_open=10,
        families_reporting=2,
        operator_called=1,
        hours_since_operator_contact=2,
    )
    return base.model_copy(update=update)


def test_facts_carry_no_names_numbers_or_families_words() -> None:
    t = ticket(
        event("NOTIFIED", 20),
        event("NOTE", 5, "operator:op-1", note="operator_reason", code="NEEDS_PANCHAYAT"),
        event(
            "NOTE",
            4,
            "operator:op-1",
            note="operator_voice",
            transcript="मोटर जल गई, 9876543210 पर ठेकेदार",
            summary_en="Motor burnt; call contractor at 9876543210",
        ),
        event("NOTE", 3, "resident:voice-note", note="voice_note", transcript="Ramesh ka ghar"),
    )
    f = facts_for(t, NOW)
    dumped = json.dumps(f.model_dump(mode="json"), ensure_ascii=False)
    assert "9876543210" not in dumped and "Ramesh" not in dumped and "मोटर" not in dumped
    assert "hh-a" not in dumped
    assert f.operator_said == "Motor burnt; call contractor at …"
    assert f.operator_reasons == ["cannot fix it alone, needs the Panchayat"]
    assert (f.hours_open, f.families_reporting, f.operator_called) == (30, 2, 1)
    assert f.hours_since_operator_contact == 4


@pytest.mark.parametrize(
    ("update", "step"),
    [
        ({}, NextStep.WAIT_FOR_REPAIR),
        ({"operator_called": 0}, NextStep.CALL_OPERATOR_AGAIN),
        ({"hours_since_operator_contact": 30}, NextStep.CALL_OPERATOR_AGAIN),
        (
            {"operator_reasons": ["cannot fix it alone, needs the Panchayat"]},
            NextStep.SEND_TO_SARPANCH,
        ),
        ({"operator_reasons": ["parts needed"], "hours_open": 50}, NextStep.SEND_TO_SARPANCH),
        (
            {"operator_said_fixed": True, "families_said_still_broken": 1},
            NextStep.CALL_OPERATOR_AGAIN,
        ),
        ({"hours_open": 80}, NextStep.SEND_TO_SARPANCH),
        ({"hours_open": 80, "sent_to_sarpanch": True}, NextStep.RAISE_WITH_BLOCK_OFFICE),
    ],
)
def test_fixed_rules(update: dict[str, Any], step: NextStep) -> None:
    got = suggest_rules(facts(**update))
    assert got.step is step and got.source == "rules" and got.reasons
    assert got.confidence is None  # rules never pretend to a probability


def jev(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_jev_choice_and_urgency_are_read_and_nothing_personal_is_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "next_step": {
                        "type": "choice",
                        "choice": "SEND_TO_SARPANCH",
                        "probabilities": {"SEND_TO_SARPANCH": 0.82, "WAIT_FOR_REPAIR": 0.18},
                        "confidence": 0.77,
                    },
                    "urgent": {"type": "noul", "noul": 0.91},
                },
                "usage": {"input_tokens": 300, "output_tokens": 20},
            },
        )

    got = suggest(facts(hours_open=60), jev_key="k-test", http=jev(handler))
    assert got.step is NextStep.SEND_TO_SARPANCH and got.source == "jev-1.13.0"
    assert (got.confidence, got.urgent) == (0.77, 0.91)
    assert got.label == "Send it to the Sarpanch"
    [request] = seen
    assert str(request.url) == JEV_URL and request.headers["Authorization"] == "Bearer k-test"
    body = json.loads(request.content)
    assert body["model"] == "jev-1.13.0"  # pinned, never an alias
    assert set(body["questions"]["next_step"]["criteria"]) == {s.value for s in NextStep}
    assert body["state"]["hours_open"] == 60


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": "bad key"}),
        httpx.Response(200, json={"answers": {"next_step": {"choice": "PRAY"}}}),
        httpx.Response(200, json={"nothing": True}),
    ],
)
def test_any_jev_failure_falls_back_to_the_rules(response: httpx.Response) -> None:
    got = suggest(facts(operator_called=0), jev_key="k", http=jev(lambda r: response))
    assert got.source == "rules" and got.step is NextStep.CALL_OPERATOR_AGAIN


def test_jev_is_asked_once_the_next_model_is_the_retry() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(529)

    got = suggest(facts(), jev_key="k", http=jev(handler))
    assert got.source == "rules" and seen == [JEV_URL]
    assert got.reasons[-1] == "the Jev decision model did not answer"


def test_no_key_means_rules_without_any_request() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call a decision model without a key")

    assert suggest(facts(), jev_key=None, openai_key=None, http=jev(boom)).source == "rules"


JEV_UNSURE = {
    "model": "jev-1.13.0",
    "answers": {
        "next_step": {
            "type": "choice",
            "choice": "WAIT_FOR_REPAIR",
            "probabilities": {"WAIT_FOR_REPAIR": 0.35, "CALL_OPERATOR_AGAIN": 0.33},
            "confidence": 0.13,
        }
    },
}


def openai_answer(choice: str, confidence: float) -> dict[str, Any]:
    return {
        "model": "gpt-6-luna",
        "answers": [
            {
                "type": "choice",
                "name": "next_step",
                "choice": choice,
                "probabilities": [
                    {"value": choice, "probability": 0.9},
                    {"value": "WAIT_FOR_REPAIR", "probability": 0.1},
                ],
                "confidence": confidence,
            },
            {"type": "predicate", "name": "urgent", "probability": 0.84},
        ],
    }


def both(openai: httpx.Response, seen: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == JEV_URL:
            return httpx.Response(200, json=JEV_UNSURE)
        return openai

    return jev(handler)


def test_openai_decides_when_jev_is_unsure_and_sends_nothing_personal() -> None:
    seen: list[httpx.Request] = []
    http = both(httpx.Response(200, json=openai_answer("SEND_TO_SARPANCH", 0.77)), seen)
    got = suggest(
        facts(operator_said="Ramesh says the motor burnt"), jev_key="j", openai_key="o", http=http
    )
    assert got.step is NextStep.SEND_TO_SARPANCH and got.source == "gpt-6-luna"
    assert (got.confidence, got.urgent) == (0.77, 0.84)
    assert got.probabilities == {"SEND_TO_SARPANCH": 0.9, "WAIT_FOR_REPAIR": 0.1}
    assert got.reasons == ["the Jev decision model was unsure (13%)"]
    jev_call, openai_call = seen
    assert str(openai_call.url) == OPENAI_URL
    assert openai_call.headers["Authorization"] == "Bearer o"
    body = json.loads(openai_call.content)
    assert body["model"] == "gpt-6-luna"
    assert [q["type"] for q in body["questions"]] == ["choice", "predicate"]
    assert {c["value"] for c in body["questions"][0]["choices"]} == {s.value for s in NextStep}
    for call in (jev_call, openai_call):
        assert "Ramesh" not in call.content.decode()  # only codes and counts leave AWS


@pytest.mark.parametrize(
    ("openai", "reason"),
    [
        (httpx.Response(200, json=openai_answer("CALL_OPERATOR_AGAIN", 0.2)), "was unsure (20%)"),
        (httpx.Response(500), "did not answer"),
        (
            httpx.Response(200, json={"answers": [{"type": "refusal", "name": "next_step"}]}),
            "did not answer",
        ),
    ],
)
def test_when_neither_model_is_sure_the_rules_decide_and_say_why(
    openai: httpx.Response, reason: str
) -> None:
    got = suggest(facts(operator_called=0), jev_key="j", openai_key="o", http=both(openai, []))
    assert got.source == "rules" and got.step is NextStep.CALL_OPERATOR_AGAIN
    assert got.reasons[1:] == [
        "the Jev decision model was unsure (13%)",
        f"the OpenAI decision model {reason}",
    ]


def test_overview_text_falls_back_to_the_template(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(prompt: str, **_: Any) -> tuple[str, str]:
        raise ReaderError("down")

    monkeypatch.setattr(overview, "converse_text", fail)
    text, source = overview.write_overview(facts(operator_reasons=["parts needed"]), None)
    assert source == "template" and text == template_overview(
        facts(operator_reasons=["parts needed"])
    )
    assert text.startswith("Complaint #7: 2 families reported no water, open for 10 hours")
    assert "The pump operator said: parts needed." in text


def test_overview_text_from_a_model_is_tidied(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def model(prompt: str, **_: Any) -> tuple[str, str]:
        seen.append(prompt)
        return "  Two families have had\n no water for 10 hours.  ", "test-model"

    monkeypatch.setattr(overview, "converse_text", model)
    text, source = overview.write_overview(facts(), None)
    assert (text, source) == ("Two families have had no water for 10 hours.", "test-model")
    assert "Do not invent anything" in seen[0]


def test_blocker_codes_all_have_plain_words() -> None:
    assert set(overview.BLOCKER_EN) == set(BlockerCode)


@pytest.mark.parametrize(
    ("model_id", "accepts"),
    [
        ("in.anthropic.claude-haiku-4-5-20251001-v1:0", True),
        ("global.amazon.nova-2-lite-v1:0", True),
        ("global.anthropic.claude-haiku-5-5", False),
        ("global.anthropic.claude-sonnet-5-5", False),
    ],
)
def test_temperature_only_where_the_model_accepts_it(model_id: str, accepts: bool) -> None:
    assert accepts_temperature(model_id) is accepts
    assert ("temperature" in inference_config(model_id, 100)) is accepts


def test_an_unsure_jev_answer_gives_way_to_the_rules() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        answer = {
            "type": "choice",
            "choice": "WAIT_FOR_REPAIR",
            "probabilities": {"WAIT_FOR_REPAIR": 0.35, "CALL_OPERATOR_AGAIN": 0.33},
            "confidence": 0.13,
        }
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {"next_step": answer}})

    got = suggest(facts(operator_called=0), jev_key="k", http=jev(handler))
    assert got.source == "rules" and got.step is NextStep.CALL_OPERATOR_AGAIN
    assert got.reasons[-1] == "the Jev decision model was unsure (13%)"
