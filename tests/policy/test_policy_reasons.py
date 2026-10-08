"""Every denial has a plain reason in English and Hindi."""

from __future__ import annotations

import re

import pytest

from jalsakshi.policy.reasons import DETAILED, ENGINE_ERROR_ID, REASONS, PolicyId, reason_for

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
ALL_IDS = [*(pid.value for pid in PolicyId), ENGINE_ERROR_ID]


@pytest.mark.parametrize("policy_id", ALL_IDS)
def test_reason_is_non_empty_in_both_languages(policy_id: str) -> None:
    reason = REASONS[policy_id]
    assert reason.en.strip()
    assert reason.hi.strip()
    assert reason.en.isascii()
    assert DEVANAGARI.search(reason.hi)


@pytest.mark.parametrize("policy_id", ALL_IDS)
def test_generic_reasons_have_no_placeholders(policy_id: str) -> None:
    reason = REASONS[policy_id]
    assert "{" not in reason.en
    assert "{" not in reason.hi


def test_quorum_reason_fills_numbers() -> None:
    reason = reason_for(PolicyId.VERIFY_NEEDS_QUORUM, {"verify_yes": 1, "quorum": 3})
    assert "1" in reason.en and "3" in reason.en
    assert "1" in reason.hi and "3" in reason.hi
    assert "{" not in reason.en + reason.hi


def test_detailed_reason_falls_back_when_facts_missing() -> None:
    generic = REASONS[PolicyId.VERIFY_NEEDS_QUORUM]
    assert reason_for(PolicyId.VERIFY_NEEDS_QUORUM) == generic
    assert reason_for(PolicyId.VERIFY_NEEDS_QUORUM, {"verify_yes": 1}) == generic


def test_detailed_templates_have_a_generic_twin() -> None:
    assert set(DETAILED) <= set(REASONS)


def test_unknown_policy_id_still_gives_both_languages() -> None:
    reason = reason_for("brand-new-rule")
    assert "brand-new-rule" in reason.en
    assert "brand-new-rule" in reason.hi
    assert DEVANAGARI.search(reason.hi)
