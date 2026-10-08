"""Gram Sabha brief: agent path, fallbacks, template and summary (scripted model, no network)."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime

import pytest
from agent_fakes import NOW, ScriptedFactory, Slow, ToolCall
from hypothesis import given, settings
from hypothesis import strategies as st

from jalsakshi.agent.brief import (
    BriefInput,
    BriefSummary,
    clean_agent_markdown,
    generate_brief,
    template_brief,
    tickets_payload,
    validate_numbers,
    village_summary_payload,
)
from jalsakshi.agent.evidence import allowed_numbers, identifiers
from jalsakshi.agent.models import MODEL_CHAIN
from jalsakshi.core.models import DayCounts, DayStatus, DayStatusValue, Village

BODY = """# जल साक्ष्य पत्र: Kumhari

## सारांश
राज्य ने हर घर जल का दावा किया है (स्रोत: JJM IMIS Har Ghar Jal report), पर घरों ने 7 में से \
केवल ३ दिन पूरा पानी बताया (43% दिन)।

## घरों की गवाही
- 1 अक्टूबर 2026 से 2026-10-07 तक: 2 दिन पानी नहीं आया, 1 दिन आंशिक, 1 दिन गंदा पानी।

## मरम्मत शिकायतें
- TKT-0001 (पानी नहीं आया) 26.5 घंटे में घरों की पुष्टि से बंद हुई।
- TKT-0002 (गंदा पानी) अभी खुली है।

## ग्राम सभा में चर्चा के बिंदु
- खुली शिकायत पर नल जल मित्र से जवाब लें।"""

INVENTED = BODY.replace("43% दिन", "60% दिन")
TOOLS_THEN = [ToolCall("village_summary"), ToolCall("tickets")]


def _script(text: str) -> list[ToolCall | str]:
    return [*TOOLS_THEN, text]


# --- agent path ---------------------------------------------------------------------------


def test_agent_path_writes_validated_brief(brief_input: BriefInput) -> None:
    factory = ScriptedFactory(_script("यह रहा पत्र:\n```markdown\n" + BODY + "\n```"))
    brief = generate_brief(brief_input, model_factory=factory, now=NOW)

    assert brief.generated_by == "agent"
    assert brief.model_id == MODEL_CHAIN[0]
    assert brief.generated_at == NOW
    assert BODY.splitlines()[0] in brief.markdown_hi
    assert "यह रहा पत्र" not in brief.markdown_hi
    assert "```" not in brief.markdown_hi
    assert "## स्रोत" in brief.markdown_hi  # appended by code, not the model
    assert "सिम्युलेटेड (simulated)" in brief.markdown_hi
    assert brief.markdown_hi.startswith("> **सूचना:**")
    assert brief.numbers == brief_input.summary.numbers()
    assert brief.sources == brief_input.all_sources()


def test_agent_tools_return_only_computed_values(brief_input: BriefInput) -> None:
    factory = ScriptedFactory(_script(BODY))
    generate_brief(brief_input, model_factory=factory, now=NOW)

    model = factory.models[0]
    assert set(model.requests[0]["tools"]) == {"village_summary", "tickets"}
    assert "never as words" in model.requests[0]["system_prompt"]
    summary, tickets = (json.loads(text) for text in model.tool_results())
    assert summary == village_summary_payload(brief_input)
    assert summary["observed_days"]["days"] == 7
    assert summary["supplied_pct"] == 43
    assert tickets == tickets_payload(brief_input)
    assert [t["id"] for t in tickets["tickets"]] == ["TKT-0001", "TKT-0002"]
    assert tickets["tickets"][0]["hours_to_verified_fix"] == 26.5


def test_invented_number_falls_back_to_template(brief_input: BriefInput) -> None:
    factory = ScriptedFactory(_script(INVENTED), _script(INVENTED))
    brief = generate_brief(brief_input, model_factory=factory, now=NOW)

    assert brief.generated_by == "template"
    assert brief.model_id is None
    assert "60%" not in brief.markdown_hi
    assert [mid for mid, _ in factory.calls] == list(MODEL_CHAIN)


def test_invented_number_on_first_model_tries_the_next(brief_input: BriefInput) -> None:
    factory = ScriptedFactory(_script(INVENTED), _script(BODY))
    brief = generate_brief(brief_input, model_factory=factory, now=NOW)
    assert brief.generated_by == "agent"
    assert brief.model_id == MODEL_CHAIN[1]


def test_model_exception_falls_back_to_template(brief_input: BriefInput) -> None:
    factory = ScriptedFactory([RuntimeError("AccessDenied")], [TimeoutError("read timeout")])
    brief = generate_brief(brief_input, model_factory=factory, now=NOW)
    assert brief.generated_by == "template"
    assert brief.markdown_hi == template_brief(brief_input).markdown_hi


def test_tool_crash_mid_run_falls_back(brief_input: BriefInput) -> None:
    factory = ScriptedFactory(
        [ToolCall("village_summary"), RuntimeError("stream broke")], [RuntimeError("down")]
    )
    assert generate_brief(brief_input, model_factory=factory).generated_by == "template"


def test_writing_without_reading_the_tools_is_rejected(brief_input: BriefInput) -> None:
    no_numbers = "# जल साक्ष्य पत्र: Kumhari\n\nसब ठीक है।"
    factory = ScriptedFactory([no_numbers], [no_numbers])
    assert generate_brief(brief_input, model_factory=factory).generated_by == "template"


def test_runaway_tool_loop_hits_turn_limit(brief_input: BriefInput) -> None:
    loop = [ToolCall("village_summary")] * 10
    factory = ScriptedFactory(list(loop), list(loop))
    assert generate_brief(brief_input, model_factory=factory).generated_by == "template"
    assert len(factory.models[0].requests) == 6


def test_spent_deadline_skips_the_models(brief_input: BriefInput) -> None:
    factory = ScriptedFactory(_script(BODY), _script(BODY))
    brief = generate_brief(brief_input, model_factory=factory, deadline_s=0)
    assert brief.generated_by == "template"
    assert all(not model.requests for model in factory.models)


def test_slow_model_is_cancelled_at_the_deadline(brief_input: BriefInput) -> None:
    factory = ScriptedFactory([*TOOLS_THEN, Slow(0.5, BODY)], _script(BODY))
    started = time.monotonic()
    brief = generate_brief(brief_input, model_factory=factory, deadline_s=0.2)
    assert brief.generated_by == "template"
    assert time.monotonic() - started < 2
    assert not factory.models[1].requests  # the budget was spent, so no second model call


def test_use_agent_false_never_calls_a_model(brief_input: BriefInput) -> None:
    factory = ScriptedFactory()
    brief = generate_brief(brief_input, use_agent=False, model_factory=factory, now=NOW)
    assert brief.generated_by == "template"
    assert factory.calls == []


def test_clean_agent_markdown_drops_preface_fences_and_sources() -> None:
    raw = "ठीक है।\n```\n# शीर्षक\nपाठ\n## स्रोत\n- मॉडल का स्रोत\n```"
    assert clean_agent_markdown(raw) == "# शीर्षक\nपाठ"
    assert clean_agent_markdown("कोई शीर्षक नहीं") == ""


# --- template -----------------------------------------------------------------------------


def test_template_is_deterministic(brief_input: BriefInput) -> None:
    first = template_brief(brief_input, now=NOW)
    second = template_brief(brief_input.model_copy(deep=True), now=NOW)
    assert first == second
    later = template_brief(brief_input, now=datetime(2027, 1, 1, tzinfo=UTC))
    assert later.markdown_hi == first.markdown_hi


def test_template_passes_its_own_validator(brief_input: BriefInput) -> None:
    brief = template_brief(brief_input, now=NOW)
    md = brief.markdown_hi
    assert validate_numbers(md, allowed_numbers(brief_input), ignore=identifiers(brief_input))
    for expected in (
        "# जल साक्ष्य पत्र: Kumhari",
        "1 अक्टूबर 2026 से 7 अक्टूबर 2026 तक",
        "`TKT-0001`",
        "`TKT-0002`",
        "26.5 घंटे",
        "(43% दिन)",
        "सिम्युलेटेड (simulated)",
        "दैनिक (daily)",
        "JJM IMIS Har Ghar Jal report",
    ):
        assert expected in md


def test_template_with_no_data() -> None:
    inp = BriefInput(
        village=Village(id="v2", name="Achhoti", block="Durg", district="Durg"),
        period_from=date(2026, 10, 1),
        period_to=date(2026, 10, 7),
        summary=BriefSummary(
            days=0,
            supplied=0,
            no_supply=0,
            partial=0,
            dirty=0,
            unverified=0,
            tickets_opened=0,
            tickets_closed_verified=0,
        ),
    )
    brief = template_brief(inp, now=NOW)
    assert brief.numbers["supplied_pct"] is None
    assert "कोई जानकारी नहीं मिली" in brief.markdown_hi
    assert "> **सूचना:**" not in brief.markdown_hi
    assert validate_numbers(brief.markdown_hi, allowed_numbers(inp), ignore=identifiers(inp))


def test_brief_json_matches_api_contract(brief_input: BriefInput) -> None:
    payload = template_brief(brief_input, now=NOW).model_dump(mode="json")
    assert {"markdown_hi", "numbers", "generated_by", "sources", "generated_at"} <= set(payload)
    assert payload["generated_by"] == "template"


counts = st.integers(min_value=0, max_value=400)


@settings(max_examples=60, deadline=None)
@given(
    days=counts,
    supplied=counts,
    no_supply=counts,
    partial=counts,
    dirty=counts,
    unverified=counts,
    opened=counts,
    closed=counts,
    median=st.none() | st.floats(min_value=0, max_value=5000, allow_nan=False),
)
def test_template_always_validates(
    days: int,
    supplied: int,
    no_supply: int,
    partial: int,
    dirty: int,
    unverified: int,
    opened: int,
    closed: int,
    median: float | None,
) -> None:
    inp = BriefInput(
        village=Village(id="v3", name="Gram 7", block="Bemetara", district="Bemetara"),
        period_from=date(2026, 9, 1),
        period_to=date(2026, 9, 30),
        summary=BriefSummary(
            days=days,
            supplied=supplied,
            no_supply=no_supply,
            partial=partial,
            dirty=dirty,
            unverified=unverified,
            tickets_opened=opened,
            tickets_closed_verified=closed,
            median_hours_to_verified_fix=median,
        ),
    )
    md = template_brief(inp, now=NOW).markdown_hi
    assert validate_numbers(md, allowed_numbers(inp), ignore=identifiers(inp))


# --- summary from stored records ----------------------------------------------------------


def _day(day: int, status: DayStatusValue) -> DayStatus:
    return DayStatus(
        village_id="v-kumhari",
        date=date(2026, 10, day),
        status=status,
        counts=DayCounts(),
        rule_version="r1",
        computed_at=NOW,
    )


def test_summary_from_records(brief_input: BriefInput) -> None:
    S = DayStatusValue
    statuses = [S.SUPPLIED, S.NO_SUPPLY, S.NO_SUPPLY, S.PARTIAL, S.DIRTY, S.SUPPLIED, S.SUPPLIED]
    days = [_day(i + 1, s) for i, s in enumerate(statuses)] + [_day(9, S.UNVERIFIED)]
    summary = BriefSummary.from_records(
        days, brief_input.tickets, date(2026, 10, 1), date(2026, 10, 7)
    )
    assert summary == brief_input.summary
    assert summary.supplied_pct == 43


def test_summary_rounds_hours_and_rejects_bad_period(brief_input: BriefInput) -> None:
    data = {**brief_input.summary.model_dump(), "median_hours_to_verified_fix": 12.345}
    assert BriefSummary(**data).median_hours_to_verified_fix == 12.3
    with pytest.raises(ValueError, match="period_from"):
        BriefInput(
            village=brief_input.village,
            period_from=date(2026, 10, 8),
            period_to=date(2026, 10, 1),
            summary=brief_input.summary,
        )
