/**
 * Wire types for the JalSakshi API.
 *
 * Mirrors src/jalsakshi/core/models.py (ARCHITECTURE.md §3) and the HTTP contract in §13.
 * Pydantic serialises datetimes as ISO 8601 strings and None as null, so optional model
 * fields are typed `T | null` and marked optional to tolerate `exclude_none` responses.
 */

/** ISO 8601 date-time with offset, e.g. "2026-10-08T05:15:00Z". */
export type IsoDateTime = string;
/** Calendar date, "YYYY-MM-DD" (India Standard Time). */
export type IsoDate = string;

// ---------------------------------------------------------------- enums (models.py)

export const FRESHNESS = ['live', 'daily', 'annual', 'model', 'simulated', 'replay'] as const;
export type Freshness = (typeof FRESHNESS)[number];

export type OperatorRole =
  | 'NAL_JAL_MITRA'
  | 'SARPANCH'
  | 'PANCHAYAT_SECRETARY'
  | 'PHED_AE_SIM'
  | 'PHED_EE_SIM';

export type Purpose = 'DAILY' | 'VERIFY' | 'OPERATOR';
export type CallOutcome = 'ANSWERED' | 'UNREACHABLE' | 'DECLINED';
export type WaterAnswer = 'YES' | 'NO' | 'PARTIAL';
export type CleanAnswer = 'YES' | 'NO';
export type CapturedVia = 'DTMF' | 'SPEECH' | 'SIMULATOR';

export const DAY_STATUSES = ['SUPPLIED', 'PARTIAL', 'NO_SUPPLY', 'DIRTY', 'UNVERIFIED'] as const;
export type DayStatusValue = (typeof DAY_STATUSES)[number];

export type TicketReason = 'NO_SUPPLY' | 'DIRTY';

export const TICKET_STATES = [
  'OPEN',
  'ASSIGNED',
  'OPERATOR_REPORTED_FIXED',
  'VERIFYING',
  'CLOSED_VERIFIED',
  'REOPENED',
  'ESCALATED',
] as const;
export type TicketState = (typeof TICKET_STATES)[number];

// ---------------------------------------------------------------- models (models.py)

export interface SourceTag {
  source: string;
  observed_at?: IsoDateTime | null;
  fetched_at: IsoDateTime;
  freshness: Freshness;
  url?: string | null;
}

export interface Consent {
  given_at: IsoDateTime;
  channel: 'voice' | 'in_person';
  evidence_ref?: string | null;
}

export interface Village {
  id: string;
  name: string;
  block: string;
  district: string;
  imis_village_code?: string | null;
  claimed_hgj?: boolean | null;
  hgj_certified?: boolean | null;
  claimed_source?: SourceTag | null;
  /** Local (IST) time of the daily check-in, "HH:MM". */
  checkin_local_time: string;
  quorum: number;
  active: boolean;
}

export interface Household {
  id: string;
  village_id: string;
  phone_e164: string;
  display_name?: string | null;
  language: string;
  call_window: string;
  consent?: Consent | null;
  active: boolean;
}

/** Household as the console sees it: no raw phone, only `+91XXXXXX1234`. */
export type HouseholdMasked = Omit<Household, 'phone_e164'> & { phone_masked: string };

export interface Operator {
  id: string;
  role: OperatorRole;
  phone_e164: string;
  display_name?: string | null;
  village_ids: string[];
}

export interface CheckIn {
  village_id: string;
  date: IsoDate;
  household_id: string;
  attempt: number;
  call_id: string;
  purpose: Purpose;
  outcome: CallOutcome;
  water?: WaterAnswer | null;
  hours?: number | null;
  clean?: CleanAnswer | null;
  note_transcript?: string | null;
  note_issue?: string | null;
  captured_via: CapturedVia;
  captured_at: IsoDateTime;
}

/** Check-in as listed by the console API: household id and answers, phone masked. */
export type CheckInMasked = CheckIn & { phone_masked?: string | null };

export interface DayCounts {
  answered: number;
  yes: number;
  no: number;
  partial: number;
  dirty: number;
  unreachable: number;
}

export interface DayStatus {
  village_id: string;
  date: IsoDate;
  status: DayStatusValue;
  counts: DayCounts;
  rule_version: string;
  computed_at: IsoDateTime;
}

export interface TicketEvent {
  at: IsoDateTime;
  actor: string;
  kind: string;
  from_state?: TicketState | null;
  to_state?: TicketState | null;
  detail: Record<string, unknown>;
}

export interface Ticket {
  id: string;
  village_id: string;
  reason: TicketReason;
  state: TicketState;
  opened_at: IsoDateTime;
  updated_at: IsoDateTime;
  events: TicketEvent[];
}

// ---------------------------------------------------------------- §13 response shapes

export interface Observed7d {
  days: number;
  supplied: number;
  no_supply: number;
  partial: number;
  dirty: number;
  unverified: number;
  /** Where the tallies come from: `live` calls, or `simulated` when the web-phone simulator answered. */
  source?: SourceTag | null;
}

/** One row of GET /api/villages. */
export interface VillageSummary {
  village: Village;
  today?: DayStatus | null;
  open_ticket?: Ticket | null;
  observed_7d: Observed7d;
}

export interface GroundwaterContext {
  /** Stage of extraction, %; null when the assessment publishes none for the block. */
  stage_pct: number | null;
  category: string;
  source: SourceTag;
}

export interface SourcedValue {
  value: number;
  source: SourceTag;
}

export interface StateHgjContext {
  villages: number;
  reported: number;
  certified: number;
  source: SourceTag;
}

export interface VillageContext {
  groundwater?: GroundwaterContext | null;
  rain_7d_mm?: SourcedValue | null;
  state_hgj?: StateHgjContext | null;
}

/** GET /api/villages/{vid}. */
export interface VillageDetail {
  village: Village;
  households: HouseholdMasked[];
  operators: Operator[];
  context: VillageContext;
}

export interface RunCheckinResponse {
  execution_arn: string;
}

export interface TicketQuery {
  state?: TicketState;
  village_id?: string;
}

/** Body of a 403 from a Cedar-guarded action. */
export interface PolicyDenied {
  denied: true;
  policy_id: string;
  reason_hi: string;
  reason_en: string;
}

export type CloseResult = { ok: true; ticket: Ticket } | { ok: false; denied: PolicyDenied };

/** GET /api/villages/{vid}/brief. */
export interface Brief {
  markdown_hi: string;
  numbers: Record<string, number | string | null>;
  generated_by: 'agent' | 'template';
  sources: SourceTag[];
  generated_at: IsoDateTime;
  /** Bedrock model that wrote the text, or null for the template. */
  model_id?: string | null;
}

/** One entry of GET /api/activity. */
export interface ActivityItem {
  at: IsoDateTime;
  kind: string;
  village_id?: string | null;
  text_en: string;
  text_hi: string;
}

// ---------------------------------------------------------------- simulator (§13 Action)

/** A prompt the IVR speaks: catalog key, Hindi text, optional rendered audio. */
export interface PromptRef {
  prompt_key: string;
  text_hi: string;
  audio_url?: string | null;
}

export type PlayAction = { type: 'play' } & PromptRef;
export interface GetDigitsAction {
  type: 'get_digits';
  num_digits: number;
  timeout_s: number;
  prompts: PromptRef[];
}
export interface RecordAction {
  type: 'record';
  max_s: number;
}
export interface HangupAction {
  type: 'hangup';
}
export type Action = PlayAction | GetDigitsAction | RecordAction | HangupAction;

export interface SimStartRequest {
  household_id?: string;
  operator_id?: string;
  purpose: Purpose;
}

export interface SimStartResponse {
  call_id: string;
  actions: Action[];
}

export interface SimInputRequest {
  digits?: string;
  timeout?: boolean;
}

export interface SimInputResponse {
  actions: Action[];
  done: boolean;
}

/** Error envelope for every non-2xx response except Cedar denies. */
export interface ApiErrorBody {
  error: { code: string; message: string };
}
