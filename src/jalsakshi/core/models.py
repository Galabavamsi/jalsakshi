"""Shared domain types. This file is the contract between modules (docs/ARCHITECTURE.md §3, §15).

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
    HANDPUMP_MECHANIC = "HANDPUMP_MECHANIC"


class Purpose(StrEnum):
    DAILY = "DAILY"
    VERIFY = "VERIFY"
    OPERATOR = "OPERATOR"
    REGISTER = "REGISTER"
    REPORT = "REPORT"
    BROADCAST = "BROADCAST"
    SUMMARY = "SUMMARY"
    ALERT = "ALERT"


CHECKIN_PURPOSES: frozenset[Purpose] = frozenset({Purpose.DAILY, Purpose.VERIFY, Purpose.REPORT})
"""Purposes whose calls produce a CheckIn (the others register people or deliver a message)."""


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


class Fallback(StrEnum):
    """Where a family got drinking water on a day its own source failed (§15.1)."""

    OTHER_SOURCE = "OTHER_SOURCE"
    BOUGHT = "BOUGHT"
    NONE = "NONE"


class WaterPointKind(StrEnum):
    PIPED = "PIPED"
    HANDPUMP = "HANDPUMP"
    BOREWELL = "BOREWELL"
    TANKER = "TANKER"
    OTHER = "OTHER"


class AccessKind(StrEnum):
    """How a family draws its drinking water (the water point is what breaks and gets fixed)."""

    HOUSE_TAP = "HOUSE_TAP"
    STANDPOST = "STANDPOST"
    HANDPUMP = "HANDPUMP"
    BOREWELL = "BOREWELL"
    TANKER = "TANKER"
    OTHER = "OTHER"


ACCESS_POINT_KIND: dict[AccessKind, WaterPointKind] = {
    AccessKind.HOUSE_TAP: WaterPointKind.PIPED,
    AccessKind.STANDPOST: WaterPointKind.PIPED,
    AccessKind.HANDPUMP: WaterPointKind.HANDPUMP,
    AccessKind.BOREWELL: WaterPointKind.BOREWELL,
    AccessKind.TANKER: WaterPointKind.TANKER,
    AccessKind.OTHER: WaterPointKind.OTHER,
}


class ConsentStatus(StrEnum):
    NONE = "NONE"
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ConsentAction(StrEnum):
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    MINOR = "MINOR"


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
    LOW_PRESSURE = "LOW_PRESSURE"
    LEAK = "LEAK"
    BROKEN = "BROKEN"
    OTHER = "OTHER"


class TicketOrigin(StrEnum):
    RECONCILE = "reconcile"
    REPORT = "report"
    VOICE_NOTE = "voice_note"
    CONSOLE = "console"


class BlockerCode(StrEnum):
    """Why the operator says a problem is not fixed yet (operator call keys 2-7, §15.7).

    ``OTHER``: the operator explains in their own words (a voice note). ``NEEDS_PANCHAYAT``: the
    operator cannot solve it alone; the complaint goes to the Sarpanch (who gets a call).
    """

    PARTS_NEEDED = "PARTS_NEEDED"
    NO_POWER = "NO_POWER"
    PIPE_BROKEN = "PIPE_BROKEN"
    NOT_MINE = "NOT_MINE"
    OTHER = "OTHER"
    NEEDS_PANCHAYAT = "NEEDS_PANCHAYAT"


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
    channel: str = Field(pattern="^(voice|in_person|ivr_keypad|console)$")
    evidence_ref: str | None = None
    notice_version: str | None = None
    call_id: str | None = None


class GeoPoint(BaseModel):
    """A location with where it came from (e.g. "GeoNames, approximate", "field GPS")."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    source: str
    accuracy_m: int | None = Field(default=None, ge=0)


class Village(BaseModel):
    id: str
    name: str
    block: str
    district: str
    name_hi: str | None = None
    state: str | None = None
    lgd_code: str | None = None
    census_code: str | None = None
    gram_panchayat: str | None = None
    gp_lgd_code: str | None = None
    census_households: int | None = Field(default=None, ge=0)
    census_population: int | None = Field(default=None, ge=0)
    census_source: SourceTag | None = None
    location: GeoPoint | None = None
    inbound: bool = False
    imis_village_code: str | None = None
    claimed_hgj: bool | None = None
    hgj_certified: bool | None = None
    claimed_source: SourceTag | None = None
    checkin_local_time: str = Field(default="10:30", pattern=r"^\d{2}:\d{2}$")
    quorum: int = Field(default=2, ge=1)
    languages: list[str] = Field(default_factory=lambda: ["hi"])
    active: bool = True


class WaterPoint(BaseModel):
    """A drinking-water source the Panchayat looks after: what breaks and gets repaired."""

    id: str
    village_id: str
    kind: WaterPointKind
    name: str
    name_hi: str | None = None
    hamlet: str | None = None
    location: GeoPoint | None = None
    supply_window: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    operator_ids: list[str] = Field(default_factory=list)
    quorum: int | None = Field(default=None, ge=1)
    provisional: bool = False
    active: bool = True


class Household(BaseModel):
    id: str
    village_id: str
    phone_e164: str = Field(pattern=r"^\+\d{10,15}$")
    display_name: str | None = None
    language: str = "hi"
    call_window: str = Field(default="09:00-20:00", pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    consent: Consent | None = None
    consent_status: ConsentStatus | None = None
    access: AccessKind | None = None
    water_point_id: str | None = None
    hamlet: str | None = None
    registered_via: str = Field(default="seed", pattern="^(seed|ivr|console)$")
    active: bool = True

    @property
    def consent_given(self) -> bool:
        return self.effective_consent is ConsentStatus.GRANTED

    @property
    def effective_consent(self) -> ConsentStatus:
        """``consent_status``, or GRANTED/NONE from ``consent`` for records written before v2."""
        if self.consent_status is not None:
            return self.consent_status
        return ConsentStatus.GRANTED if self.consent is not None else ConsentStatus.NONE


class ConsentEvent(BaseModel):
    """One entry of the append-only consent ledger (§15.3). Never updated or deleted."""

    village_id: str
    household_id: str
    phone_masked: str
    action: ConsentAction
    notice_version: str
    notice_sha256: str
    channel: str = Field(pattern="^(ivr_keypad|in_person|console)$")
    call_id: str | None = None
    digits: str | None = None
    at: datetime


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
    fallback: Fallback | None = None
    water_point_id: str | None = None
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


class PointStatus(BaseModel):
    """One water point's status for a day (``water_point_id`` None = households with no point)."""

    water_point_id: str | None = None
    status: DayStatusValue
    counts: DayCounts


class DayStatus(BaseModel):
    village_id: str
    date: date
    status: DayStatusValue
    counts: DayCounts
    rule_version: str
    computed_at: datetime
    points: list[PointStatus] = Field(default_factory=list)


class TicketEvent(BaseModel):
    at: datetime
    actor: str
    kind: str
    from_state: TicketState | None = None
    to_state: TicketState | None = None
    detail: dict = Field(default_factory=dict)


class NoteIssue(BaseModel):
    """What the agent understood from a resident's voice note (§15.6). Advisory only."""

    issue: TicketReason
    summary_hi: str
    summary_en: str
    transcript: str
    location_hint: str | None = None
    days_affected: int | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    model_id: str | None = None


class Ticket(BaseModel):
    id: str
    village_id: str
    reason: TicketReason
    state: TicketState = TicketState.OPEN
    opened_at: datetime
    updated_at: datetime
    events: list[TicketEvent] = Field(default_factory=list)
    number: int | None = Field(default=None, ge=1)
    water_point_id: str | None = None
    origin: TicketOrigin = TicketOrigin.RECONCILE
    reporters: list[str] = Field(default_factory=list)
    quorum: int | None = Field(default=None, ge=1)
    issue: NoteIssue | None = None
    blocker: BlockerCode | None = None


class BroadcastKind(StrEnum):
    SUPPLY_CHANGE = "SUPPLY_CHANGE"
    BOIL_WATER = "BOIL_WATER"
    REPAIR_DONE = "REPAIR_DONE"
    MEETING = "MEETING"
    CUSTOM = "CUSTOM"


class BroadcastState(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class Broadcast(BaseModel):
    """A Panchayat announcement played to households by phone, only after the sarpanch approves."""

    id: str
    village_id: str
    water_point_id: str | None = None
    kind: BroadcastKind
    text_hi: str = Field(min_length=1, max_length=400)
    state: BroadcastState = BroadcastState.DRAFT
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    sent_at: datetime | None = None
    recipients: int = Field(default=0, ge=0)
    delivered: int = Field(default=0, ge=0)
    heard: int = Field(default=0, ge=0)


class QualityMethod(StrEnum):
    FTK = "FTK"
    LAB = "LAB"


class QualityResult(StrEnum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"


class QualityTest(BaseModel):
    """A water-quality test of one water point (field test kit or lab), entered by a person."""

    id: str
    village_id: str
    water_point_id: str | None = None
    tested_at: datetime
    method: QualityMethod
    result: QualityResult
    parameters: dict[str, str] = Field(default_factory=dict)
    entered_by: str
    note: str | None = None
