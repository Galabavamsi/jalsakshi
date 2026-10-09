"""Resident-side glue for v2 (ARCHITECTURE.md §15): registration and the consent ledger,
withdrawal, water points, resident-reported complaints and who a complaint goes to.

Decisions stay in core (reconcile, tickets, policy); this module only loads, saves and starts
workflows. Every write is safe to repeat: consent events are conditional puts, a complaint joins
the open ticket of its water point and reason, and TicketFlow executions are named after the
ticket so a second start is a no-op.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Final

from botocore.exceptions import ClientError

from jalsakshi.core.clock import today_ist
from jalsakshi.core.ids import new_id
from jalsakshi.core.models import (
    ACCESS_POINT_KIND,
    AccessKind,
    CheckIn,
    CleanAnswer,
    Consent,
    ConsentAction,
    ConsentEvent,
    ConsentStatus,
    DayStatus,
    DayStatusValue,
    Household,
    NoteIssue,
    Operator,
    OperatorRole,
    Purpose,
    Ticket,
    TicketOrigin,
    TicketReason,
    Village,
    WaterAnswer,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.core.reconcile import DAY_PURPOSES, is_answered, latest_answers, tickets_to_open
from jalsakshi.core.tickets import (
    Denied,
    TicketEventKind,
    new_ticket,
    report_quorum,
    transition,
    with_reporter,
)
from jalsakshi.handlers import config
from jalsakshi.handlers.common import activity, count, dumps, logger, mask_phone
from jalsakshi.store import ConflictError, Repository
from jalsakshi.voice.catalog import catalog_for
from jalsakshi.voice.flow import ConsentAnswer, FlowSession, notice_version

MAX_SAVE_ATTEMPTS: Final = 3
_TICK: Final = timedelta(microseconds=1)

POINT_NAMES: Final[dict[WaterPointKind, tuple[str, str]]] = {
    WaterPointKind.PIPED: ("piped water supply", "नल जल योजना"),
    WaterPointKind.HANDPUMP: ("handpump", "हैंडपंप"),
    WaterPointKind.BOREWELL: ("borewell / well", "बोरवेल / कुआँ"),
    WaterPointKind.TANKER: ("tanker supply", "टैंकर"),
    WaterPointKind.OTHER: ("other source", "अन्य स्रोत"),
}
STATUS_HI: Final[dict[DayStatusValue, str]] = {
    DayStatusValue.SUPPLIED: "paani aaya",
    DayStatusValue.PARTIAL: "kuch gharon mein kam paani aaya",
    DayStatusValue.NO_SUPPLY: "paani nahi aaya",
    DayStatusValue.DIRTY: "gandle paani ki shikayat hai",
    DayStatusValue.UNVERIFIED: "abhi poori jaankari nahi hai",
}
REASON_HI: Final[dict[TicketReason, str]] = {
    TicketReason.NO_SUPPLY: "paani nahi aaya",
    TicketReason.DIRTY: "gandla paani",
    TicketReason.LOW_PRESSURE: "kam paani",
    TicketReason.LEAK: "pipe leak",
    TicketReason.BROKEN: "pump kharab",
    TicketReason.OTHER: "anya shikayat",
}


# --- consent ------------------------------------------------------------------------------------


def notice_sha256(language: str = "hi") -> str:
    """Fingerprint of the consent notice text that was read out (stored with every event)."""
    text = catalog_for(language).text("register.notice")
    return hashlib.sha256(f"{notice_version(language)}|{text}".encode()).hexdigest()


def with_language(repo: Repository, flow: FlowSession) -> FlowSession:
    """Fix the call's language when it is answered: the family's own, else the village's first.

    A first (registration) call also offers every language the village calls in.
    """
    if flow.language is not None:
        return flow
    village = repo.get_village(flow.village_id) if flow.village_id else None
    offered = list((village.languages if village else None) or ["hi"])
    language = offered[0]
    if flow.household_id and flow.village_id and flow.purpose is not Purpose.REGISTER:
        household = repo.get_household(flow.village_id, flow.household_id)
        if household is not None and household.language:
            language = household.language
    update: dict[str, object] = {"language": language}
    if flow.purpose is Purpose.REGISTER:
        update["offered_languages"] = offered
    return flow.model_copy(update=update)


def log_consent(
    repo: Repository,
    village_id: str,
    household_id: str,
    phone: str,
    action: ConsentAction,
    *,
    at: datetime,
    call_id: str | None,
    digits: str | None,
    channel: str = "ivr_keypad",
    language: str = "hi",
) -> ConsentEvent:
    """Append one consent-ledger entry (masked phone only)."""
    event = ConsentEvent(
        village_id=village_id,
        household_id=household_id,
        phone_masked=mask_phone(phone) or "",
        action=action,
        notice_version=notice_version(language),
        notice_sha256=notice_sha256(language),
        channel=channel,
        call_id=call_id,
        digits=digits,
        at=at,
    )
    repo.append_consent_event(event)
    count("ConsentEvents", action=action.value)
    return event


def finish_registration(
    repo: Repository,
    *,
    village_id: str,
    household_id: str,
    phone: str,
    call_id: str,
    adult: bool | None,
    consent: ConsentAnswer | None,
    digits: str | None,
    access: AccessKind | None,
    via: str = "ivr",
    language: str = "hi",
) -> Household | None:
    """Apply a REGISTER call's outcome: ledger entry, then create or update the household.

    Returns the household when consent was granted. An unknown caller who declines or stays
    silent leaves nothing behind but the (masked) ledger entry.
    """
    now = config.now()
    existing = repo.get_household(village_id, household_id)
    if adult is False:
        log_consent(
            repo,
            village_id,
            household_id,
            phone,
            ConsentAction.MINOR,
            at=now,
            call_id=call_id,
            language=language,
            digits="2",
        )
        return None
    if consent is ConsentAnswer.DECLINED:
        log_consent(
            repo,
            village_id,
            household_id,
            phone,
            ConsentAction.DECLINED,
            at=now,
            call_id=call_id,
            language=language,
            digits=digits,
        )
        if existing is not None:
            repo.put_household(
                existing.model_copy(
                    update={"consent_status": ConsentStatus.DECLINED, "active": False}
                )
            )
        return None
    if consent is not ConsentAnswer.GRANTED:
        return None
    log_consent(
        repo,
        village_id,
        household_id,
        phone,
        ConsentAction.GRANTED,
        at=now,
        call_id=call_id,
        language=language,
        digits=digits,
    )
    village = repo.get_village(village_id)
    point = point_for_access(repo, village, access) if village and access else None
    base = existing or Household(
        id=household_id, village_id=village_id, phone_e164=phone, registered_via=via
    )
    household = base.model_copy(
        update={
            "consent": Consent(
                given_at=now,
                channel="ivr_keypad",
                notice_version=notice_version(language),
                call_id=call_id,
                language=language,
                evidence_ref=f"consent-ledger:{call_id}",
            ),
            "consent_status": ConsentStatus.GRANTED,
            "access": access or base.access,
            "language": language,
            "water_point_id": point.id if point else base.water_point_id,
            "active": True,
        }
    )
    repo.put_household(household)
    activity(
        "consent",
        village_id,
        f"A family registered and gave consent ({mask_phone(phone)})",
        f"एक परिवार ने पंजीकरण कर सहमति दी ({mask_phone(phone)})",
    )
    return household


def withdraw(repo: Repository, household: Household, *, call_id: str | None) -> None:
    """Stop all calls and erase the household (the ledger keeps a masked entry)."""
    log_consent(
        repo,
        household.village_id,
        household.id,
        household.phone_e164,
        ConsentAction.WITHDRAWN,
        at=config.now(),
        call_id=call_id,
        digits="9",
    )
    repo.delete_household(household.village_id, household.id)
    activity(
        "consent",
        household.village_id,
        "A family stopped JalSakshi calls; their details were erased",
        "एक परिवार ने JalSakshi कॉल बंद कराईं; उनकी जानकारी हटा दी गई",
    )


def new_household_id(phone: str) -> str:
    """Stable id for a number registering itself (same number, same id)."""
    return "hh-" + hashlib.sha256(phone.encode()).hexdigest()[:10]


# --- water points -------------------------------------------------------------------------------


def point_for_access(repo: Repository, village: Village, access: AccessKind) -> WaterPoint:
    """The village's active point for this access kind, creating a provisional one if needed."""
    kind = ACCESS_POINT_KIND[access]
    points = [p for p in repo.list_water_points(village.id, active_only=True) if p.kind is kind]
    if points:
        return points[0]
    name_en, name_hi = POINT_NAMES[kind]
    # Never reuse the id of an existing point (a deactivated one would be overwritten).
    taken = {p.id for p in repo.list_water_points(village.id)}
    ids = (f"wp-{kind.value.lower()}-{n}" for n in itertools.count(1))
    point = WaterPoint(
        id=next(i for i in ids if i not in taken),
        village_id=village.id,
        kind=kind,
        name=f"{village.name} {name_en}",
        name_hi=f"{village.name_hi or village.name} {name_hi}",
        provisional=True,
    )
    repo.put_water_point(point)
    return point


def point_name(repo: Repository, village_id: str, water_point_id: str | None) -> str | None:
    """Spoken name of a water point (Hindi when known)."""
    if water_point_id is None:
        return None
    point = repo.get_water_point(village_id, water_point_id)
    if point is None:
        return None
    return point.name_hi or point.name


def point_quorum(repo: Repository, village: Village, water_point_id: str | None) -> int:
    """Households needed to decide a point's day (its own quorum, else the village's)."""
    if water_point_id is None:
        return village.quorum
    point = repo.get_water_point(village.id, water_point_id)
    return (point.quorum if point else None) or village.quorum


def route_operator(
    repo: Repository,
    village_id: str,
    water_point_id: str | None,
    *,
    skip: Iterable[str] = (),
) -> Operator | None:
    """Who a complaint goes to: the point's operators, then the Nal Jal Mitra, then the sarpanch."""
    skipped = set(skip)
    chain: list[Operator] = []
    if water_point_id:
        point = repo.get_water_point(village_id, water_point_id)
        for oid in point.operator_ids if point else []:
            operator = repo.get_operator(oid)
            if operator is not None:
                chain.append(operator)
    operators = repo.list_operators_for_village(village_id)
    for role in (OperatorRole.NAL_JAL_MITRA, OperatorRole.SARPANCH):
        chain.extend(o for o in operators if o.role is role)
    return next((o for o in chain if o.id not in skipped), None)


def not_mine(ticket: Ticket) -> list[str]:
    """Operators who said a complaint is not theirs (operator call key 5), oldest first."""
    return [
        str(e.detail["not_mine"])
        for e in ticket.events
        if e.kind == TicketEventKind.NOTE and e.detail.get("not_mine")
    ]


# --- complaints ----------------------------------------------------------------------------------


def report_problem(
    repo: Repository,
    village: Village,
    household: Household,
    reason: TicketReason,
    *,
    origin: TicketOrigin,
    issue: NoteIssue | None = None,
) -> Ticket:
    """Open a complaint for the household's water point, or join the one already open."""
    wp = household.water_point_id
    quorum = point_quorum(repo, village, wp)
    for _ in range(MAX_SAVE_ATTEMPTS):
        current = repo.get_open_ticket(village.id, wp, reason)
        if current is not None:
            return _join(repo, current, household.id, quorum, issue)
        now = config.now()
        ticket = new_ticket(
            village.id,
            reason,
            now,
            ticket_id=new_id("tkt", at=now),
            water_point_id=wp,
            origin=origin,
            reporters=[household.id],
            quorum=report_quorum(quorum, 1),
            number=repo.next_ticket_number(village.id),
        ).model_copy(update={"issue": issue})
        stored = repo.open_ticket_if_none(ticket)
        if stored is not None:
            _opened(village, stored)
            start_ticket_flow(stored)
            return stored
    raise ConflictError(f"could not open or join a {reason} ticket for {village.id}")


def open_reconciled_tickets(
    repo: Repository, village: Village, status: DayStatus, checkins: Sequence[CheckIn]
) -> list[Ticket]:
    """Open a ticket for every water point whose day is NO_SUPPLY or DIRTY (none already open)."""
    open_keys = [(t.water_point_id, t.reason) for t in repo.list_open_tickets(village.id)]
    opened: list[Ticket] = []
    # Same evidence as the reconciler: a later VERIFY answer must not hide a DAILY report.
    latest = latest_answers(
        c for c in checkins if c.date == status.date and c.purpose in DAY_PURPOSES
    )
    for wp, reason in tickets_to_open(status, open_keys):
        reporters = [
            c.household_id for c in latest if c.water_point_id == wp and reported(c, reason)
        ]
        now = config.now()
        ticket = new_ticket(
            village.id,
            reason,
            now,
            ticket_id=new_id("tkt", at=now),
            water_point_id=wp,
            origin=TicketOrigin.RECONCILE,
            reporters=reporters,
            quorum=point_quorum(repo, village, wp),
            number=repo.next_ticket_number(village.id),
        )
        stored = repo.open_ticket_if_none(ticket)
        if stored is not None:
            _opened(village, stored)
            opened.append(stored)
    return opened


def reported(checkin: CheckIn, reason: TicketReason) -> bool:
    """Did this answer report the ticket's problem? (DIRTY: unclean water; else no or partial.)"""
    if not is_answered(checkin):
        return False
    if reason is TicketReason.DIRTY:
        return checkin.clean == CleanAnswer.NO
    return checkin.water in (WaterAnswer.NO, WaterAnswer.PARTIAL)


def start_ticket_flow(ticket: Ticket) -> bool:
    """Start TicketFlow for an already-opened ticket (execution named after it: idempotent)."""
    arn = config.settings().ticket_sfn_arn
    if not arn:
        logger.warning("no ticket workflow configured", extra={"ticket_id": ticket.id})
        return False
    payload = {
        "village_id": ticket.village_id,
        "reason": ticket.reason.value,
        "ticket_id": ticket.id,
        "date": today_ist(ticket.opened_at).isoformat(),
    }
    try:
        config.client("stepfunctions").start_execution(
            stateMachineArn=arn, name=ticket.id, input=dumps(payload)
        )
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ExecutionAlreadyExists":
            return False
        raise
    return True


def update_ticket(
    repo: Repository,
    ticket_id: str,
    mutate: Callable[[Ticket], Ticket],
    detail: dict[str, object],
    actor: str,
) -> Ticket | Denied:
    """Add a NOTE event and apply a field change in one save, under the optimistic lock."""
    for attempt in range(1, MAX_SAVE_ATTEMPTS + 1):
        ticket = repo.get_ticket_by_id(ticket_id)
        if ticket is None:
            return Denied(f"ticket {ticket_id} not found")
        at = max(config.now(), ticket.updated_at + _TICK)
        noted = transition(ticket, TicketEventKind.NOTE, actor, at, detail)
        if isinstance(noted, Denied):
            return noted
        try:
            return repo.save_ticket(mutate(noted), expected_updated_at=ticket.updated_at)
        except ConflictError:
            if attempt == MAX_SAVE_ATTEMPTS:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def _join(
    repo: Repository, ticket: Ticket, household_id: str, quorum: int, issue: NoteIssue | None
) -> Ticket:
    if household_id in ticket.reporters and issue is None:
        return ticket

    def mutate(t: Ticket) -> Ticket:
        joined = with_reporter(t, household_id, quorum)
        return joined.model_copy(update={"issue": issue}) if issue and not t.issue else joined

    result = update_ticket(
        repo,
        ticket.id,
        mutate,
        {"note": "another_report", "household_id": household_id},
        "resident:missed-call",
    )
    if isinstance(result, Denied):
        logger.warning("could not join ticket", extra={"reason": result.reason})
        return ticket
    activity(
        "ticket",
        ticket.village_id,
        f"Another family reported the same problem (complaint #{ticket.number})",
        f"एक और परिवार ने यही शिकायत की (शिकायत क्रमांक {ticket.number})",
    )
    return result


def _opened(village: Village, ticket: Ticket) -> None:
    count("TicketsOpened", origin=ticket.origin.value)
    activity(
        "ticket",
        village.id,
        f"Complaint #{ticket.number} opened for {village.name}: {ticket.reason} "
        f"({ticket.origin.value})",
        f"{village.name_hi or village.name}: शिकायत क्रमांक {ticket.number} दर्ज "
        f"({REASON_HI[ticket.reason]})",
    )


# --- what residents hear ------------------------------------------------------------------------


def status_text_hi(repo: Repository, village: Village, day: date) -> str:
    """Today's status per water point and the open complaints, as one short spoken paragraph."""
    status = repo.get_day_status(village.id, day)
    names = {p.id: p.name_hi or p.name for p in repo.list_water_points(village.id)}
    parts = [f"Aaj {village.name_hi or village.name} mein."]
    if status is None or not status.points:
        parts.append("Aaj ke liye abhi poori jaankari nahi hai.")
    else:
        for point in status.points:
            label = names.get(point.water_point_id or "", "gaon")
            parts.append(f"{label}: {STATUS_HI[point.status]}.")
    open_now = repo.list_open_tickets(village.id)
    if open_now:
        parts.append(f"Khuli shikayatein: {len(open_now)}.")
        oldest = open_now[0]
        days_open = (config.now() - oldest.opened_at).days
        if days_open >= 1:
            parts.append(f"Sabse purani shikayat {days_open} din se khuli hai.")
    else:
        parts.append("Abhi koi shikayat khuli nahi hai.")
    return " ".join(parts)
