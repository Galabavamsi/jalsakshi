"""Cedar policy engine: a thin, fail-closed cedarpy wrapper plus typed helpers.

See docs/ARCHITECTURE.md section 7. Policies and schema load once per process (cached).
Any error while evaluating (bad request shape, missing attribute, parse failure) is a deny with
``ENGINE_ERROR_ID``, never an allow: Cedar skips a forbid rule that errors, so trusting its
decision alone would fail open.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from functools import cache
from importlib import resources
from typing import Any, Final

import cedarpy
from pydantic import BaseModel, ConfigDict, Field

from jalsakshi.core.models import Broadcast, Household, OperatorRole, Purpose, Ticket
from jalsakshi.policy.reasons import ALLOW_BY_DEFAULT_ID, ENGINE_ERROR_ID, PolicyId, reason_for

logger = logging.getLogger(__name__)

POLICY_FILE: Final = "jalsakshi.cedar"
SCHEMA_FILE: Final = "jalsakshi.cedarschema"
IST: Final = timezone(timedelta(hours=5, minutes=30), name="IST")

_STALE_HOURS: Final = 1_000_000_000
"""Age used for NaN or infinite inputs, so they always count as stale."""

_ORDER: Final = {pid.value: i for i, pid in enumerate(PolicyId)}

type CedarValue = bool | int | str | Sequence[CedarValue] | Mapping[str, CedarValue]


class Action(StrEnum):
    """Cedar actions guarded by the policies."""

    PLACE_CALL = "PlaceCall"
    CLOSE_VERIFIED = "CloseVerified"
    VIEW_HOUSEHOLD_ANSWERS = "ViewHouseholdAnswers"
    PUBLISH_EVIDENCE = "PublishEvidence"
    APPROVE_BROADCAST = "ApproveBroadcast"
    SEND_BROADCAST = "SendBroadcast"


@dataclass(frozen=True, slots=True)
class Entity:
    """A Cedar entity: its type, id and attributes (must match ``jalsakshi.cedarschema``)."""

    type: str
    id: str
    attrs: Mapping[str, CedarValue] = field(default_factory=dict)

    @property
    def uid(self) -> dict[str, str]:
        """The entity uid in Cedar JSON form."""
        return {"type": self.type, "id": self.id}

    def to_cedar(self) -> dict[str, Any]:
        """The entity in Cedar JSON entities form."""
        return {"uid": self.uid, "attrs": dict(self.attrs), "parents": []}


SYSTEM: Final = Entity("System", "jalsakshi")
"""Principal for actions the backend takes on its own (scheduler, Step Functions)."""

ANY_VILLAGE: Final = Entity("Village", "*")
"""Resource for village-scoped checks whose rule does not depend on which village it is."""


class Decision(BaseModel):
    """Result of a policy check. On a deny, ``policy_ids`` and both reason lists line up."""

    model_config = ConfigDict(frozen=True)

    allowed: bool
    policy_ids: list[str] = Field(default_factory=list)
    reasons_en: list[str] = Field(default_factory=list)
    reasons_hi: list[str] = Field(default_factory=list)

    def denial_payload(self) -> dict[str, object]:
        """The 403 body from ARCHITECTURE.md section 13, built from the first denying rule."""
        if self.allowed:
            raise ValueError("denial_payload() called on an allowed decision")
        return {
            "denied": True,
            "policy_id": self.policy_ids[0],
            "reason_hi": self.reasons_hi[0],
            "reason_en": self.reasons_en[0],
        }


@cache
def read_policy_file(name: str) -> str:
    """Return the text of a file in ``policy/policies`` (cached)."""
    folder = resources.files("jalsakshi.policy") / "policies"
    return (folder / name).read_text(encoding="utf-8")


@cache
def _policy_set() -> cedarpy.PolicySet:
    """Parse the policy file once per process."""
    return cedarpy.PolicySet.from_str(read_policy_file(POLICY_FILE))


@cache
def _schema() -> cedarpy.Schema:
    """Parse the schema file once per process."""
    return cedarpy.Schema.from_str(read_policy_file(SCHEMA_FILE))


def authorize(
    action: Action | str,
    principal: Entity,
    resource: Entity,
    context: Mapping[str, CedarValue] | None = None,
) -> Decision:
    """Check one request against the policies. Fails closed on any error."""
    ctx = dict(context or {})
    facts = {**resource.attrs, **ctx}
    request = {
        "principal": principal.uid,
        "action": {"type": "Action", "id": str(action)},
        "resource": resource.uid,
        "context": ctx,
    }
    try:
        result = cedarpy.is_authorized(
            request, _policy_set(), _entities(principal, resource), schema=_schema()
        )
    except Exception:  # cedarpy raises on bad input or policy files; a crash must never allow.
        logger.exception("policy check raised; denying", extra={"action": str(action)})
        return _deny([ENGINE_ERROR_ID], facts)
    return _to_decision(result, facts, str(action))


def _entities(principal: Entity, resource: Entity) -> list[dict[str, Any]]:
    """Cedar entities for one request (principal and resource, without duplicates)."""
    if principal.uid == resource.uid:
        return [principal.to_cedar()]
    return [principal.to_cedar(), resource.to_cedar()]


def _to_decision(result: cedarpy.AuthzResult, facts: Mapping[str, object], action: str) -> Decision:
    """Map a cedarpy result to a Decision, treating errors and empty denies as engine errors."""
    errors = result.diagnostics.errors
    if errors:
        logger.warning(
            "policy check had errors; denying", extra={"action": action, "errors": errors}
        )
    if result.allowed and not errors:
        return Decision(allowed=True)
    ids = [] if result.allowed else _denying_ids(result.diagnostics)
    if errors or not ids:
        ids.append(ENGINE_ERROR_ID)
    return _deny(ids, facts)


def _denying_ids(diagnostics: cedarpy.Diagnostics) -> list[str]:
    """The ``@id`` of each forbid rule that matched, in policy-file order."""
    annotations = diagnostics.id_annotations_by_reason
    ids = {annotations.get(raw) or raw for raw in diagnostics.reasons}
    ids.discard(ALLOW_BY_DEFAULT_ID)
    return sorted(ids, key=lambda pid: (_ORDER.get(pid, len(_ORDER)), pid))


def _deny(policy_ids: list[str], facts: Mapping[str, object]) -> Decision:
    """Build a deny Decision with reasons in both languages."""
    reasons = [reason_for(pid, facts) for pid in policy_ids]
    return Decision(
        allowed=False,
        policy_ids=policy_ids,
        reasons_en=[r.en for r in reasons],
        reasons_hi=[r.hi for r in reasons],
    )


def ist_hour(at: datetime) -> int:
    """Hour of day (0-23) in IST for a timezone-aware datetime."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("ist_hour() needs a timezone-aware datetime")
    return at.astimezone(IST).hour


def can_place_call(
    household: Household,
    purpose: Purpose,
    hour_ist: int,
    calls_today: int,
    *,
    caller_initiated: bool = False,
    callbacks_today: int = 0,
    test_phone: bool = False,
) -> Decision:
    """May the system call this household now? ``calls_today`` counts this purpose's calls today.

    ``caller_initiated`` marks a call back after the household's own missed call;
    ``callbacks_today`` counts such call-backs to this number today.
    """
    resource = Entity(
        "Household",
        household.id,
        {
            "village_id": household.village_id,
            "consent_given": household.consent_given,
            "consent_status": household.effective_consent.value,
        },
    )
    context = {
        "hour_ist": hour_ist,
        "calls_today": calls_today,
        "purpose": str(purpose),
        "caller_initiated": caller_initiated,
        "callbacks_today": callbacks_today,
        "test_phone": test_phone,
    }
    return authorize(Action.PLACE_CALL, SYSTEM, resource, context)


def can_approve_broadcast(role: OperatorRole, broadcast: Broadcast) -> Decision:
    """May a console user with this role approve this announcement?"""
    principal = Entity("Operator", f"role:{role}", {"role": str(role)})
    return authorize(Action.APPROVE_BROADCAST, principal, _broadcast_entity(broadcast))


def can_send_broadcast(broadcast: Broadcast, sent_last_7_days: int) -> Decision:
    """May this announcement be played to households now?"""
    context = {"sent_last_7_days": sent_last_7_days}
    return authorize(Action.SEND_BROADCAST, SYSTEM, _broadcast_entity(broadcast), context)


def _broadcast_entity(broadcast: Broadcast) -> Entity:
    attrs = {"village_id": broadcast.village_id, "state": broadcast.state.value}
    return Entity("Broadcast", broadcast.id, attrs)


def can_close_verified(ticket: Ticket, quorum: int, verify_yes: int) -> Decision:
    """May this ticket move to CLOSED_VERIFIED, given the verify-call YES count?"""
    resource = Entity("Ticket", ticket.id, {"village_id": ticket.village_id, "quorum": quorum})
    return authorize(Action.CLOSE_VERIFIED, SYSTEM, resource, {"verify_yes": verify_yes})


def can_view_household_answers(role: OperatorRole) -> Decision:
    """May a console user with this role see answers of single households?"""
    principal = Entity("Operator", f"role:{role}", {"role": str(role)})
    return authorize(Action.VIEW_HOUSEHOLD_ANSWERS, principal, ANY_VILLAGE)


def can_publish_evidence(data_age_hours: float) -> Decision:
    """May a Gram Sabha evidence sheet be published from data this old?"""
    context = {"data_age_hours": _whole_hours_up(data_age_hours)}
    return authorize(Action.PUBLISH_EVIDENCE, SYSTEM, ANY_VILLAGE, context)


def _whole_hours_up(hours: float) -> int:
    """Round an age up to whole hours (exact for "> 24"); NaN or infinity counts as stale."""
    if not math.isfinite(hours):
        return _STALE_HOURS
    return math.ceil(hours)
