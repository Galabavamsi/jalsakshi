"""Panchayat announcements (ARCHITECTURE.md §15.8): draft, sarpanch approval, phone delivery.

Cedar decides who may approve (``ApproveBroadcast``: sarpanch only) and whether an announcement
may go out (``SendBroadcast``: approved, at most two a week); every recipient call is still a
``PlaceCall`` check (consent, calling hours). Delivery counts come back from the calls.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from jalsakshi.core.clock import today_ist
from jalsakshi.core.ids import new_id
from jalsakshi.core.models import (
    Broadcast,
    BroadcastKind,
    BroadcastState,
    Household,
    OperatorRole,
    Purpose,
)
from jalsakshi.handlers import config
from jalsakshi.handlers.common import PolicyDeniedError, activity, logger, record_denial
from jalsakshi.policy import (
    can_approve_broadcast,
    can_send_broadcast,
)
from jalsakshi.store import NotFoundError, Repository
from jalsakshi.store.errors import ConflictError

WEEK: Final = timedelta(days=7)


def draft(
    repo: Repository,
    village_id: str,
    kind: BroadcastKind,
    text_hi: str,
    created_by: str,
    water_point_id: str | None = None,
) -> Broadcast:
    """Save a new DRAFT announcement."""
    now = config.now()
    broadcast = Broadcast(
        id=new_id("bc", at=now),
        village_id=village_id,
        water_point_id=water_point_id,
        kind=kind,
        text_hi=text_hi.strip(),
        created_by=created_by,
        created_at=now,
    )
    repo.put_broadcast(broadcast)
    activity(
        "broadcast",
        village_id,
        f"Announcement drafted ({kind.value}); waiting for the sarpanch",
        "घोषणा का मसौदा बना; सरपंच की मंज़ूरी बाकी",
    )
    return broadcast


def load(repo: Repository, village_id: str, broadcast_id: str) -> Broadcast:
    broadcast = repo.get_broadcast(village_id, broadcast_id)
    if broadcast is None:
        raise NotFoundError(f"announcement {broadcast_id!r} not found")
    return broadcast


def approve(repo: Repository, broadcast: Broadcast, role: OperatorRole, actor: str) -> Broadcast:
    """Sarpanch approval (Cedar ApproveBroadcast); raises PolicyDeniedError otherwise."""
    if broadcast.state is not BroadcastState.DRAFT:
        raise ConflictError(f"announcement is {broadcast.state}, not DRAFT")
    decision = can_approve_broadcast(role, broadcast)
    if not decision.allowed:
        record_denial(decision, broadcast.village_id, f"approving announcement {broadcast.id}")
        raise PolicyDeniedError(decision)
    approved = broadcast.model_copy(
        update={
            "state": BroadcastState.APPROVED,
            "approved_by": actor,
            "approved_at": config.now(),
        }
    )
    repo.put_broadcast(approved)
    _prerender(approved.text_hi)
    activity(
        "broadcast",
        broadcast.village_id,
        "The sarpanch approved an announcement",
        "सरपंच ने घोषणा को मंज़ूरी दी",
    )
    return approved


def cancel(repo: Repository, broadcast: Broadcast) -> Broadcast:
    if broadcast.state is BroadcastState.SENT:
        raise ConflictError("a sent announcement cannot be cancelled")
    cancelled = broadcast.model_copy(update={"state": BroadcastState.CANCELLED})
    repo.put_broadcast(cancelled)
    return cancelled


def sent_last_week(repo: Repository, village_id: str) -> int:
    since = config.now() - WEEK
    return sum(
        1
        for b in repo.list_broadcasts(village_id)
        if b.state is BroadcastState.SENT and b.sent_at is not None and b.sent_at >= since
    )


def check_send(repo: Repository, broadcast: Broadcast) -> None:
    """Cedar SendBroadcast, then calling hours; raises PolicyDeniedError when it may not go out.

    Sending outside calling hours would mark it SENT (using one of the week's two) while every
    recipient call is refused, so the hours are checked first, with Cedar's PlaceCall rule.
    """
    decision = can_send_broadcast(broadcast, sent_last_week(repo, broadcast.village_id))
    if not decision.allowed:
        record_denial(decision, broadcast.village_id, f"sending announcement {broadcast.id}")
        raise PolicyDeniedError(decision)


def recipients(repo: Repository, broadcast: Broadcast) -> list[Household]:
    """Active, consenting households on the target point (or the whole village)."""
    households = repo.list_households(broadcast.village_id, active_only=True)
    return [
        h
        for h in households
        if h.consent_given
        and (broadcast.water_point_id is None or h.water_point_id == broadcast.water_point_id)
    ]


def send(repo: Repository, broadcast: Broadcast) -> Broadcast:
    """Mark SENT and dial every recipient (each call policy-checked); returns the stored copy."""
    from jalsakshi.handlers import outbound

    check_send(repo, broadcast)
    targets = recipients(repo, broadcast)
    sent = broadcast.model_copy(
        update={
            "state": BroadcastState.SENT,
            "sent_at": config.now(),
            "recipients": len(targets),
        }
    )
    repo.put_broadcast(sent)
    placed = 0
    for household in targets:
        if outbound.call_household(
            repo, household, Purpose.BROADCAST, message=sent.text_hi, broadcast_id=sent.id
        ):
            placed += 1
    activity(
        "broadcast",
        broadcast.village_id,
        f"Announcement sent: {placed} of {len(targets)} calls placed",
        f"घोषणा भेजी गई: {len(targets)} में से {placed} कॉल लगीं",
    )
    return sent


def record_delivery(repo: Repository, village_id: str, broadcast_id: str, *, heard: bool) -> None:
    """One recipient picked up (and maybe pressed 1): atomic add, safe for concurrent calls."""
    repo.add_broadcast_delivery(village_id, broadcast_id, delivered=1, heard=1 if heard else 0)


def _prerender(text: str) -> None:
    """Render the announcement audio now, so the call itself never waits for TTS."""
    from jalsakshi.handlers import speech

    try:
        tts = speech.runtime_tts()
        if tts is not None:
            tts.ensure_all(text)
    except Exception as exc:  # the call will try again; approval must not fail on audio
        logger.warning("announcement audio not pre-rendered", extra={"error": str(exc)})


def today_label() -> str:
    return today_ist(config.now()).isoformat()
