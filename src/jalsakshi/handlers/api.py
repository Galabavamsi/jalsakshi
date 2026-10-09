"""Console API (``/api/*`` behind the Cognito JWT authorizer), ARCHITECTURE.md §13.

Thin routes over store, core, policy, data and agent. Bodies are the ``core.models`` types
serialised in JSON mode; phones are always masked; Cedar denies are answered as
``403 {denied, policy_id, reason_hi, reason_en}`` and every other error as
``{error: {code, message}}``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from pydantic import BaseModel

from jalsakshi.agent.brief import BriefInput, BriefSummary, generate_brief
from jalsakshi.agent.evidence import to_ist_date
from jalsakshi.core.clock import today_ist
from jalsakshi.core.models import (
    CapturedVia,
    DayStatus,
    Freshness,
    Household,
    Operator,
    OperatorRole,
    Purpose,
    SourceTag,
    Ticket,
    TicketState,
    Village,
)
from jalsakshi.core.tickets import Denied, TicketEventKind, closing_quorum
from jalsakshi.core.verify import VerifyOutcome, evaluate_verification
from jalsakshi.data.official import load_official, official_age_note
from jalsakshi.handlers import config, residents, sfn, tickets
from jalsakshi.handlers.calls import household_decision
from jalsakshi.handlers.common import (
    ApiError,
    PolicyDeniedError,
    count,
    entrypoint,
    install_error_handlers,
    json_body,
    json_response,
    logger,
    mask_phone,
    record_denial,
)
from jalsakshi.handlers.context import load_context
from jalsakshi.policy import (
    Decision,
    can_close_verified,
    can_publish_evidence,
    can_view_household_answers,
)
from jalsakshi.store import Repository

OBSERVED_DAYS: Final = 7
DAYS_DEFAULT: Final = 14
BRIEF_DAYS_DEFAULT: Final = 7
MAX_RANGE_DAYS: Final = 92
ACTIVITY_LOOKBACK: Final = timedelta(hours=1)
CHECKIN_SOURCE: Final = "JalSakshi household check-ins"
CHECKIN_SOURCE_SIMULATED: Final = "JalSakshi household check-ins (web-phone simulator)"
DEFAULT_ROLE: Final = OperatorRole.PANCHAYAT_SECRETARY
# A user in several groups gets the most restricted role first.
_ROLE_ORDER: Final = (
    OperatorRole.PHED_EE_SIM,
    OperatorRole.PHED_AE_SIM,
    OperatorRole.HANDPUMP_MECHANIC,
    OperatorRole.NAL_JAL_MITRA,
    OperatorRole.SARPANCH,
    OperatorRole.PANCHAYAT_SECRETARY,
)

app = APIGatewayHttpResolver()
install_error_handlers(app)


# --- villages -------------------------------------------------------------------------------------


@app.get("/api/villages")
def list_villages() -> Response:
    """Every village with today's status, its open ticket and the last 7 days' tally."""
    repo = config.repository()
    today = today_ist(config.now())
    allowed = _allowed_villages(repo)
    rows = [_village_row(repo, v, today) for v in repo.list_villages() if v.id in allowed]
    return json_response(200, rows)


@app.get("/api/villages/<village_id>")
def get_village(village_id: str) -> Response:
    """Village, masked households, operators and the cached public context."""
    repo = config.repository()
    village = _village(repo, village_id)
    official = load_official(village.lgd_code) if village.lgd_code else None
    body = {
        "village": _dump(village),
        "households": [_masked_household(h) for h in repo.list_households(village.id)],
        "operators": [_masked_operator(o) for o in repo.list_operators_for_village(village.id)],
        "water_points": [_dump(p) for p in repo.list_water_points(village.id)],
        "official": official.model_dump(mode="json") if official else None,
        "official_note": official_age_note(official, config.now()) if official else None,
        "context": load_context(village.id),
    }
    return json_response(200, body)


@app.get("/api/villages/<village_id>/days")
def list_days(village_id: str) -> Response:
    """Day statuses in ``from``..``to`` (default: the last 14 days)."""
    repo = config.repository()
    village = _village(repo, village_id)
    start, end = _period(DAYS_DEFAULT)
    return json_response(200, [_dump(d) for d in repo.list_day_statuses(village.id, start, end)])


@app.get("/api/villages/<village_id>/checkins")
def list_checkins(village_id: str) -> Response:
    """One day's check-ins (household id and answers, phone masked); Cedar-guarded by role."""
    decision = can_view_household_answers(_role())
    _require(decision, village_id, "viewing household answers")
    repo = config.repository()
    village = _village(repo, village_id)
    day = _date_query("date") or today_ist(config.now())
    purpose = _enum_query("purpose", Purpose) or Purpose.DAILY
    phones = {h.id: mask_phone(h.phone_e164) for h in repo.list_households(village.id)}
    rows = [
        {**_dump(c), "phone_masked": phones.get(c.household_id)}
        for c in repo.list_checkins(village.id, day, purpose)
    ]
    return json_response(200, rows)


@app.post("/api/villages/<village_id>/checkin/run")
def run_checkin(village_id: str) -> Response:
    """Start CheckInRun now (demo trigger). Each call is still policy-checked in the workflow."""
    body = json_body(app)
    purpose = _enum_value("purpose", Purpose, body.get("purpose", Purpose.DAILY))
    if purpose is not Purpose.DAILY:
        raise ApiError(400, "invalid_request", "only DAILY check-in runs can be started")
    repo = config.repository()
    village = _village(repo, village_id)
    arn = config.settings().checkin_sfn_arn
    if not arn:
        raise ApiError(503, "not_configured", "the check-in workflow is not deployed")
    households = repo.list_households(village.id, active_only=True)
    if not households:
        raise ApiError(409, "no_households", "this village has no active households")
    decisions = [household_decision(repo, h, purpose) for h in households]
    if not any(d.allowed for d in decisions):
        _require(decisions[0], village.id, "check-in run")
    payload = {
        "village_id": village.id,
        "purpose": purpose.value,
        "trigger": "console",
        "requested_by": _actor(),
    }
    return json_response(200, {"execution_arn": sfn.start_execution(arn, payload)})


@app.get("/api/villages/<village_id>/brief")
def get_brief(village_id: str) -> Response:
    """Gram Sabha evidence sheet (agent, else template); Cedar blocks it on stale data."""
    repo = config.repository()
    village = _village(repo, village_id)
    start, end = _period(BRIEF_DAYS_DEFAULT)
    days = repo.list_day_statuses(village.id, start, end)
    _require(can_publish_evidence(_age_hours(days)), village.id, "publishing the brief")
    village_tickets = [t for t in repo.list_tickets(village_id=village.id) if _overlaps(t, start)]
    inp = BriefInput(
        village=village,
        period_from=start,
        period_to=end,
        summary=BriefSummary.from_records(days, village_tickets, start, end),
        tickets=[t for t in village_tickets if to_ist_date(t.opened_at) <= end],
        sources=[_checkin_source(repo, village.id, days), *_context_sources(village.id)],
    )
    use_agent = config.settings().brief_use_agent
    brief = generate_brief(inp, use_agent=use_agent, now=config.now())
    if use_agent and brief.generated_by == "template":
        count("AgentFallbackUsed")
    logger.info("brief generated", extra={"village_id": village.id, "by": brief.generated_by})
    return json_response(200, brief.model_dump(mode="json"))


# --- tickets --------------------------------------------------------------------------------------


@app.get("/api/tickets")
def list_tickets() -> Response:
    """Tickets, newest first; every state when ``state`` is omitted."""
    state = _enum_query("state", TicketState)
    village_id = app.current_event.get_query_string_value("village_id") or None
    repo = config.repository()
    allowed = _allowed_villages(repo)
    found = repo.list_tickets(state=state, village_id=village_id)
    return json_response(200, [_dump(t) for t in found if t.village_id in allowed])


@app.get("/api/tickets/<ticket_id>")
def get_ticket(ticket_id: str) -> Response:
    """One ticket with its events."""
    repo = config.repository()
    ticket = tickets.load_ticket(repo, ticket_id)
    _village(repo, ticket.village_id)
    return json_response(200, _dump(ticket))


@app.post("/api/tickets/<ticket_id>/operator-fixed")
def operator_fixed(ticket_id: str) -> Response:
    """The operator reports a fix from the console; verification calls follow."""
    operator_id = str(json_body(app).get("operator_id") or "").strip()
    if not operator_id:
        raise ApiError(400, "invalid_request", "operator_id is required")
    repo = config.repository()
    ticket = tickets.load_ticket(repo, ticket_id)
    operator = repo.get_operator(operator_id)
    if operator is None:
        raise ApiError(404, "not_found", f"operator {operator_id!r} not found")
    if ticket.village_id not in operator.village_ids:
        raise ApiError(422, "operator_not_for_village", "operator does not serve this village")
    result = tickets.report_fixed(repo, ticket.id, _actor(), "console", operator_id=operator.id)
    return json_response(200, _dump(_transitioned(result)))


@app.post("/api/tickets/<ticket_id>/close")
def close_ticket(ticket_id: str) -> Response:
    """Close as verified only if the households' answers allow it (Cedar verify-needs-quorum)."""
    repo = config.repository()
    ticket = tickets.load_ticket(repo, ticket_id)
    if ticket.state is TicketState.CLOSED_VERIFIED:
        return json_response(200, _dump(ticket))
    village = _village(repo, ticket.village_id)
    quorum = closing_quorum(ticket, residents.point_quorum(repo, village, ticket.water_point_id))
    since = tickets.verify_started_at(ticket)
    checkins = tickets.verify_checkins(repo, ticket, today_ist(config.now()))
    result = evaluate_verification(checkins, quorum, since=since)
    decision = can_close_verified(ticket, quorum, result.yes)
    if not decision.allowed:
        _note_denied(repo, ticket, decision)
        _require(decision, ticket.village_id, f"closing ticket {ticket.id}")
    if result.outcome is not VerifyOutcome.CLOSED_VERIFIED:
        raise ApiError(409, "verification_failed", "a household still reports a problem")
    detail = {"via": "console", "yes": result.yes, "no": result.no, "quorum": quorum}
    closed = tickets.apply_event(repo, ticket.id, TicketEventKind.VERIFIED_OK, _actor(), detail)
    if not isinstance(closed, Denied):
        count("TicketsClosedVerified")
    return json_response(200, _dump(_transitioned(closed)))


# --- who am I ------------------------------------------------------------------------------------


# --- activity -------------------------------------------------------------------------------------


@app.get("/api/activity")
def list_activity() -> Response:
    """Feed entries after ``since`` (ISO time; default: the last hour), oldest first."""
    raw = app.current_event.get_query_string_value("since")
    since = _parse_since(raw) if raw else config.now() - ACTIVITY_LOOKBACK
    entries = config.repository().list_activity(since)
    return json_response(200, [e.model_dump(mode="json") for e in entries])


@entrypoint
def handler(event: Any, context: Any) -> Any:
    """Lambda entrypoint for every ``/api/*`` route."""
    return app.resolve(event, context)


# --- helpers --------------------------------------------------------------------------------------


def _dump(model: BaseModel | None) -> dict[str, Any] | None:
    return None if model is None else model.model_dump(mode="json")


def _village(repo: Repository, village_id: str) -> Village:
    village = repo.get_village(village_id)
    if village is None or village.id not in _allowed_villages(repo):
        raise ApiError(404, "not_found", f"village {village_id!r} not found")
    return village


def user_id() -> str:
    """The Cognito ``sub`` of the signed-in user ("local" in tests without one)."""
    claims = _claims()
    return str(claims.get("sub") or claims.get("username") or "local")


def _allowed_villages(repo: Repository) -> set[str]:
    """Admins (Cognito group ADMIN) see every village; everyone else only their own."""
    if "ADMIN" in set(_groups(_claims().get("cognito:groups"))) or not _claims().get("sub"):
        return {v.id for v in repo.list_villages()}
    return set(repo.user_villages(user_id()))


def _village_row(repo: Repository, village: Village, today: date) -> dict[str, Any]:
    start = today - timedelta(days=OBSERVED_DAYS - 1)
    days = repo.list_day_statuses(village.id, start, today)
    summary = BriefSummary.from_records(days, [], start, today)
    observed = summary.model_dump(
        include={"days", "supplied", "no_supply", "partial", "dirty", "unverified"}
    )
    observed["source"] = _checkin_source(repo, village.id, days).model_dump(mode="json")
    return {
        "village": _dump(village),
        "today": _dump(next((d for d in days if d.date == today), None)),
        "open_ticket": _dump(repo.get_open_ticket(village.id)),
        "open_tickets": [_dump(t) for t in repo.list_open_tickets(village.id)],
        "observed_7d": observed,
    }


def _masked_household(household: Household) -> dict[str, Any]:
    body = household.model_dump(mode="json", exclude={"phone_e164"})
    return {**body, "phone_masked": mask_phone(household.phone_e164)}


def _masked_operator(operator: Operator) -> dict[str, Any]:
    return {**operator.model_dump(mode="json"), "phone_e164": mask_phone(operator.phone_e164)}


def _checkin_source(repo: Repository, village_id: str, days: Sequence[DayStatus]) -> SourceTag:
    """Source of the household tallies: ``simulated`` when any answer came from the simulator."""
    latest = max((d.computed_at for d in days), default=None)
    simulated = _any_simulated(repo, village_id, days)
    return SourceTag(
        source=CHECKIN_SOURCE_SIMULATED if simulated else CHECKIN_SOURCE,
        observed_at=latest,
        fetched_at=config.now(),
        freshness=Freshness.SIMULATED if simulated else Freshness.LIVE,
    )


def _any_simulated(repo: Repository, village_id: str, days: Sequence[DayStatus]) -> bool:
    return any(
        c.captured_via is CapturedVia.SIMULATOR
        for d in days
        for c in repo.list_checkins(village_id, d.date, Purpose.DAILY)
    )


def _context_sources(village_id: str) -> list[SourceTag]:
    context = load_context(village_id)
    tags = []
    for value in context.values():
        if isinstance(value, dict) and isinstance(value.get("source"), dict):
            tags.append(SourceTag.model_validate(value["source"]))
    return tags


def _age_hours(days: Sequence[DayStatus]) -> float:
    latest = max((d.computed_at for d in days), default=None)
    if latest is None:
        return math.inf
    return (config.now() - latest).total_seconds() / 3600


def _overlaps(ticket: Ticket, start: date) -> bool:
    return ticket.state is not TicketState.CLOSED_VERIFIED or (
        to_ist_date(ticket.updated_at) >= start
    )


def _transitioned(result: Ticket | Denied) -> Ticket:
    if isinstance(result, Denied):
        raise ApiError(409, "transition_denied", result.reason)
    return result


def _note_denied(repo: Repository, ticket: Ticket, decision: Decision) -> None:
    """Keep the denied close attempt on the ticket's audit trail (best effort)."""
    detail = {"note": "close_denied", "policy_id": decision.policy_ids[0]}
    try:
        tickets.apply_event(repo, ticket.id, TicketEventKind.NOTE, _actor(), detail)
    except Exception:
        logger.exception("could not note the denied close", extra={"ticket_id": ticket.id})


def _require(decision: Decision, village_id: str | None, subject: str) -> None:
    if not decision.allowed:
        record_denial(decision, village_id, subject)
        raise PolicyDeniedError(decision)


def _claims() -> dict[str, Any]:
    authorizer = app.current_event.request_context.authorizer
    claims = authorizer.jwt_claim if authorizer is not None else None
    return dict(claims or {})


def _groups(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(g) for g in raw]
    text = str(raw or "").strip().strip("[]")
    return [part for part in text.replace(",", " ").split() if part]


def _role() -> OperatorRole:
    groups = set(_groups(_claims().get("cognito:groups")))
    return next((role for role in _ROLE_ORDER if role.value in groups), DEFAULT_ROLE)


def _actor() -> str:
    claims = _claims()
    who = claims.get("username") or claims.get("cognito:username") or claims.get("sub")
    return f"console:{who or 'unknown'}"


def _date_query(name: str) -> date | None:
    raw = app.current_event.get_query_string_value(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", f"{name} must be YYYY-MM-DD") from exc


def _enum_query[E: StrEnum](name: str, kind: type[E]) -> E | None:
    raw = app.current_event.get_query_string_value(name)
    return _enum_value(name, kind, raw) if raw else None


def _enum_value[E: StrEnum](name: str, kind: type[E], raw: object) -> E:
    try:
        return kind(str(raw))
    except ValueError as exc:
        raise ApiError(400, "invalid_request", f"unknown {name} {raw!r}") from exc


def _period(default_days: int) -> tuple[date, date]:
    end = _date_query("to") or today_ist(config.now())
    start = _date_query("from") or end - timedelta(days=default_days - 1)
    if start > end:
        raise ApiError(400, "invalid_request", "from must not be after to")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ApiError(400, "invalid_request", f"at most {MAX_RANGE_DAYS} days per request")
    return start, end


def _parse_since(raw: str) -> datetime:
    try:
        since = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "since must be an ISO 8601 time") from exc
    if since.tzinfo is None:
        raise ApiError(400, "invalid_request", "since needs a timezone (e.g. Z)")
    return since


# Gram Panchayat routes (water points, families, consent, announcements, quality, analytics)
# register on the same resolver.
from jalsakshi.handlers import api_onboarding, api_panchayat  # noqa: E402, F401
