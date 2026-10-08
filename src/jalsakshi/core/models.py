"""Shared domain types. This file is the contract between modules (docs/ARCHITECTURE.md §3).

Pure pydantic: no AWS or I/O imports. Change it only with a matching ARCHITECTURE.md edit.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Freshness(StrEnum):
    LIVE = "live"
    DAILY = "daily"
    ANNUAL = "annual"
    MODEL = "model"
    SIMULATED = "simulated"
    REPLAY = "replay"


class SourceTag(BaseModel):
    """Where a number came from and how fresh it is. Shown next to every number in the UI."""

    source: str
    observed_at: datetime | None = None
    fetched_at: datetime
    freshness: Freshness
    url: str | None = None


class OperatorRole(StrEnum):
    NAL_JAL_MITRA = "NAL_JAL_MITRA"
    SARPANCH = "SARPANCH"
    PANCHAYAT_SECRETARY = "PANCHAYAT_SECRETARY"
    PHED_AE_SIM = "PHED_AE_SIM"
    PHED_EE_SIM = "PHED_EE_SIM"


class Purpose(StrEnum):
    DAILY = "DAILY"
    VERIFY = "VERIFY"
    OPERATOR = "OPERATOR"


class CallOutcome(StrEnum):
    ANSWERED = "ANSWERED"
    UNREACHABLE = "UNREACHABLE"
    DECLINED = "DECLINED"


class WaterAnswer(StrEnum):
    YES = "YES"
    NO = "NO"
    PARTIAL = "PARTIAL"


class CleanAnswer(StrEnum):
    YES = "YES"
    NO = "NO"


class CapturedVia(StrEnum):
    DTMF = "DTMF"
    SPEECH = "SPEECH"
    SIMULATOR = "SIMULATOR"


class DayStatusValue(StrEnum):
    SUPPLIED = "SUPPLIED"
    PARTIAL = "PARTIAL"
    NO_SUPPLY = "NO_SUPPLY"
    DIRTY = "DIRTY"
    UNVERIFIED = "UNVERIFIED"


class TicketReason(StrEnum):
    NO_SUPPLY = "NO_SUPPLY"
    DIRTY = "DIRTY"


class TicketState(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    OPERATOR_REPORTED_FIXED = "OPERATOR_REPORTED_FIXED"
    VERIFYING = "VERIFYING"
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    REOPENED = "REOPENED"
    ESCALATED = "ESCALATED"


class Consent(BaseModel):
    given_at: datetime
    channel: str = Field(pattern="^(voice|in_person)$")
    evidence_ref: str | None = None


class Village(BaseModel):
    id: str
    name: str
    block: str
    district: str
    imis_village_code: str | None = None
    claimed_hgj: bool | None = None
    hgj_certified: bool | None = None
    claimed_source: SourceTag | None = None
    checkin_local_time: str = Field(default="10:30", pattern=r"^\d{2}:\d{2}$")
    quorum: int = Field(default=2, ge=1)
    active: bool = True


class Household(BaseModel):
    id: str
    village_id: str
    phone_e164: str = Field(pattern=r"^\+\d{10,15}$")
    display_name: str | None = None
    language: str = "hi"
    call_window: str = Field(default="09:00-20:00", pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    consent: Consent | None = None
    active: bool = True

    @property
    def consent_given(self) -> bool:
        return self.consent is not None


class Operator(BaseModel):
    id: str
    role: OperatorRole
    phone_e164: str = Field(pattern=r"^\+\d{10,15}$")
    display_name: str | None = None
    village_ids: list[str] = Field(default_factory=list)


class CheckIn(BaseModel):
    village_id: str
    date: date
    household_id: str
    attempt: int = Field(default=1, ge=1)
    call_id: str
    purpose: Purpose = Purpose.DAILY
    outcome: CallOutcome
    water: WaterAnswer | None = None
    hours: int | None = Field(default=None, ge=0, le=24)
    clean: CleanAnswer | None = None
    note_transcript: str | None = None
    note_issue: str | None = None
    captured_via: CapturedVia = CapturedVia.DTMF
    captured_at: datetime


class DayCounts(BaseModel):
    answered: int = 0
    yes: int = 0
    no: int = 0
    partial: int = 0
    dirty: int = 0
    unreachable: int = 0


class DayStatus(BaseModel):
    village_id: str
    date: date
    status: DayStatusValue
    counts: DayCounts
    rule_version: str
    computed_at: datetime


class TicketEvent(BaseModel):
    at: datetime
    actor: str
    kind: str
    from_state: TicketState | None = None
    to_state: TicketState | None = None
    detail: dict = Field(default_factory=dict)


class Ticket(BaseModel):
    id: str
    village_id: str
    reason: TicketReason
    state: TicketState = TicketState.OPEN
    opened_at: datetime
    updated_at: datetime
    events: list[TicketEvent] = Field(default_factory=list)
