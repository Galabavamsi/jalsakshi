"""Cedar rules added in v2: registration calls, withdrawal, call-backs, announcements (§15)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jalsakshi.core.models import (
    Broadcast,
    BroadcastKind,
    BroadcastState,
    ConsentStatus,
    Household,
    OperatorRole,
    Purpose,
)
from jalsakshi.policy import PolicyId, can_approve_broadcast, can_place_call, can_send_broadcast

NOW = datetime(2026, 10, 9, 6, 0, tzinfo=UTC)


def household(status: ConsentStatus) -> Household:
    return Household(id="h1", village_id="v1", phone_e164="+919000000001", consent_status=status)


def announcement(state: BroadcastState) -> Broadcast:
    return Broadcast(
        id="b1",
        village_id="v1",
        kind=BroadcastKind.BOIL_WATER,
        text_hi="Paani ubaal kar piyein.",
        state=state,
        created_by="console:sec",
        created_at=NOW,
    )


def test_registration_call_needs_no_prior_consent() -> None:
    decision = can_place_call(household(ConsentStatus.NONE), Purpose.REGISTER, 11, 0)
    assert decision.allowed


def test_only_one_unasked_registration_call_a_day() -> None:
    decision = can_place_call(household(ConsentStatus.NONE), Purpose.REGISTER, 11, 1)
    assert decision.policy_ids == [PolicyId.ONE_CALL_PER_DAY]


@pytest.mark.parametrize("status", [ConsentStatus.DECLINED, ConsentStatus.WITHDRAWN])
@pytest.mark.parametrize("purpose", [Purpose.REGISTER, Purpose.DAILY, Purpose.BROADCAST])
def test_no_calls_after_decline_or_withdrawal(status: ConsentStatus, purpose: Purpose) -> None:
    decision = can_place_call(household(status), purpose, 11, 0)
    assert not decision.allowed
    assert PolicyId.NO_CALLS_AFTER_WITHDRAWAL in decision.policy_ids


def test_a_withdrawn_family_can_ask_to_register_again_with_a_missed_call() -> None:
    decision = can_place_call(
        household(ConsentStatus.WITHDRAWN), Purpose.REGISTER, 11, 3, caller_initiated=True
    )
    assert decision.allowed


def test_callbacks_are_capped_per_day() -> None:
    ok = can_place_call(
        household(ConsentStatus.GRANTED),
        Purpose.REPORT,
        11,
        0,
        caller_initiated=True,
        callbacks_today=4,
    )
    capped = can_place_call(
        household(ConsentStatus.GRANTED),
        Purpose.REPORT,
        11,
        0,
        caller_initiated=True,
        callbacks_today=5,
    )
    assert ok.allowed
    assert capped.policy_ids == [PolicyId.CALLBACK_LIMIT]


def test_callbacks_a_family_asked_for_may_happen_at_night() -> None:
    decision = can_place_call(
        household(ConsentStatus.GRANTED), Purpose.REPORT, 22, 0, caller_initiated=True
    )
    assert decision.allowed


def test_legacy_households_with_consent_object_count_as_granted() -> None:
    legacy = Household(id="h1", village_id="v1", phone_e164="+919000000001")
    assert not can_place_call(legacy, Purpose.DAILY, 11, 0).allowed


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (OperatorRole.SARPANCH, True),
        (OperatorRole.PANCHAYAT_SECRETARY, False),
        (OperatorRole.NAL_JAL_MITRA, False),
    ],
)
def test_only_the_sarpanch_approves_announcements(role: OperatorRole, allowed: bool) -> None:
    decision = can_approve_broadcast(role, announcement(BroadcastState.DRAFT))
    assert decision.allowed is allowed
    if not allowed:
        assert decision.policy_ids == [PolicyId.BROADCAST_NEEDS_SARPANCH]


def test_announcements_need_approval_and_a_weekly_limit() -> None:
    assert can_send_broadcast(announcement(BroadcastState.APPROVED), 1).allowed
    draft = can_send_broadcast(announcement(BroadcastState.DRAFT), 0)
    assert draft.policy_ids == [PolicyId.BROADCAST_NOT_APPROVED]
    limited = can_send_broadcast(announcement(BroadcastState.APPROVED), 2)
    assert limited.policy_ids == [PolicyId.BROADCAST_WEEKLY_LIMIT]
