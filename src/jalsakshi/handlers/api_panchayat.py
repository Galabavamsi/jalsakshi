"""Console API for the Gram Panchayat features (ARCHITECTURE.md §15.12), on the ``/api`` app.

Water points, adding families (who then get a consent call), the consent ledger, complaints
raised from the console, announcements (draft, sarpanch approval, send), water-quality tests,
analytics and the weekly summary. Imported at the end of ``handlers.api`` so the routes register
on the same resolver; phones stay masked and Cedar denials are 403s as everywhere else.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Final

from jalsakshi.core.analytics import village_analytics
from jalsakshi.core.clock import IST, today_ist
from jalsakshi.core.ids import new_id
from jalsakshi.core.models import (
    AccessKind,
    BroadcastKind,
    ConsentStatus,
    Freshness,
    GeoPoint,
    Household,
    QualityMethod,
    QualityResult,
    QualityTest,
    TicketOrigin,
    TicketReason,
    TicketState,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.core.summary import weekly_summary_text
from jalsakshi.data.official import load_official, official_age_note
from jalsakshi.handlers import advice, broadcasts, calls, config, residents, sfn_tasks, tickets
from jalsakshi.handlers.api import (
    _actor,
    _dump,
    _enum_value,
    _masked_household,
    _period,
    _role,
    _village,
    app,
)
from jalsakshi.handlers.common import ApiError, activity, json_body, json_response, mask_phone
from jalsakshi.store import Repository
from jalsakshi.voice.flow import NOTICE_VERSION

ANALYTICS_DAYS_DEFAULT: Final = 30
_PHONE: Final = re.compile(r"^\+91\d{10}$")
_SLUG: Final = re.compile(r"^[a-z0-9-]{1,40}$")


# --- water points --------------------------------------------------------------------------------


@app.get("/api/villages/<village_id>/water-points")
def list_water_points(village_id: str) -> Any:
    repo = config.repository()
    village = _village(repo, village_id)
    return json_response(200, [_dump(p) for p in repo.list_water_points(village.id)])


@app.post("/api/villages/<village_id>/water-points")
def put_water_point(village_id: str) -> Any:
    """Create or update a water point (the secretary names provisional ones)."""
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    point_id = str(body.get("id") or f"wp-{new_id('x', at=config.now())[-8:].lower()}")
    if not _SLUG.match(point_id):
        raise ApiError(400, "invalid_request", "id must be lowercase letters, digits or -")
    existing = repo.get_water_point(village.id, point_id)
    location = None
    if body.get("lat") is not None and body.get("lon") is not None:
        location = GeoPoint(
            lat=_number("lat", body["lat"]),
            lon=_number("lon", body["lon"]),
            source=str(body.get("location_source") or "entered in the console"),
        )
    operator_ids = body.get("operator_ids")
    if operator_ids is not None and (
        not isinstance(operator_ids, list) or not all(isinstance(o, str) for o in operator_ids)
    ):
        raise ApiError(400, "invalid_request", "operator_ids must be a list of operator ids")
    fields = {
        "id": point_id,
        "village_id": village.id,
        "kind": _enum_value(
            "kind", WaterPointKind, body.get("kind") or (existing.kind if existing else "PIPED")
        ),
        "name": str(body.get("name") or (existing.name if existing else point_id)),
        "name_hi": body.get("name_hi") or (existing.name_hi if existing else None),
        "hamlet": body.get("hamlet") or (existing.hamlet if existing else None),
        "supply_window": body.get("supply_window")
        or (existing.supply_window if existing else None),
        "operator_ids": list(operator_ids or (existing.operator_ids if existing else [])),
        "quorum": body.get("quorum") or (existing.quorum if existing else None),
        "location": location or (existing.location if existing else None),
        "provisional": False,
        "active": bool(body.get("active", existing.active if existing else True)),
    }
    point = WaterPoint.model_validate(fields)
    repo.put_water_point(point)
    return json_response(200, _dump(point))


# --- families ----------------------------------------------------------------------------------


@app.post("/api/villages/<village_id>/households")
def add_household(village_id: str) -> Any:
    """Add a family's number; it gets the consent (registration) call, never a check-in first."""
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    phone = str(body.get("phone") or "").replace(" ", "")
    if not _PHONE.match(phone):
        raise ApiError(400, "invalid_request", "phone must look like +91XXXXXXXXXX")
    # The same number already in this village (seeded, or registered by phone) is that family.
    same_village = [h for h in repo.find_households_by_phone(phone) if h.village_id == village.id]
    existing = same_village[0] if same_village else None
    household_id = existing.id if existing else residents.new_household_id(phone)
    if existing is not None and existing.effective_consent is ConsentStatus.GRANTED:
        return json_response(200, {"household": _masked_household(existing), "call": "none"})
    if existing is not None and existing.effective_consent is ConsentStatus.DECLINED:
        # Re-adding must not reset a refusal to NONE (that would bypass Cedar's
        # no-calls-after-withdrawal); the family can still join with its own missed call.
        raise ApiError(409, "consent_declined", "this family declined JalSakshi calls")
    wants_call = body.get("call", True) is not False
    if wants_call and not config.settings().outbound_fn:
        raise ApiError(503, "not_configured", "outbound calls are not configured on this stage")
    access = _enum_value("access", AccessKind, body["access"]) if body.get("access") else None
    household = Household(
        id=household_id,
        village_id=village.id,
        phone_e164=phone,
        display_name=(str(body.get("display_name") or "").strip() or None),
        consent_status=ConsentStatus.NONE,
        access=access,
        registered_via="console",
    )
    repo.put_household(household)
    call = "none"
    if wants_call:
        _invoke_outbound(
            {
                "kind": "register",
                "village_id": village.id,
                "household_id": household_id,
                "requested_at": config.now().isoformat(),
            }
        )
        call = "queued"
    activity(
        "consent",
        village.id,
        f"Secretary added a family ({mask_phone(phone)}); consent call {call}",
        f"सचिव ने एक परिवार जोड़ा ({mask_phone(phone)}); सहमति कॉल: {call}",
    )
    return json_response(201, {"household": _masked_household(household), "call": call})


@app.post("/api/villages/<village_id>/households/<household_id>/consent-call")
def call_again(village_id: str, household_id: str) -> Any:
    """Call a family that has not answered its consent call yet (Cedar still decides)."""
    repo = config.repository()
    village = _village(repo, village_id)
    household = repo.get_household(village.id, household_id)
    if household is None or not household.active:
        raise ApiError(404, "not_found", "no such family in this village")
    consent = household.effective_consent
    if consent is ConsentStatus.GRANTED:
        raise ApiError(409, "already_agreed", "this family has already agreed")
    if consent is not ConsentStatus.NONE:
        raise ApiError(409, "consent_declined", "this family said no; it can join by a missed call")
    if not config.settings().outbound_fn:
        raise ApiError(503, "not_configured", "outbound calls are not configured on this stage")
    _invoke_outbound(
        {
            "kind": "register",
            "village_id": village.id,
            "household_id": household.id,
            "requested_at": config.now().isoformat(),
        }
    )
    activity(
        "consent",
        village.id,
        f"Secretary asked for another consent call ({mask_phone(household.phone_e164)})",
        f"सचिव ने फिर से सहमति कॉल माँगी ({mask_phone(household.phone_e164)})",
    )
    return json_response(202, {"call": "queued"})


@app.get("/api/tickets/<ticket_id>/overview")
def ticket_overview(ticket_id: str) -> Any:
    """AI overview and suggested next step for a complaint (advice; the secretary decides)."""
    repo = config.repository()
    ticket = tickets.load_ticket(repo, ticket_id)
    _village(repo, ticket.village_id)
    return json_response(200, advice.overview(ticket).model_dump(mode="json"))


@app.post("/api/tickets/<ticket_id>/send-to-sarpanch")
def send_to_sarpanch(ticket_id: str) -> Any:
    """The secretary sends a complaint to the Sarpanch, who gets a call about it now."""
    repo = config.repository()
    ticket = tickets.load_ticket(repo, ticket_id)
    _village(repo, ticket.village_id)
    if ticket.state is TicketState.CLOSED_VERIFIED:
        raise ApiError(409, "closed", "this complaint is already closed")
    if not config.settings().outbound_fn:
        raise ApiError(503, "not_configured", "outbound calls are not configured on this stage")
    calls.escalate_to_panchayat(
        repo, ticket.id, _actor(), None, delay_s=0, reason=calls.ESCALATION_OFFICE
    )
    return json_response(200, _dump(tickets.load_ticket(repo, ticket.id)))


@app.post("/api/tickets/<ticket_id>/call-operator")
def call_operator_again(ticket_id: str) -> Any:
    """Call the pump operator about this complaint again (Cedar and the dialer still decide)."""
    repo = config.repository()
    ticket = tickets.load_ticket(repo, ticket_id)
    _village(repo, ticket.village_id)
    if ticket.state is TicketState.CLOSED_VERIFIED:
        raise ApiError(409, "closed", "this complaint is already closed")
    if ticket.state not in sfn_tasks.OPERATOR_CALL_STATES:
        raise ApiError(
            409,
            "not_waiting_for_operator",
            "the pump operator's first call is still on its way"
            if ticket.state is TicketState.OPEN
            else "the operator said it is fixed; families are being asked",
        )
    _invoke_outbound(
        {
            "kind": "operator_call",
            "ticket_id": ticket.id,
            "requested_at": config.now().isoformat(),
        }
    )
    activity(
        "ticket",
        ticket.village_id,
        f"Secretary asked JalSakshi to call the pump operator again about complaint "
        f"#{ticket.number}",
        f"सचिव ने शिकायत क्रमांक {ticket.number} के लिए नल जल मित्र को फिर कॉल करवाई",
    )
    return json_response(202, {"call": "queued"})


@app.get("/api/villages/<village_id>/consents")
def list_consents(village_id: str) -> Any:
    """The consent ledger (masked phones), oldest first: the proof of consent."""
    repo = config.repository()
    village = _village(repo, village_id)
    events = [_dump(e) for e in repo.list_consent_events(village.id)]
    return json_response(
        200,
        {
            "events": events,
            "notice_version": NOTICE_VERSION,
            "notice_sha256": residents.notice_sha256(),
            "label": (
                "Designed to the DPDP Act 2023 / Rules 2025 standard; the Act's consent "
                "provisions are in force from May 2027."
            ),
        },
    )


# --- complaints from the console ---------------------------------------------------------------


@app.post("/api/villages/<village_id>/tickets")
def raise_ticket(village_id: str) -> Any:
    """A complaint someone brought to the Panchayat office (on behalf of a registered family)."""
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    reason = _enum_value("reason", TicketReason, body.get("reason"))
    household_id = str(body.get("household_id") or "")
    household = repo.get_household(village.id, household_id) if household_id else None
    if household is None:
        raise ApiError(422, "household_required", "pick the family that reported it")
    ticket = residents.report_problem(repo, village, household, reason, origin=TicketOrigin.CONSOLE)
    return json_response(201, _dump(ticket))


# --- announcements --------------------------------------------------------------------------


@app.get("/api/villages/<village_id>/broadcasts")
def list_broadcasts(village_id: str) -> Any:
    repo = config.repository()
    village = _village(repo, village_id)
    sent_week = broadcasts.sent_last_week(repo, village.id)
    rows = [_dump(b) for b in repo.list_broadcasts(village.id)]
    return json_response(
        200, {"broadcasts": rows, "sent_last_7_days": sent_week, "weekly_limit": 2}
    )


@app.post("/api/villages/<village_id>/broadcasts")
def draft_broadcast(village_id: str) -> Any:
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    text = str(body.get("text_hi") or "").strip()
    if not 1 <= len(text) <= 400:
        raise ApiError(400, "invalid_request", "text_hi must be 1-400 characters")
    kind = _enum_value("kind", BroadcastKind, body.get("kind") or "CUSTOM")
    point_id = _known_point(repo, village.id, body.get("water_point_id"))
    draft = broadcasts.draft(repo, village.id, kind, text, _actor(), point_id)
    return json_response(201, _dump(draft))


@app.post("/api/villages/<village_id>/broadcasts/<broadcast_id>/<action>")
def broadcast_action(village_id: str, broadcast_id: str, action: str) -> Any:
    """``approve`` (sarpanch only), ``send`` (approved, 2 a week) or ``cancel``."""
    repo = config.repository()
    broadcast = broadcasts.load(repo, village_id, broadcast_id)
    match action:
        case "approve":
            return json_response(200, _dump(broadcasts.approve(repo, broadcast, _role(), _actor())))
        case "send":
            broadcasts.check_send(repo, broadcast)
            _invoke_outbound(
                {"kind": "broadcast", "village_id": village_id, "broadcast_id": broadcast_id}
            )
            return json_response(202, {**(_dump(broadcast) or {}), "queued": True})
        case "cancel":
            return json_response(200, _dump(broadcasts.cancel(repo, broadcast)))
    raise ApiError(404, "not_found", f"unknown action {action!r}")


# --- water quality -----------------------------------------------------------------------------


@app.get("/api/villages/<village_id>/quality")
def list_quality(village_id: str) -> Any:
    """Tests entered here, plus the official (JJM WQMIS) record with its age."""
    repo = config.repository()
    village = _village(repo, village_id)
    official = load_official(village.lgd_code) if village.lgd_code else None
    return json_response(
        200,
        {
            "tests": [_dump(t) for t in repo.list_quality_tests(village.id)],
            "official": official.model_dump(mode="json") if official else None,
            "official_note": official_age_note(official, config.now()) if official else None,
        },
    )


@app.post("/api/villages/<village_id>/quality")
def add_quality(village_id: str) -> Any:
    """Record a field-test-kit or lab result for a water point (added to its open DIRTY ticket)."""
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    tested_at = _time(body.get("tested_at")) or config.now()
    parameters = body.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ApiError(400, "invalid_request", "parameters must be an object of name: value")
    test = QualityTest(
        id=new_id("qt", at=config.now()),
        village_id=village.id,
        water_point_id=_known_point(repo, village.id, body.get("water_point_id")),
        tested_at=tested_at,
        method=_enum_value("method", QualityMethod, body.get("method") or "FTK"),
        result=_enum_value("result", QualityResult, body.get("result")),
        parameters={str(k): str(v) for k, v in parameters.items()},
        entered_by=_actor(),
        note=(str(body.get("note") or "").strip() or None),
    )
    repo.put_quality_test(test)
    dirty = repo.get_open_ticket(village.id, test.water_point_id, TicketReason.DIRTY)
    if dirty is not None:
        detail = {"note": "quality_test", "result": test.result.value, "method": test.method.value}
        residents.update_ticket(repo, dirty.id, lambda t: t, detail, _actor())
    return json_response(201, _dump(test))


# --- analytics and summary ---------------------------------------------------------------------


@app.get("/api/villages/<village_id>/analytics")
def get_analytics(village_id: str) -> Any:
    repo = config.repository()
    village = _village(repo, village_id)
    start, end = _period(ANALYTICS_DAYS_DEFAULT)
    return json_response(200, _analytics(repo, village, start, end).model_dump(mode="json"))


@app.get("/api/villages/<village_id>/summary")
def get_summary(village_id: str) -> Any:
    repo = config.repository()
    village = _village(repo, village_id)
    end = today_ist(config.now())
    start = end - timedelta(days=6)
    points = repo.list_water_points(village.id)
    summary = weekly_summary_text(village, _analytics(repo, village, start, end), points)
    return json_response(200, summary.model_dump(mode="json"))


def _analytics(repo: Repository, village: Any, start: Any, end: Any) -> Any:
    days = repo.list_day_statuses(village.id, start, end)
    checkins = repo.list_checkins_between(village.id, start, end)
    simulated = any(c.captured_via.value == "SIMULATOR" for c in checkins)
    return village_analytics(
        village,
        start,
        end,
        config.now(),
        water_points=repo.list_water_points(village.id),
        days=days,
        tickets=repo.list_tickets(village_id=village.id),
        households=repo.list_households(village.id),
        consents=repo.list_consent_events(village.id),
        checkins=checkins,
        broadcasts=repo.list_broadcasts(village.id),
        quality=repo.list_quality_tests(village.id),
        freshness=Freshness.SIMULATED if simulated else Freshness.LIVE,
    )


# --- helpers ---------------------------------------------------------------------------------


def _invoke_outbound(job: dict[str, Any]) -> None:
    function = config.settings().outbound_fn
    if not function:
        raise ApiError(503, "not_configured", "outbound calls are not configured on this stage")
    config.client("lambda").invoke(
        FunctionName=function, InvocationType="Event", Payload=json.dumps(job).encode()
    )


def _known_point(repo: Repository, village_id: str, raw: object) -> str | None:
    """A water point id from the body: None when absent, 400 when the village has no such point."""
    if not raw:
        return None
    point_id = str(raw)
    if repo.get_water_point(village_id, point_id) is None:
        raise ApiError(400, "invalid_request", f"unknown water point {point_id!r}")
    return point_id


def _number(name: str, raw: object) -> float:
    try:
        return float(str(raw))
    except ValueError as exc:
        raise ApiError(400, "invalid_request", f"{name} must be a number") from exc


def _time(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "tested_at must be an ISO time") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)
