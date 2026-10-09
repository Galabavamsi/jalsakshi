"""Outbound calls that are not part of a workflow (ARCHITECTURE.md §15.4, §15.8, §15.10).

One Lambda, invoked asynchronously (by the IVR handler, the console API or EventBridge), with
``{"kind": ...}``:

- ``callback``: call back a number that gave a missed call: the REPORT menu for a consenting
  household, the OPERATOR flow for an operator with an open complaint, REGISTER for anyone else.
- ``register``: the first (consent) call to a household the secretary added in the console.
- ``broadcast``: deliver an approved announcement.
- ``weekly_summary``: the Monday summary call to each village's sarpanch and secretary.

Every call passes Cedar ``PlaceCall`` and the dialer's allowlist; call ids are deterministic per
event, and ``STEP#dispatch`` is a conditional write, so a retried invocation never dials twice.
"""

from __future__ import annotations

import hashlib
import time
from datetime import timedelta
from typing import Any, Final

import httpx

from jalsakshi.core.analytics import village_analytics
from jalsakshi.core.clock import today_ist
from jalsakshi.core.models import (
    ConsentStatus,
    Household,
    Operator,
    OperatorRole,
    Purpose,
    Village,
)
from jalsakshi.core.summary import weekly_summary_text
from jalsakshi.handlers import broadcasts, config, residents
from jalsakshi.handlers.calls import (
    CallRecord,
    callbacks_today,
    household_decision,
    is_consented,
    load_call,
    operator_decision,
    reported_households,
    save_call,
)
from jalsakshi.handlers.common import (
    PolicyDeniedError,
    activity,
    entrypoint,
    logger,
    mask_phone,
    record_denial,
)
from jalsakshi.handlers.config import VoiceProvider
from jalsakshi.handlers.dialer import DialError, dial
from jalsakshi.store import Repository
from jalsakshi.voice.flow import FlowSession

MAX_DELAY_S: Final = 30
SUMMARY_ROLES: Final = (OperatorRole.SARPANCH, OperatorRole.PANCHAYAT_SECRETARY)


@entrypoint
def handler(event: Any, context: Any) -> dict[str, Any]:
    """Dispatch one outbound job."""
    payload = event if isinstance(event, dict) else {}
    kind = str(payload.get("kind", ""))
    repo = config.repository()
    match kind:
        case "callback":
            return callback(
                repo,
                str(payload.get("phone", "")),
                int(payload.get("delay_s") or 0),
                str(payload.get("missed_at", "")),
            )
        case "register":
            return register(repo, str(payload["village_id"]), str(payload["household_id"]))
        case "broadcast":
            broadcast = broadcasts.load(
                repo, str(payload["village_id"]), str(payload["broadcast_id"])
            )
            try:
                sent = broadcasts.send(repo, broadcast)
            except PolicyDeniedError as denied:  # recorded already; a retry would not help
                return {"status": "denied", "policy_id": denied.decision.policy_ids[0]}
            return {"broadcast_id": sent.id, "recipients": sent.recipients}
        case "weekly_summary":
            return weekly_summaries(repo)
        case "operator_call":
            from jalsakshi.handlers import sfn_tasks, tickets

            ticket = tickets.load_ticket(repo, str(payload.get("ticket_id", "")))
            sfn_tasks.call_operator(repo, ticket)
            return {"status": "done", "ticket_id": ticket.id}
    logger.warning("unknown outbound job", extra={"kind": kind})
    return {"status": "ignored"}


# --- call-backs after a missed call -----------------------------------------------------------


def callback(repo: Repository, phone: str, delay_s: int = 0, missed_at: str = "") -> dict[str, Any]:
    """Call a missed caller back with the flow that fits who they are."""
    if delay_s > 0:
        time.sleep(min(delay_s, MAX_DELAY_S))
    if not phone.startswith("+"):
        return {"status": "ignored", "reason": "no caller id"}
    tag = hashlib.sha256(f"{phone}|{missed_at}".encode()).hexdigest()[:12]
    known = repo.find_households_by_phone(phone)
    households = [h for h in known if is_consented(h)]
    if households:
        return _report_callback(repo, households[0], phone, tag)
    roles = repo.lookup_phone(phone)
    for oid in roles.operators:
        operator = repo.get_operator(oid)
        if operator is not None:
            result = _operator_callback(repo, operator, phone, tag)
            if result is not None:
                return result
    if roles.operators and not known:
        # A Panchayat team member (operator, sarpanch, coordinator) is never registered as a
        # family: that would put team answers into a real village's record.
        return {"status": "ignored", "reason": "team member with no open complaint"}
    # A family the secretary added (or that declined) registers in its own village.
    return _register_callback(repo, phone, tag, known[0] if known else None)


def _report_callback(
    repo: Repository, household: Household, phone: str, tag: str
) -> dict[str, Any]:
    village = repo.get_village(household.village_id)
    if village is None:
        return {"status": "ignored", "reason": "village missing"}
    decision = household_decision(
        repo,
        household,
        Purpose.REPORT,
        caller_initiated=True,
        callbacks_today=max(callbacks_today(repo, phone) - 1, 0),
    )
    if not decision.allowed:
        record_denial(decision, village.id, f"call-back to {mask_phone(phone)}")
        return {"status": "denied", "policy_id": decision.policy_ids[0]}
    today = today_ist(config.now())
    flow = FlowSession(
        call_id=f"cb-{tag}",
        purpose=Purpose.REPORT,
        village_id=village.id,
        household_id=household.id,
        access=household.access,
        message_text_hi=residents.status_text_hi(repo, village, today),
    )
    record = CallRecord(
        flow=flow,
        provider=config.settings().voice_provider,
        day=today,
        origin="callback",
        caller_initiated=True,
    )
    return _dial(repo, record, phone, f"Calling back a family ({mask_phone(phone)})")


def _operator_callback(
    repo: Repository, operator: Operator, phone: str, tag: str
) -> dict[str, Any] | None:
    """An operator's missed call: the oldest open complaint routed to them, if any."""
    for village_id in operator.village_ids:
        for ticket in repo.list_open_tickets(village_id):
            routed = residents.route_operator(
                repo, village_id, ticket.water_point_id, skip=residents.not_mine(ticket)
            )
            if routed is None or routed.id != operator.id:
                continue
            decision = operator_decision(
                operator,
                village_id,
                caller_initiated=True,
                callbacks_today=max(callbacks_today(repo, phone) - 1, 0),
            )
            if not decision.allowed:
                record_denial(decision, village_id, f"call-back to operator {operator.id}")
                return {"status": "denied", "policy_id": decision.policy_ids[0]}
            status = repo.get_day_status(village_id, today_ist(ticket.opened_at))
            flow = FlowSession(
                call_id=f"cb-{tag}",
                purpose=Purpose.OPERATOR,
                village_id=village_id,
                operator_id=operator.id,
                ticket_id=ticket.id,
                ticket_reason=ticket.reason,
                reported_households=max(
                    reported_households(status, ticket.reason, ticket.water_point_id),
                    len(ticket.reporters),
                ),
                ticket_number=ticket.number,
                water_point_name=residents.point_name(repo, village_id, ticket.water_point_id),
            )
            record = CallRecord(
                flow=flow,
                provider=config.settings().voice_provider,
                day=today_ist(config.now()),
                origin="callback",
                caller_initiated=True,
            )
            return _dial(repo, record, operator.phone_e164, "Calling back the operator")
    return None


def _register_callback(
    repo: Repository, phone: str, tag: str, known: Household | None = None
) -> dict[str, Any]:
    village = repo.get_village(known.village_id) if known else _inbound_village(repo)
    if village is None:
        return {"status": "ignored", "reason": "no village takes missed calls"}
    household_id = known.id if known else residents.new_household_id(phone)
    existing = repo.get_household(village.id, household_id)
    stand_in = existing or Household(
        id=household_id,
        village_id=village.id,
        phone_e164=phone,
        consent_status=ConsentStatus.NONE,
    )
    decision = household_decision(
        repo,
        stand_in,
        Purpose.REGISTER,
        caller_initiated=True,
        callbacks_today=max(callbacks_today(repo, phone) - 1, 0),
    )
    if not decision.allowed:
        record_denial(decision, village.id, f"registration call-back to {mask_phone(phone)}")
        return {"status": "denied", "policy_id": decision.policy_ids[0]}
    flow = FlowSession(
        call_id=f"cb-{tag}",
        purpose=Purpose.REGISTER,
        village_id=village.id,
        household_id=household_id,
    )
    record = CallRecord(
        flow=flow,
        provider=config.settings().voice_provider,
        day=today_ist(config.now()),
        origin="callback",
        caller_initiated=True,
        phone_e164=phone,
    )
    return _dial(
        repo, record, phone, f"Calling back a new number to register ({mask_phone(phone)})"
    )


def _inbound_village(repo: Repository) -> Village | None:
    villages = repo.list_villages()
    return next((v for v in villages if v.inbound and v.active), None)


# --- console-triggered calls ------------------------------------------------------------------


def register(repo: Repository, village_id: str, household_id: str) -> dict[str, Any]:
    """The first call to a household added in the console: read the notice, ask for consent."""
    household = repo.get_household(village_id, household_id)
    if household is None:
        return {"status": "ignored", "reason": "household missing"}
    decision = household_decision(repo, household, Purpose.REGISTER)
    if not decision.allowed:
        record_denial(decision, village_id, f"registration call to household {household_id}")
        return {"status": "denied", "policy_id": decision.policy_ids[0]}
    today = today_ist(config.now())
    flow = FlowSession(
        call_id=f"reg-{village_id}-{household_id}-{today:%Y%m%d}",
        purpose=Purpose.REGISTER,
        village_id=village_id,
        household_id=household_id,
    )
    record = CallRecord(
        flow=flow,
        provider=config.settings().voice_provider,
        day=today,
        origin="console",
        phone_e164=household.phone_e164,
    )
    return _dial(
        repo,
        record,
        household.phone_e164,
        f"Registration call to {mask_phone(household.phone_e164)}",
    )


def call_household(
    repo: Repository,
    household: Household,
    purpose: Purpose,
    *,
    message: str,
    broadcast_id: str | None = None,
) -> bool:
    """One announcement call (policy-checked); True when it was placed or left pending."""
    decision = household_decision(repo, household, purpose)
    if not decision.allowed:
        record_denial(decision, household.village_id, f"{purpose} call to {household.id}")
        return False
    flow = FlowSession(
        call_id=f"bc-{broadcast_id}-{household.id}",
        purpose=purpose,
        village_id=household.village_id,
        household_id=household.id,
        message_text_hi=message,
    )
    record = CallRecord(
        flow=flow,
        provider=config.settings().voice_provider,
        day=today_ist(config.now()),
        origin="broadcast",
        broadcast_id=broadcast_id,
    )
    result = _dial(repo, record, household.phone_e164, None)
    return result.get("status") in {"dialled", "pending"}


# --- weekly summary ----------------------------------------------------------------------------


def weekly_summaries(repo: Repository) -> dict[str, Any]:
    """Call each active village's sarpanch and secretary with last week's numbers."""
    placed = 0
    for village in repo.list_villages():
        if not village.active:
            continue
        summary = summary_for(repo, village)
        for operator in repo.list_operators_for_village(village.id):
            if operator.role not in SUMMARY_ROLES:
                continue
            decision = operator_decision(operator, village.id)
            if not decision.allowed:
                record_denial(decision, village.id, f"summary call to {operator.id}")
                continue
            today = today_ist(config.now())
            flow = FlowSession(
                call_id=f"sum-{village.id}-{operator.id}-{today:%Y%m%d}",
                purpose=Purpose.SUMMARY,
                village_id=village.id,
                operator_id=operator.id,
                message_text_hi=summary.text_hi,
            )
            record = CallRecord(
                flow=flow,
                provider=config.settings().voice_provider,
                day=today,
                origin="summary",
            )
            if _dial(repo, record, operator.phone_e164, None).get("status") == "dialled":
                placed += 1
    return {"status": "done", "calls": placed}


def summary_for(repo: Repository, village: Village) -> Any:
    """Last 7 days' analytics for a village, as the spoken summary."""
    end = today_ist(config.now())
    start = end - timedelta(days=6)
    points = repo.list_water_points(village.id)
    analytics = village_analytics(
        village,
        start,
        end,
        config.now(),
        water_points=points,
        days=repo.list_day_statuses(village.id, start, end),
        tickets=repo.list_tickets(village_id=village.id),
        households=repo.list_households(village.id),
        consents=repo.list_consent_events(village.id),
        checkins=repo.list_checkins_between(village.id, start, end),
        broadcasts=repo.list_broadcasts(village.id),
        quality=repo.list_quality_tests(village.id),
    )
    return weekly_summary_text(village, analytics, points)


# --- dialling ----------------------------------------------------------------------------------


def _dial(repo: Repository, record: CallRecord, phone: str, feed_en: str | None) -> dict[str, Any]:
    existing = load_call(repo, record.call_id)
    if existing is not None:
        return {"status": "already_dialled", "call_id": record.call_id}
    save_call(repo, record)
    if record.provider is VoiceProvider.SIMULATOR:
        from jalsakshi.handlers.calls import mark_pending

        mark_pending(repo, record)
        return {"status": "pending", "call_id": record.call_id}
    if not repo.record_call_step(record.call_id, "dispatch", {"origin": record.origin}):
        return {"status": "already_dialled", "call_id": record.call_id}
    try:
        request_uuid = dial(record, phone)
    except (DialError, config.ConfigError, httpx.HTTPError) as exc:
        logger.warning("outbound call failed", extra={"call_id": record.call_id, "error": str(exc)})
        return {"status": "failed", "call_id": record.call_id, "error": str(exc)}
    save_call(repo, record.model_copy(update={"provider_call_uuid": request_uuid or None}))
    if feed_en:
        activity("call", record.flow.village_id, feed_en, feed_en)
    return {"status": "dialled", "call_id": record.call_id}
