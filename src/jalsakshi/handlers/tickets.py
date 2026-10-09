"""Ticket glue: apply one state-machine event under the store's optimistic lock, and the
fix-wait token that lets a console click or an operator call resume the TicketFlow execution.

Whether an event is allowed is decided only by ``core.tickets.transition``; this module loads,
saves (retrying when another writer won the race) and reports.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any, Final

from jalsakshi.core.clock import today_ist
from jalsakshi.core.models import (
    CheckIn,
    CleanAnswer,
    Household,
    Purpose,
    Ticket,
    TicketReason,
    Village,
    WaterAnswer,
)
from jalsakshi.core.reconcile import DAY_PURPOSES, is_answered, latest_answers
from jalsakshi.core.tickets import Denied, TicketEventKind, transition
from jalsakshi.handlers import config, sfn
from jalsakshi.handlers.common import activity, logger
from jalsakshi.store import ConflictError, NotFoundError, Repository
from jalsakshi.store.table import iso_ts

MAX_SAVE_ATTEMPTS: Final = 3
WAIT_TTL_DAYS: Final = 30
MAX_VERIFY_DAYS: Final = 14
_TICK: Final = timedelta(microseconds=1)

_FEED: Final[dict[TicketEventKind, tuple[str, str]]] = {
    TicketEventKind.NOTIFIED: (
        "Nal Jal Mitra notified about ticket {tid}",
        "नल जल मित्र को शिकायत {tid} की सूचना दी गई",
    ),
    TicketEventKind.OPERATOR_FIXED: (
        "Operator reported ticket {tid} fixed; households will be called to confirm",
        "मित्र ने कहा शिकायत {tid} ठीक हो गई; घरों से पुष्टि होगी",
    ),
    TicketEventKind.VERIFY_STARTED: (
        "Verification calls started for ticket {tid}",
        "शिकायत {tid}: पुष्टि के लिए घरों को कॉल शुरू",
    ),
    TicketEventKind.VERIFIED_OK: (
        "Ticket {tid} closed: households confirmed water is back",
        "शिकायत {tid} बंद: घरों ने पानी आने की पुष्टि की",
    ),
    TicketEventKind.VERIFY_FAILED: (
        "Ticket {tid} reopened: a household still reports a problem",
        "शिकायत {tid} फिर खुली: एक घर ने कहा समस्या अभी है",
    ),
    TicketEventKind.ESCALATED: (
        "Ticket {tid} escalated to PHED (simulated)",
        "शिकायत {tid} PHED को भेजी गई (सिम्युलेटेड)",
    ),
}


def wait_key(ticket_id: str) -> str:
    """Call-session id that holds the TicketFlow task token waiting for a fix."""
    return f"wait-{ticket_id}"


def load_ticket(repo: Repository, ticket_id: str) -> Ticket:
    """The ticket, or NotFoundError."""
    ticket = repo.get_ticket_by_id(ticket_id)
    if ticket is None:
        raise NotFoundError(f"ticket {ticket_id!r} not found")
    return ticket


def apply_event(
    repo: Repository,
    ticket_id: str,
    kind: TicketEventKind,
    actor: str,
    detail: Mapping[str, Any] | None = None,
) -> Ticket | Denied:
    """Apply one event and save it; Denied when the state machine refuses it."""
    for attempt in range(1, MAX_SAVE_ATTEMPTS + 1):
        ticket = load_ticket(repo, ticket_id)
        at = max(config.now(), ticket.updated_at + _TICK)
        result = transition(ticket, kind, actor, at, detail)
        if isinstance(result, Denied):
            return result
        try:
            saved = repo.save_ticket(result, expected_updated_at=ticket.updated_at)
        except ConflictError:
            if attempt == MAX_SAVE_ATTEMPTS:
                raise
            logger.info("ticket changed meanwhile; retrying", extra={"ticket_id": ticket_id})
            continue
        _feed(saved, kind)
        return saved
    raise AssertionError("unreachable")  # pragma: no cover


def register_wait(repo: Repository, ticket_id: str, token: str, waiting_for: str) -> None:
    """Remember the task token of a TicketFlow step that waits for the operator's fix."""
    data = {"ticket_id": ticket_id, "waiting_for": waiting_for, "registered_at": _now_iso()}
    repo.put_call_session(wait_key(ticket_id), data, ttl_days=WAIT_TTL_DAYS)
    repo.set_task_token(wait_key(ticket_id), token)


def release_wait(repo: Repository, ticket_id: str, output: Mapping[str, Any]) -> bool:
    """Resume the TicketFlow step waiting on this ticket; False when nothing is waiting."""
    session = repo.get_call_session(wait_key(ticket_id))
    if session is None or not session.task_token:
        return False
    resumed = sfn.send_task_success(session.task_token, output)
    data = {**session.data, "released_at": _now_iso(), "resumed": resumed}
    repo.put_call_session(wait_key(ticket_id), data, ttl_days=WAIT_TTL_DAYS)
    return resumed


def report_fixed(
    repo: Repository, ticket_id: str, actor: str, via: str, operator_id: str | None = None
) -> Ticket | Denied:
    """The operator says it is fixed: OPERATOR_FIXED, then resume the workflow to verify."""
    detail = {"via": via, "operator_id": operator_id}
    result = apply_event(repo, ticket_id, TicketEventKind.OPERATOR_FIXED, actor, detail)
    if isinstance(result, Denied):
        return result
    resumed = release_wait(repo, ticket_id, {"fixed": True, "actor": actor, "via": via})
    logger.info("operator fix reported", extra={"ticket_id": ticket_id, "resumed": resumed})
    return result


def verify_targets(
    village: Village,
    ticket: Ticket,
    households: list[Household],
    daily: list[CheckIn],
    quorum: int | None = None,
) -> list[Household]:
    """Households to call back: those that reported the problem, else everyone on the point.

    ``daily`` holds the DAILY and REPORT check-ins of the day the ticket opened; the ticket's own
    ``reporters`` (missed calls, voice notes) always count. When fewer reporters than the quorum
    exist, every active household on the ticket's water point (or the whole village) is called,
    so a quorum stays reachable.
    """
    needed = quorum or ticket.quorum or village.quorum
    day = [
        c
        for c in daily
        if c.purpose in DAY_PURPOSES
        and (ticket.water_point_id is None or c.water_point_id == ticket.water_point_id)
    ]
    reporters = {c.household_id for c in latest_answers(day) if _reported(c, ticket.reason)}
    reporters.update(ticket.reporters)
    chosen = [h for h in households if h.id in reporters]
    if len(chosen) >= needed:
        return chosen
    on_point = [
        h
        for h in households
        if ticket.water_point_id is None or h.water_point_id == ticket.water_point_id
    ]
    return on_point or households


def ticket_day(ticket: Ticket) -> date:
    """IST calendar day on which the ticket opened."""
    return today_ist(ticket.opened_at)


def verify_started_at(ticket: Ticket) -> datetime | None:
    """Time of the latest VERIFY_STARTED event (start of the current verification round)."""
    starts = [e.at for e in ticket.events if e.kind == TicketEventKind.VERIFY_STARTED]
    return max(starts, default=None)


def verify_checkins(repo: Repository, ticket: Ticket, today: date) -> list[CheckIn]:
    """VERIFY check-ins of the ticket's village since its latest verification round began."""
    since = verify_started_at(ticket)
    if since is None:
        return []
    first = max(today_ist(since), today - timedelta(days=MAX_VERIFY_DAYS - 1))
    days = [first + timedelta(days=n) for n in range((today - first).days + 1)]
    return [c for day in days for c in repo.list_checkins(ticket.village_id, day, Purpose.VERIFY)]


def _reported(checkin: CheckIn, reason: TicketReason) -> bool:
    if not is_answered(checkin) or checkin.purpose not in (Purpose.DAILY, Purpose.REPORT):
        return False
    if reason is TicketReason.DIRTY:
        return checkin.clean == CleanAnswer.NO
    return checkin.water in (WaterAnswer.NO, WaterAnswer.PARTIAL)


def _feed(ticket: Ticket, kind: TicketEventKind) -> None:
    texts = _FEED.get(kind)
    if texts is not None:
        text_en, text_hi = (text.format(tid=ticket.id) for text in texts)
        activity("ticket", ticket.village_id, text_en, text_hi)


def _now_iso() -> str:
    return iso_ts(config.now())
