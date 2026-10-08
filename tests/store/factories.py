"""Builders for domain objects used by the store tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from jalsakshi.core.models import (
    CallOutcome,
    CheckIn,
    Consent,
    DayCounts,
    DayStatus,
    DayStatusValue,
    Freshness,
    Household,
    Operator,
    OperatorRole,
    Purpose,
    SourceTag,
    Ticket,
    TicketEvent,
    TicketReason,
    TicketState,
    Village,
    WaterAnswer,
)

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)  # 10:30 IST
DAY = date(2026, 10, 9)
TABLE = "jalsakshi-test"


class Clock:
    """Settable clock passed to Repository(clock=...)."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def village(vid: str = "v1", **overrides: Any) -> Village:
    fields: dict[str, Any] = {
        "id": vid,
        "name": f"Village {vid}",
        "block": "Dhamdha",
        "district": "Durg",
        "claimed_hgj": True,
        "claimed_source": SourceTag(
            source="JJM IMIS",
            observed_at=datetime(2026, 9, 30, tzinfo=UTC),
            fetched_at=NOW,
            freshness=Freshness.DAILY,
            url="https://ejalshakti.gov.in/",
        ),
    }
    return Village(**(fields | overrides))


def household(hid: str = "h1", vid: str = "v1", **overrides: Any) -> Household:
    fields: dict[str, Any] = {
        "id": hid,
        "village_id": vid,
        "phone_e164": "+919800000001",
        "display_name": "सुनीता",
        "consent": Consent(given_at=NOW, channel="in_person", evidence_ref="form-1"),
    }
    return Household(**(fields | overrides))


def operator(oid: str = "op1", villages: tuple[str, ...] = ("v1",), **overrides: Any) -> Operator:
    fields: dict[str, Any] = {
        "id": oid,
        "role": OperatorRole.NAL_JAL_MITRA,
        "phone_e164": "+919800000099",
        "village_ids": list(villages),
    }
    return Operator(**(fields | overrides))


def checkin(
    hid: str = "h1",
    *,
    vid: str = "v1",
    day: date = DAY,
    attempt: int = 1,
    purpose: Purpose = Purpose.DAILY,
    **overrides: Any,
) -> CheckIn:
    fields: dict[str, Any] = {
        "village_id": vid,
        "date": day,
        "household_id": hid,
        "attempt": attempt,
        "call_id": f"call-{hid}-{attempt}-{purpose}",
        "purpose": purpose,
        "outcome": CallOutcome.ANSWERED,
        "water": WaterAnswer.YES,
        "hours": 2,
        "captured_at": NOW,
    }
    return CheckIn(**(fields | overrides))


def day_status(
    day: date = DAY, vid: str = "v1", status: DayStatusValue = DayStatusValue.SUPPLIED
) -> DayStatus:
    return DayStatus(
        village_id=vid,
        date=day,
        status=status,
        counts=DayCounts(answered=3, yes=3),
        rule_version="r1",
        computed_at=NOW,
    )


def ticket(tid: str = "t1", vid: str = "v1", opened_at: datetime = NOW) -> Ticket:
    opened = TicketEvent(
        at=opened_at,
        actor="reconciler",
        kind="opened",
        to_state=TicketState.OPEN,
        detail={"day": DAY.isoformat(), "no": 3, "share": 0.75},
    )
    return Ticket(
        id=tid,
        village_id=vid,
        reason=TicketReason.NO_SUPPLY,
        opened_at=opened_at,
        updated_at=opened_at,
        events=[opened],
    )


def advance(tk: Ticket, to: TicketState, at: datetime, actor: str = "system") -> Ticket:
    """Return `tk` moved to `to` at `at`, with one appended event."""
    event = TicketEvent(at=at, actor=actor, kind="transition", from_state=tk.state, to_state=to)
    return tk.model_copy(update={"state": to, "updated_at": at, "events": [*tk.events, event]})
