/**
 * Wire types for the JalSakshi API.
 *
 * Mirrors src/jalsakshi/core/models.py (ARCHITECTURE.md §3, §15) and the HTTP contract in §13.
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
  | 'PHED_EE_SIM'
  | 'HANDPUMP_MECHANIC';

/** REGISTER, REPORT, BROADCAST and SUMMARY are the v2 call purposes (§15.12). */
export type Purpose =
  | 'DAILY'
  | 'VERIFY'
  | 'OPERATOR'
  | 'REGISTER'
  | 'REPORT'
  | 'BROADCAST'
  | 'SUMMARY'
  | 'ALERT';
export type CallOutcome = 'ANSWERED' | 'UNREACHABLE' | 'DECLINED';
export type WaterAnswer = 'YES' | 'NO' | 'PARTIAL';
export type CleanAnswer = 'YES' | 'NO';
export type CapturedVia = 'DTMF' | 'SPEECH' | 'SIMULATOR';
/** Where a family got drinking water on a day its own source failed (§15.1). */
export type Fallback = 'OTHER_SOURCE' | 'BOUGHT' | 'NONE';

export const WATER_POINT_KINDS = ['PIPED', 'HANDPUMP', 'BOREWELL', 'TANKER', 'OTHER'] as const;
export type WaterPointKind = (typeof WATER_POINT_KINDS)[number];

/** How a family draws its water; the water point is what breaks and gets repaired. */
export const ACCESS_KINDS = ['HOUSE_TAP', 'STANDPOST', 'HANDPUMP', 'BOREWELL', 'TANKER', 'OTHER'] as const;
export type AccessKind = (typeof ACCESS_KINDS)[number];

export type ConsentStatus = 'NONE' | 'GRANTED' | 'DECLINED' | 'WITHDRAWN';
export type ConsentAction = 'GRANTED' | 'DECLINED' | 'WITHDRAWN' | 'MINOR';

export const DAY_STATUSES = ['SUPPLIED', 'PARTIAL', 'NO_SUPPLY', 'DIRTY', 'UNVERIFIED'] as const;
export type DayStatusValue = (typeof DAY_STATUSES)[number];

export const TICKET_REASONS = ['NO_SUPPLY', 'DIRTY', 'LOW_PRESSURE', 'LEAK', 'BROKEN', 'OTHER'] as const;
export type TicketReason = (typeof TICKET_REASONS)[number];

/** How a complaint reached the register (§15.5). */
export type TicketOrigin = 'reconcile' | 'report' | 'voice_note' | 'console';

/** Why the operator says a problem is not fixed yet (operator call keys 2-7, §15.7). */
export type BlockerCode = 'PARTS_NEEDED' | 'NO_POWER' | 'PIPE_BROKEN' | 'NOT_MINE' | 'OTHER' | 'NEEDS_PANCHAYAT';

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

export const BROADCAST_KINDS = ['SUPPLY_CHANGE', 'BOIL_WATER', 'REPAIR_DONE', 'MEETING', 'CUSTOM'] as const;
export type BroadcastKind = (typeof BROADCAST_KINDS)[number];
export type BroadcastState = 'DRAFT' | 'APPROVED' | 'SENT' | 'CANCELLED';

export type QualityMethod = 'FTK' | 'LAB';
export type QualityResult = 'SAFE' | 'UNSAFE';

/** Har Ghar Jal status as the state's own dashboard records it. */
export type HgjStatus = 'IN_PROGRESS' | 'REPORTED' | 'CERTIFIED';

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
  channel: 'voice' | 'in_person' | 'ivr_keypad' | 'console';
  evidence_ref?: string | null;
  notice_version?: string | null;
  call_id?: string | null;
}

/** A location and where it came from ("GeoNames, approximate", "field GPS"). */
export interface GeoPoint {
  lat: number;
  lon: number;
  source: string;
  accuracy_m?: number | null;
}

export interface Village {
  id: string;
  name: string;
  block: string;
  district: string;
  name_hi?: string | null;
  state?: string | null;
  lgd_code?: string | null;
  census_code?: string | null;
  gram_panchayat?: string | null;
  gp_lgd_code?: string | null;
  census_households?: number | null;
  census_population?: number | null;
  census_source?: SourceTag | null;
  location?: GeoPoint | null;
  /** True for the village unknown missed-call numbers register into. */
  inbound?: boolean;
  imis_village_code?: string | null;
  claimed_hgj?: boolean | null;
  hgj_certified?: boolean | null;
  claimed_source?: SourceTag | null;
  /** Call languages; the first is the default for new families. */
  languages?: string[];
  /** Local (IST) time of the daily check-in, "HH:MM". */
  checkin_local_time: string;
  quorum: number;
  active: boolean;
}

/** A drinking-water source the Panchayat looks after: what breaks and gets repaired (§15.1). */
export interface WaterPoint {
  id: string;
  village_id: string;
  kind: WaterPointKind;
  name: string;
  name_hi?: string | null;
  hamlet?: string | null;
  location?: GeoPoint | null;
  /** "06:30-08:00", IST. */
  supply_window?: string | null;
  /** First = primary: complaints go to this operator. */
  operator_ids: string[];
  /** Households needed to confirm a repair; null = the village's quorum. */
  quorum?: number | null;
  /** Created by a registration and not yet checked by the secretary. */
  provisional: boolean;
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
  /** v2 consent state; absent on records written before v2 (then `consent` decides). */
  consent_status?: ConsentStatus | null;
  access?: AccessKind | null;
  water_point_id?: string | null;
  hamlet?: string | null;
  registered_via?: 'seed' | 'ivr' | 'console';
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

/** One entry of the append-only consent ledger (§15.3). Never updated or deleted. */
export interface ConsentEvent {
  village_id: string;
  household_id: string;
  phone_masked: string;
  action: ConsentAction;
  notice_version: string;
  notice_sha256: string;
  channel: 'ivr_keypad' | 'in_person' | 'console';
  call_id?: string | null;
  /** The key the person pressed, e.g. "1" (agree), "3" (decline), "9" (stop). */
  digits?: string | null;
  at: IsoDateTime;
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
  fallback?: Fallback | null;
  water_point_id?: string | null;
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

/** One water point's status for a day (`water_point_id` null = households with no point). */
export interface PointStatus {
  water_point_id?: string | null;
  status: DayStatusValue;
  counts: DayCounts;
}

export interface DayStatus {
  village_id: string;
  date: IsoDate;
  status: DayStatusValue;
  counts: DayCounts;
  rule_version: string;
  computed_at: IsoDateTime;
  /** Per water point (rule r2); empty or absent for days computed before r2. */
  points?: PointStatus[];
}

export interface TicketEvent {
  at: IsoDateTime;
  actor: string;
  kind: string;
  from_state?: TicketState | null;
  to_state?: TicketState | null;
  detail: Record<string, unknown>;
}

/** What the AI understood from a resident's voice note (§15.6). Advisory only, never a decision. */
export interface NoteIssue {
  issue: TicketReason;
  summary_hi: string;
  summary_en: string;
  transcript: string;
  location_hint?: string | null;
  days_affected?: number | null;
  /** 0..1 */
  confidence: number;
  model_id?: string | null;
}

/** AI advice on a complaint (§15.14): suggestions only; the secretary decides. */
export type NextStep = 'CALL_OPERATOR_AGAIN' | 'SEND_TO_SARPANCH' | 'RAISE_WITH_BLOCK_OFFICE' | 'WAIT_FOR_REPAIR';

export interface AdviceSuggestion {
  step: NextStep;
  label: string;
  /** "rules", or the decision model that answered (e.g. "jev-1.13.0"). */
  source: string;
  confidence: number | null;
  probabilities: Record<string, number>;
  urgent: number | null;
  reasons: string[];
}

export interface TicketOverview {
  text: string;
  /** The model that wrote the text, or "template". */
  text_source: string;
  suggestion: AdviceSuggestion | null;
  facts: Record<string, unknown>;
  generated_at: IsoDateTime;
}

export interface Ticket {
  id: string;
  village_id: string;
  reason: TicketReason;
  state: TicketState;
  opened_at: IsoDateTime;
  updated_at: IsoDateTime;
  events: TicketEvent[];
  /** Per-village complaint number ("shikayat kramank 7"). */
  number?: number | null;
  water_point_id?: string | null;
  origin?: TicketOrigin;
  /** Household ids of the families who reported it. */
  reporters?: string[];
  /** Households needed to close it. */
  quorum?: number | null;
  issue?: NoteIssue | null;
  blocker?: BlockerCode | null;
}

/** A Panchayat announcement played by phone, only after the sarpanch approves (§15.8). */
export interface Broadcast {
  id: string;
  village_id: string;
  water_point_id?: string | null;
  kind: BroadcastKind;
  text_hi: string;
  state: BroadcastState;
  created_by: string;
  created_at: IsoDateTime;
  approved_by?: string | null;
  approved_at?: IsoDateTime | null;
  sent_at?: IsoDateTime | null;
  recipients: number;
  delivered: number;
  heard: number;
}

/** A water-quality test of one water point (field test kit or lab), entered by a person (§15.9). */
export interface QualityTest {
  id: string;
  village_id: string;
  water_point_id?: string | null;
  tested_at: IsoDateTime;
  method: QualityMethod;
  result: QualityResult;
  parameters: Record<string, string>;
  entered_by: string;
  note?: string | null;
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
  /** Every open complaint (v2: one per water point and reason). */
  open_tickets?: Ticket[];
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

/** A water-supply scheme serving the village, as listed in IMIS (amounts in Rs lakh). */
export interface OfficialScheme {
  scheme_id: string;
  name?: string | null;
  kind?: string | null;
  sanction_year?: string | null;
  estimated_lakh?: number | null;
  spent_lakh?: number | null;
  status?: string | null;
  functional_status?: string | null;
}

/** Water-quality testing on record in WQMIS (values are ranges as published). */
export interface OfficialWaterQuality {
  last_household_test?: IsoDate | null;
  household_test_dates?: IsoDate[];
  last_household_values_date?: IsoDate | null;
  last_household_values?: Record<string, string>;
  samples_summary?: string;
  contamination_flags?: string[];
  ftk_this_fy?: string | null;
  ftk_samples_this_fy?: number | null;
  ftk_samples_last_fy?: number | null;
  ftk_parameters?: string[];
  ftk_note?: string | null;
  women_trained_ftk?: number | null;
}

/** The state's own JJM record for a village (data/official.py): a claim, never a decision input. */
export interface OfficialRecord {
  village_lgd: string;
  imis_village_id: string;
  name: string;
  gram_panchayat?: string | null;
  gp_imis_id?: string | null;
  households: number;
  tap_connections: number;
  population?: number | null;
  population_sc?: number | null;
  population_st?: number | null;
  hgj_status: HgjStatus;
  schemes?: OfficialScheme[];
  source_type?: string | null;
  wq?: OfficialWaterQuality | null;
  source: SourceTag;
}

/** GET /api/villages/{vid}. */
export interface VillageDetail {
  village: Village;
  households: HouseholdMasked[];
  operators: Operator[];
  context: VillageContext;
  water_points?: WaterPoint[];
  official?: OfficialRecord | null;
  /** "Last official household tap test: 17 Aug 2023 (3 years ago)". */
  official_note?: string | null;
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

/** A Cedar-guarded action whose 403 is a normal outcome (approve, send). */
export type ActionResult<T> = { ok: true; value: T } | { ok: false; denied: PolicyDenied };

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

// ---------------------------------------------------------------- §15 Gram Panchayat routes

/** POST /api/villages/{vid}/water-points: create (no id) or update (id). */
export interface WaterPointInput {
  id?: string;
  kind?: WaterPointKind;
  name?: string;
  name_hi?: string | null;
  hamlet?: string | null;
  supply_window?: string | null;
  operator_ids?: string[];
  quorum?: number | null;
  lat?: number;
  lon?: number;
  location_source?: string;
  active?: boolean;
}

/** POST /api/villages/{vid}/households: the family first gets the consent call. */
export interface AddHouseholdRequest {
  /** "+91" and ten digits. */
  phone: string;
  display_name?: string;
  access?: AccessKind;
  /** Place the consent (REGISTER) call now; default true. */
  call?: boolean;
}

export interface AddHouseholdResponse {
  household: HouseholdMasked;
  /** "queued" when the consent call was queued, "none" when no call was placed. */
  call: 'none' | 'queued';
}

/** GET /api/villages/{vid}/consents: the ledger, oldest first. */
export interface ConsentLedger {
  events: ConsentEvent[];
  notice_version: string;
  notice_sha256: string;
  /** "Designed to the DPDP Act 2023 / Rules 2025 standard; …" */
  label: string;
}

/** POST /api/villages/{vid}/tickets: a complaint brought to the Panchayat office. */
export interface RaiseTicketRequest {
  household_id: string;
  reason: TicketReason;
}

/** GET /api/villages/{vid}/broadcasts. */
export interface BroadcastList {
  broadcasts: Broadcast[];
  sent_last_7_days: number;
  weekly_limit: number;
}

export interface DraftBroadcastRequest {
  kind: BroadcastKind;
  /** 1-400 characters. */
  text_hi: string;
  water_point_id?: string | null;
}

/** 202 from send: the announcement as stored, with its calls queued. */
export type BroadcastSent = Broadcast & { queued: boolean };

/** GET /api/villages/{vid}/quality. */
export interface QualityList {
  tests: QualityTest[];
  official: OfficialRecord | null;
  official_note: string | null;
}

export interface AddQualityRequest {
  water_point_id?: string | null;
  method: QualityMethod;
  result: QualityResult;
  parameters?: Record<string, string>;
  note?: string;
  tested_at?: IsoDateTime;
}

// ---------------------------------------------------------------- analytics (core/analytics.py)

export interface OpenTicketAge {
  ticket_id: string;
  number?: number | null;
  reason: TicketReason;
  state: TicketState;
  age_hours: number;
  blocker?: string | null;
}

export interface QualitySnapshot {
  result: QualityResult;
  method: QualityMethod;
  tested_at: IsoDateTime;
}

/** One water point over the period (`water_point_id` null = households with no point). */
export interface PointAnalytics {
  water_point_id: string | null;
  name: string | null;
  kind: WaterPointKind | null;
  days_in_period: number;
  /** Days with a decided status (UNVERIFIED and missing days are unknown). */
  observed: number;
  supplied: number;
  partial: number;
  no_supply: number;
  dirty: number;
  unknown: number;
  /** supplied ÷ observed × 100; null when nothing was observed. Unknown days never count. */
  reliability_pct: number | null;
  complaints_by_reason: Record<string, number>;
  open_tickets: OpenTicketAge[];
  repairs_closed: number;
  median_repair_hours: number | null;
  worst_repair_hours: number | null;
  reopened: number;
  blockers: Record<string, number>;
  last_quality: QualitySnapshot | null;
  dirty_without_test: boolean;
}

export interface HouseholdAnalytics {
  registered: number;
  consented: number;
  withdrawn: number;
  declined: number;
  pending: number;
  census_households: number | null;
  coverage_pct: number | null;
  called: number;
  answered: number;
  answer_rate_pct: number | null;
  fallback_counts: Record<string, number>;
  reports_by_resident: number;
  consent_events: Record<string, number>;
}

export interface BroadcastAnalytics {
  sent: number;
  recipients: number;
  delivered: number;
  heard: number;
}

/** GET /api/villages/{vid}/analytics?from&to. */
export interface VillageAnalytics {
  village_id: string;
  start: IsoDate;
  end: IsoDate;
  generated_at: IsoDateTime;
  source: SourceTag;
  rule_note: string;
  points: PointAnalytics[];
  village: PointAnalytics;
  households: HouseholdAnalytics;
  broadcasts: BroadcastAnalytics;
  tickets_opened: number;
  tickets_closed_verified: number;
  median_repair_hours: number | null;
}

/** GET /api/villages/{vid}/summary: the Monday call to the sarpanch, as text. */
export interface WeeklySummary {
  village_id: string;
  start: IsoDate;
  end: IsoDate;
  /** Romanised Hindi, read out by TTS on the call. */
  text_hi: string;
  text_en: string;
  numbers: Record<string, number | null>;
  source: SourceTag;
}

// ---------------------------------------------------------------- residents' view (§15.11, no login)

/** GET /public/villages row. */
export interface PublicVillageRow {
  id: string;
  name: string;
  name_hi?: string | null;
  lgd_code?: string | null;
}

export interface PublicDay {
  date: IsoDate;
  status: DayStatusValue;
  points: Array<{ water_point_id: string | null; status: DayStatusValue }>;
  answered: number;
}

export interface PublicComplaint {
  number: number | null;
  reason: TicketReason;
  water_point: string | null;
  water_point_hi: string | null;
  state: TicketState;
  opened_at: IsoDateTime;
  age_hours: number;
  families: number;
}

export interface PublicAnnouncement {
  kind: BroadcastKind;
  text_hi: string;
  sent_at: IsoDateTime;
}

export interface PublicOfficial {
  households: number;
  tap_connections: number;
  hgj_status: HgjStatus;
  water_quality_note: string;
  source: SourceTag;
}

/** GET /public/villages/{vid}: village-level facts only, never a name or a phone. */
export interface PublicVillageView {
  village: {
    id: string;
    name: string;
    name_hi?: string | null;
    gram_panchayat?: string | null;
    block: string;
    district: string;
    lgd_code?: string | null;
  };
  generated_at: IsoDateTime;
  water_points: Array<{ id: string; name: string; name_hi?: string | null; kind: WaterPointKind }>;
  days: PublicDay[];
  open_complaints: PublicComplaint[];
  repairs_confirmed: { count: number; median_hours: number | null };
  announcements: PublicAnnouncement[];
  families_reporting: number;
  official: PublicOfficial | null;
  sources: string[];
  missed_call_number: string | null;
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

// ---------------------------------------------------------------- who am I

/** GET /api/me: the signed-in user and the role Cedar sees (to show the right actions). */
export interface Me {
  username: string | null;
  email: string | null;
  role: OperatorRole;
  is_admin: boolean;
  /** Villages this account looks after (admins: every village). */
  village_ids: string[];
  /** True until the account has set up its first village. */
  needs_setup: boolean;
  can_approve_announcements: boolean;
}

/** A known village (LGD + Census) to pick during setup (GET /api/places). */
export interface Place {
  lgd_code: string;
  name: string;
  name_hi?: string | null;
  gram_panchayat?: string | null;
  block: string;
  district: string;
  census_households?: number | null;
}

export interface Person {
  name: string;
  phone: string;
}

/** POST /api/villages: a known village by LGD code, or a new one by name. */
export type CreateVillageRequest = (
  | { lgd_code: string }
  | { name: string; name_hi?: string; gram_panchayat?: string; block: string; district: string }
) & { operator: Person; sarpanch?: Person };

export type TeamRole = 'operator' | 'sarpanch' | 'secretary';

export interface BulkAddResponse {
  added: HouseholdMasked[];
  skipped: Array<{ input: string; why: string }>;
}

/** A family to add with what is known about them (from a register photo or typed). */
export interface FamilyRow {
  phone: string;
  name?: string | null;
  area?: string | null;
}

/** GET /api/languages: call languages and whether their recordings exist on this stage. */
export interface CallLanguage {
  code: string;
  name: string;
  ready: boolean;
}

/** One row read from a photo of a register. Nothing is added until the user confirms. */
export interface RegisterRow {
  name: string | null;
  phone: string;
  area: string | null;
  phone_ok: boolean;
}

export interface RegisterPhotoResponse {
  rows: RegisterRow[];
  model_id: string;
  note: string;
}

/** POST /api/villages/{vid}/settings. */
export interface VillageSettings {
  languages?: string[];
  checkin_local_time?: string;
}

/** POST /api/admin/panchayats (JalSakshi team only): one login, its village, languages, team. */
export interface CreatePanchayatRequest {
  username: string;
  temporary_password?: string;
  village:
    | { lgd_code: string }
    | { name: string; gram_panchayat?: string; block: string; district: string };
  languages: string[];
  operator: Person;
  sarpanch?: Person;
  secretary?: Person;
}

export interface CreatePanchayatResponse {
  username: string;
  temporary_password: string;
  village: Village;
  note: string;
}

/** Error envelope for every non-2xx response except Cedar denies. */
export interface ApiErrorBody {
  error: { code: string; message: string };
}
