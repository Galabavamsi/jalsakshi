"""Each policy denies in its case and allows otherwise; the engine fails closed on errors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from jalsakshi.core.models import (
    Consent,
    Household,
    OperatorRole,
    Purpose,
    Ticket,
    TicketReason,
)
from jalsakshi.policy import engine
from jalsakshi.policy.engine import (
    SYSTEM,
    Action,
    Decision,
    Entity,
    authorize,
    can_close_verified,
    can_place_call,
    can_publish_evidence,
    can_view_household_answers,
    ist_hour,
)
from jalsakshi.policy.reasons import ENGINE_ERROR_ID, REASONS, PolicyId

NOW = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
DEPT_ROLES = {OperatorRole.PHED_AE_SIM, OperatorRole.PHED_EE_SIM}


def make_household(*, consent: bool = True) -> Household:
    """A household in village v1, with or without consent on file."""
    return Household(
        id="h1",
        village_id="v1",
        phone_e164="+919876543210",
        consent=Consent(given_at=NOW, channel="voice") if consent else None,
    )


def make_ticket() -> Ticket:
    """An open NO_SUPPLY ticket in village v1."""
    return Ticket(
        id="t1", village_id="v1", reason=TicketReason.NO_SUPPLY, opened_at=NOW, updated_at=NOW
    )


def assert_allowed(decision: Decision) -> None:
    assert decision.allowed, decision
    assert decision.policy_ids == []
    assert decision.reasons_en == []
    assert decision.reasons_hi == []


def assert_denied_by(decision: Decision, *policy_ids: str) -> None:
    assert not decision.allowed
    assert decision.policy_ids == list(policy_ids)
    assert len(decision.reasons_en) == len(policy_ids)
    assert len(decision.reasons_hi) == len(policy_ids)
    assert all(r.strip() for r in decision.reasons_en + decision.reasons_hi)


def ok_call(
    *,
    household: Household | None = None,
    purpose: Purpose = Purpose.DAILY,
    hour_ist: int = 10,
    calls_today: int = 0,
) -> Decision:
    """can_place_call with values that pass every rule, unless overridden."""
    return can_place_call(household or make_household(), purpose, hour_ist, calls_today)


# consent-required


def test_call_allowed_with_consent_in_hours_first_call() -> None:
    assert_allowed(ok_call())


def test_consent_required_denies_without_consent() -> None:
    decision = ok_call(household=make_household(consent=False))
    assert_denied_by(decision, PolicyId.CONSENT_REQUIRED)
    assert decision.reasons_en == [REASONS[PolicyId.CONSENT_REQUIRED].en]
    assert decision.reasons_hi == [REASONS[PolicyId.CONSENT_REQUIRED].hi]


# calling-hours


@pytest.mark.parametrize("hour", range(-1, 25))
def test_calling_hours_window(hour: int) -> None:
    decision = ok_call(hour_ist=hour)
    if 9 <= hour < 21:
        assert_allowed(decision)
    else:
        assert_denied_by(decision, PolicyId.CALLING_HOURS)


# one-call-per-day


@pytest.mark.parametrize("calls_today", [1, 2, 7])
def test_one_call_per_day_denies_second_daily_call(calls_today: int) -> None:
    assert_denied_by(ok_call(calls_today=calls_today), PolicyId.ONE_CALL_PER_DAY)


@pytest.mark.parametrize("purpose", [Purpose.VERIFY, Purpose.OPERATOR])
def test_one_call_per_day_only_limits_daily_calls(purpose: Purpose) -> None:
    assert_allowed(ok_call(purpose=purpose, calls_today=3))


def test_all_call_denials_are_reported_in_policy_order() -> None:
    decision = ok_call(household=make_household(consent=False), hour_ist=22, calls_today=1)
    assert_denied_by(
        decision,
        PolicyId.CONSENT_REQUIRED,
        PolicyId.CALLING_HOURS,
        PolicyId.ONE_CALL_PER_DAY,
    )


@given(
    consent=st.booleans(),
    purpose=st.sampled_from(Purpose),
    hour=st.integers(min_value=-2, max_value=26),
    calls=st.integers(min_value=0, max_value=5),
)
def test_place_call_matches_the_written_rules(
    consent: bool, purpose: Purpose, hour: int, calls: int
) -> None:
    decision = can_place_call(make_household(consent=consent), purpose, hour, calls)
    expected: list[str] = []
    if not consent:
        expected.append(PolicyId.CONSENT_REQUIRED)
    if not 9 <= hour < 21:
        expected.append(PolicyId.CALLING_HOURS)
    if purpose is Purpose.DAILY and calls >= 1:
        expected.append(PolicyId.ONE_CALL_PER_DAY)
    assert decision.allowed is (not expected)
    assert decision.policy_ids == expected


# verify-needs-quorum


@pytest.mark.parametrize(("quorum", "verify_yes"), [(2, 2), (2, 3), (1, 1), (3, 5)])
def test_verify_needs_quorum_allows_when_quorum_met(quorum: int, verify_yes: int) -> None:
    assert_allowed(can_close_verified(make_ticket(), quorum, verify_yes))


@pytest.mark.parametrize(("quorum", "verify_yes"), [(2, 0), (2, 1), (3, 2)])
def test_verify_needs_quorum_denies_below_quorum(quorum: int, verify_yes: int) -> None:
    decision = can_close_verified(make_ticket(), quorum, verify_yes)
    assert_denied_by(decision, PolicyId.VERIFY_NEEDS_QUORUM)
    assert f"Only {verify_yes} of the {quorum}" in decision.reasons_en[0]
    assert str(quorum) in decision.reasons_hi[0]
    assert str(verify_yes) in decision.reasons_hi[0]


# no-household-view-for-dept


@pytest.mark.parametrize("role", list(OperatorRole))
def test_household_answers_hidden_from_department_only(role: OperatorRole) -> None:
    decision = can_view_household_answers(role)
    if role in DEPT_ROLES:
        assert_denied_by(decision, PolicyId.NO_HOUSEHOLD_VIEW_FOR_DEPT)
    else:
        assert_allowed(decision)


# stale-data


@pytest.mark.parametrize("age", [0.0, 0.5, 12, 23.99, 24.0, -1.0])
def test_stale_data_allows_fresh_data(age: float) -> None:
    assert_allowed(can_publish_evidence(age))


@pytest.mark.parametrize("age", [24.0001, 24.5, 25, 1000.0, float("nan"), float("inf")])
def test_stale_data_denies_old_or_unknown_age(age: float) -> None:
    assert_denied_by(can_publish_evidence(age), PolicyId.STALE_DATA)


# Generic authorize and fail-closed behaviour


def test_authorize_accepts_explicit_entities() -> None:
    principal = Entity("Operator", "op-1", {"role": OperatorRole.SARPANCH.value})
    resource = Entity("Ticket", "t9", {"village_id": "v1", "quorum": 2})
    decision = authorize(Action.CLOSE_VERIFIED, principal, resource, {"verify_yes": 2})
    assert_allowed(decision)


def test_missing_context_attribute_fails_closed() -> None:
    resource = Entity("Household", "h1", {"village_id": "v1", "consent_given": True})
    decision = authorize(Action.PLACE_CALL, SYSTEM, resource, {"hour_ist": 10, "purpose": "DAILY"})
    assert_denied_by(decision, ENGINE_ERROR_ID)


def test_wrong_entity_shape_fails_closed() -> None:
    resource = Entity("Household", "h1", {"consent_given": True})
    context = {"hour_ist": 10, "calls_today": 0, "purpose": "DAILY"}
    assert_denied_by(authorize(Action.PLACE_CALL, SYSTEM, resource, context), ENGINE_ERROR_ID)


def test_unknown_action_fails_closed() -> None:
    assert_denied_by(authorize("DeleteVillage", SYSTEM, engine.ANY_VILLAGE), ENGINE_ERROR_ID)


def test_unserialisable_context_fails_closed() -> None:
    context = {"verify_yes": object()}
    resource = Entity("Ticket", "t1", {"village_id": "v1", "quorum": 2})
    decision = authorize(Action.CLOSE_VERIFIED, SYSTEM, resource, context)  # type: ignore[dict-item]
    assert_denied_by(decision, ENGINE_ERROR_ID)


def test_evaluation_errors_never_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without schema checks Cedar skips a forbid that errors and says Allow; we must deny."""
    monkeypatch.setattr(engine, "_schema", lambda: None)
    resource = Entity("Household", "h1", {"village_id": "v1", "consent_given": True})
    decision = authorize(Action.PLACE_CALL, SYSTEM, resource, {"hour_ist": 10, "purpose": "DAILY"})
    assert_denied_by(decision, ENGINE_ERROR_ID)


def test_cedar_crash_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("engine down")

    monkeypatch.setattr(engine.cedarpy, "is_authorized", boom)
    assert_denied_by(ok_call(), ENGINE_ERROR_ID)


def test_broken_policy_file_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "read_policy_file", lambda _name: "permit (principal")
    engine._policy_set.cache_clear()
    try:
        assert_denied_by(ok_call(), ENGINE_ERROR_ID)
    finally:
        engine._policy_set.cache_clear()


def test_policies_are_parsed_once() -> None:
    engine._policy_set.cache_clear()
    engine._schema.cache_clear()
    ok_call()
    ok_call(hour_ist=11)
    can_view_household_answers(OperatorRole.SARPANCH)
    assert engine._policy_set.cache_info().misses == 1
    assert engine._schema.cache_info().misses == 1


# Decision


def test_denial_payload_matches_api_contract() -> None:
    decision = ok_call(household=make_household(consent=False), hour_ist=23)
    assert decision.denial_payload() == {
        "denied": True,
        "policy_id": PolicyId.CONSENT_REQUIRED,
        "reason_hi": REASONS[PolicyId.CONSENT_REQUIRED].hi,
        "reason_en": REASONS[PolicyId.CONSENT_REQUIRED].en,
    }


def test_denial_payload_refuses_allowed_decision() -> None:
    with pytest.raises(ValueError, match="allowed"):
        ok_call().denial_payload()


def test_decision_is_frozen_and_serialisable() -> None:
    decision = can_publish_evidence(30)
    with pytest.raises(ValidationError):
        decision.allowed = True  # type: ignore[misc]
    assert Decision.model_validate_json(decision.model_dump_json()) == decision


# ist_hour


@pytest.mark.parametrize(
    ("at", "hour"),
    [
        (datetime(2026, 10, 9, 3, 29, tzinfo=UTC), 8),
        (datetime(2026, 10, 9, 3, 30, tzinfo=UTC), 9),
        (datetime(2026, 10, 9, 15, 29, tzinfo=UTC), 20),
        (datetime(2026, 10, 9, 15, 30, tzinfo=UTC), 21),
        (datetime(2026, 10, 9, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))), 10),
    ],
)
def test_ist_hour_converts_to_india_time(at: datetime, hour: int) -> None:
    assert ist_hour(at) == hour


def test_ist_hour_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ist_hour(datetime(2026, 10, 9, 10, 0))
