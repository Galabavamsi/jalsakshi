/**
 * Seeded demo data for VITE_API_MODE=mock: two villages in Durg district, 14 days of statuses,
 * one open ticket (verifying) and one CLOSED_VERIFIED ticket with a full timeline.
 *
 * Everything here is demo data. Every SourceTag is `simulated` and every source name says "demo".
 * Dates are generated relative to "now" so the strip always ends today (IST).
 */

import { addDays, istDate, istInstant, istNoon, minutesFrom } from '../lib/time';
import type {
  ActivityItem,
  CheckInMasked,
  CleanAnswer,
  DayCounts,
  DayStatus,
  DayStatusValue,
  HouseholdMasked,
  IsoDate,
  Operator,
  SourceTag,
  Ticket,
  TicketEvent,
  Village,
  VillageContext,
  WaterAnswer,
} from './types';

export const RULE_VERSION = 'r1';
export const SEED_DAYS = 14;

/** Mutable in-memory store behind the mock API. */
export interface MockState {
  villages: Village[];
  households: HouseholdMasked[];
  operators: Operator[];
  days: DayStatus[];
  checkins: CheckInMasked[];
  tickets: Ticket[];
  activity: ActivityItem[];
  context: Record<string, VillageContext>;
}

// ---------------------------------------------------------------- reconcile mirror

/** Mirror of core/reconcile.py rule r1 (ARCHITECTURE.md §4), so seeded statuses are consistent. */
export function reconcileCounts(c: DayCounts, quorum: number): DayStatusValue {
  if (c.answered < quorum) return 'UNVERIFIED';
  if (c.no >= quorum && c.no >= c.yes + c.partial) return 'NO_SUPPLY';
  if (c.dirty >= quorum) return 'DIRTY';
  if (c.no + c.partial >= 1) return 'PARTIAL';
  return 'SUPPLIED';
}

/** Counts DAILY check-ins, taking the latest attempt per household. */
export function countsFromCheckins(checkins: CheckInMasked[]): DayCounts {
  const latest = new Map<string, CheckInMasked>();
  for (const c of checkins) {
    if (c.purpose !== 'DAILY') continue;
    const prev = latest.get(c.household_id);
    if (!prev || c.attempt > prev.attempt) latest.set(c.household_id, c);
  }
  const counts: DayCounts = { answered: 0, yes: 0, no: 0, partial: 0, dirty: 0, unreachable: 0 };
  for (const c of latest.values()) {
    if (c.outcome === 'UNREACHABLE') counts.unreachable += 1;
    if (c.outcome !== 'ANSWERED' || !c.water) continue;
    counts.answered += 1;
    if (c.water === 'YES') counts.yes += 1;
    if (c.water === 'NO') counts.no += 1;
    if (c.water === 'PARTIAL') counts.partial += 1;
    if (c.clean === 'NO') counts.dirty += 1;
  }
  return counts;
}

// ---------------------------------------------------------------- seed definitions

/** [yes, no, partial, dirty, unreachable] for one day. */
type DayCode = readonly [number, number, number, number, number];

interface HouseholdSeed {
  id: string;
  name: string;
  last4: string;
  consent: 'voice' | 'in_person' | null;
}

interface VillageSeed {
  village: Omit<Village, 'claimed_source'>;
  households: HouseholdSeed[];
  /** Oldest first; the last entry is today. */
  days: DayCode[];
  groundwater: { stage_pct: number; category: string };
  rainMm: number;
}

const VILLAGE_SEEDS: VillageSeed[] = [
  {
    village: {
      id: 'v-nayapara',
      name: 'नयापारा',
      block: 'पाटन',
      district: 'दुर्ग',
      imis_village_code: null,
      claimed_hgj: true,
      hgj_certified: false,
      checkin_local_time: '10:30',
      quorum: 2,
      active: true,
    },
    households: [
      { id: 'hh-nyp-1', name: 'कमला बाई', last4: '0412', consent: 'voice' },
      { id: 'hh-nyp-2', name: 'सुनीता साहू', last4: '7731', consent: 'in_person' },
      { id: 'hh-nyp-3', name: 'रेखा वर्मा', last4: '2290', consent: 'voice' },
      { id: 'hh-nyp-4', name: 'शांति यादव', last4: '5108', consent: 'in_person' },
      { id: 'hh-nyp-5', name: 'गीता निषाद', last4: '9043', consent: null },
    ],
    days: [
      [4, 0, 0, 0, 0],
      [3, 0, 1, 0, 0],
      [4, 0, 0, 0, 0],
      [3, 0, 0, 0, 1],
      [2, 0, 2, 0, 0],
      [4, 0, 0, 0, 0],
      [1, 0, 1, 0, 2],
      [3, 0, 1, 0, 0],
      [4, 0, 0, 0, 0],
      [2, 1, 1, 0, 0],
      [1, 0, 0, 0, 3],
      [0, 3, 1, 0, 0],
      [0, 4, 0, 0, 0],
      [1, 1, 1, 0, 1],
    ],
    groundwater: { stage_pct: 82, category: 'Semi-critical' },
    rainMm: 3.5,
  },
  {
    village: {
      id: 'v-amlidih',
      name: 'अमलीडीह',
      block: 'धमधा',
      district: 'दुर्ग',
      imis_village_code: null,
      claimed_hgj: true,
      hgj_certified: true,
      checkin_local_time: '11:00',
      quorum: 2,
      active: true,
    },
    households: [
      { id: 'hh-aml-1', name: 'सरिता ध्रुव', last4: '3317', consent: 'voice' },
      { id: 'hh-aml-2', name: 'मीना साहू', last4: '6624', consent: 'voice' },
      { id: 'hh-aml-3', name: 'पार्वती पटेल', last4: '1185', consent: 'in_person' },
    ],
    days: [
      [3, 0, 0, 0, 0],
      [3, 0, 0, 0, 0],
      [2, 0, 0, 0, 1],
      [3, 0, 0, 2, 0],
      [2, 0, 1, 2, 0],
      [2, 0, 1, 0, 0],
      [3, 0, 0, 0, 0],
      [3, 0, 0, 0, 0],
      [3, 0, 0, 0, 0],
      [1, 0, 0, 0, 2],
      [3, 0, 0, 0, 0],
      [2, 0, 1, 0, 0],
      [3, 0, 0, 0, 0],
      [3, 0, 0, 0, 0],
    ],
    groundwater: { stage_pct: 64, category: 'Safe' },
    rainMm: 6,
  },
];

const OPERATORS: Operator[] = [
  {
    id: 'op-nyp-njm',
    role: 'NAL_JAL_MITRA',
    phone_e164: '+910000000101',
    display_name: 'रमेश साहू',
    village_ids: ['v-nayapara'],
  },
  {
    id: 'op-nyp-sec',
    role: 'PANCHAYAT_SECRETARY',
    phone_e164: '+910000000102',
    display_name: 'अनीता ठाकुर',
    village_ids: ['v-nayapara'],
  },
  {
    id: 'op-aml-njm',
    role: 'NAL_JAL_MITRA',
    phone_e164: '+910000000103',
    display_name: 'दिनेश ध्रुव',
    village_ids: ['v-amlidih'],
  },
  {
    id: 'op-aml-sar',
    role: 'SARPANCH',
    phone_e164: '+910000000104',
    display_name: 'लक्ष्मी पटेल',
    village_ids: ['v-amlidih'],
  },
  {
    id: 'op-phed-ae',
    role: 'PHED_AE_SIM',
    phone_e164: '+910000000105',
    display_name: 'PHED सहायक अभियंता, दुर्ग',
    village_ids: ['v-nayapara', 'v-amlidih'],
  },
];

// ---------------------------------------------------------------- builders

/** A demo SourceTag: always `simulated`, always says "demo". */
export function demoSource(source: string, fetchedAt: Date, observedAt?: Date): SourceTag {
  return {
    source: `${source} (demo)`,
    observed_at: observedAt ? observedAt.toISOString() : null,
    fetched_at: fetchedAt.toISOString(),
    freshness: 'simulated',
    url: null,
  };
}

/** Keeps generated times in the past, so an early-morning load never shows future events. */
function notAfter(at: Date, now: Date): Date {
  return at.getTime() > now.getTime() ? minutesFrom(now, -5) : at;
}

function maskedHousehold(vid: string, h: HouseholdSeed, now: Date): HouseholdMasked {
  return {
    id: h.id,
    village_id: vid,
    phone_masked: `+91XXXXXX${h.last4}`,
    display_name: h.name,
    language: 'hi',
    call_window: '09:00-20:00',
    consent: h.consent
      ? { given_at: addDaysIso(now, -30), channel: h.consent, evidence_ref: `consent/${h.id}` }
      : null,
    active: true,
  };
}

function addDaysIso(now: Date, days: number): string {
  return new Date(now.getTime() + days * 86_400_000).toISOString();
}

interface Answer {
  water: WaterAnswer;
  clean: CleanAnswer | null;
}

/** Expands a day code into per-household answers: NO first, then PARTIAL, then YES. */
function answersFor([yes, no, partial, dirty]: DayCode): Answer[] {
  const waters: WaterAnswer[] = [
    ...Array<WaterAnswer>(no).fill('NO'),
    ...Array<WaterAnswer>(partial).fill('PARTIAL'),
    ...Array<WaterAnswer>(yes).fill('YES'),
  ];
  let dirtyLeft = dirty;
  return waters.map((water) => {
    if (water === 'NO') return { water, clean: null };
    const clean: CleanAnswer = dirtyLeft > 0 ? 'NO' : 'YES';
    if (dirtyLeft > 0) dirtyLeft -= 1;
    return { water, clean };
  });
}

function rotate<T>(items: T[], by: number): T[] {
  if (items.length === 0) return items;
  const k = by % items.length;
  return [...items.slice(k), ...items.slice(0, k)];
}

function dayCheckins(
  seed: VillageSeed,
  date: IsoDate,
  dayIndex: number,
  now: Date,
): CheckInMasked[] {
  const vid = seed.village.id;
  const callable = rotate(
    seed.households.filter((h) => h.consent !== null),
    dayIndex,
  );
  const answers = answersFor(seed.days[dayIndex] as DayCode);
  const unreachable = (seed.days[dayIndex] as DayCode)[4];
  const start = istInstant(date, seed.village.checkin_local_time);
  const out: CheckInMasked[] = [];
  callable.forEach((h, i) => {
    if (i >= answers.length + unreachable) return;
    const answer = answers[i];
    const capturedAt = notAfter(minutesFrom(start, 2 + i * 3), now);
    out.push({
      village_id: vid,
      date,
      household_id: h.id,
      phone_masked: `+91XXXXXX${h.last4}`,
      attempt: answer ? 1 : 2,
      call_id: `call-${date}-${h.id}`,
      purpose: 'DAILY',
      outcome: answer ? 'ANSWERED' : 'UNREACHABLE',
      water: answer?.water ?? null,
      hours: answer ? hoursFor(answer.water, i) : null,
      clean: answer?.clean ?? null,
      note_transcript: null,
      note_issue: null,
      captured_via: 'DTMF',
      captured_at: capturedAt.toISOString(),
    });
  });
  return out;
}

function hoursFor(water: WaterAnswer, i: number): number | null {
  if (water === 'YES') return 3 - (i % 2);
  if (water === 'PARTIAL') return 1;
  return null;
}

/** Builds a DayStatus from that day's check-ins with the reconcile mirror. */
export function dayStatusFrom(
  village: Village,
  date: IsoDate,
  checkins: CheckInMasked[],
  computedAt: Date,
): DayStatus {
  const counts = countsFromCheckins(checkins);
  return {
    village_id: village.id,
    date,
    status: reconcileCounts(counts, village.quorum),
    counts,
    rule_version: RULE_VERSION,
    computed_at: computedAt.toISOString(),
  };
}

function event(
  at: Date,
  actor: string,
  kind: string,
  from: Ticket['state'] | null,
  to: Ticket['state'] | null,
  detail: Record<string, unknown> = {},
): TicketEvent {
  return { at: at.toISOString(), actor, kind, from_state: from, to_state: to, detail };
}

/** Nayapara: no supply two days running, operator says fixed today, 1 of 2 confirmations so far. */
function nayaparaTicket(today: IsoDate, now: Date): Ticket {
  const d2 = addDays(today, -2);
  const d1 = addDays(today, -1);
  const fixedAt = minutesFrom(now, -150);
  const events = [
    event(istInstant(d2, '10:46'), 'system:reconcile', 'opened', null, 'OPEN', {
      day_status: 'NO_SUPPLY',
      no: 3,
      answered: 4,
      rule_version: RULE_VERSION,
    }),
    event(istInstant(d2, '10:47'), 'system:ticket-flow', 'notified', 'OPEN', 'ASSIGNED', {
      operator_id: 'op-nyp-njm',
      call_id: `call-${d2}-op-nyp-njm`,
    }),
    event(istInstant(d1, '10:46'), 'system:reconcile', 'day_still_bad', null, null, {
      day_status: 'NO_SUPPLY',
      no: 4,
      answered: 4,
    }),
    event(fixedAt, 'op-nyp-njm', 'operator_fixed', 'ASSIGNED', 'OPERATOR_REPORTED_FIXED', {
      via: 'DTMF',
      digits: '1',
    }),
    event(minutesFrom(fixedAt, 1), 'system:ticket-flow', 'verify_started', 'OPERATOR_REPORTED_FIXED', 'VERIFYING', {
      households: 4,
      quorum: 2,
    }),
    event(minutesFrom(fixedAt, 30), 'hh-nyp-2', 'verify_answer', null, null, {
      water: 'YES',
      verify_yes: 1,
      quorum: 2,
    }),
  ];
  const last = events[events.length - 1] as TicketEvent;
  return {
    id: 'tkt-nyp-0007',
    village_id: 'v-nayapara',
    reason: 'NO_SUPPLY',
    state: 'VERIFYING',
    opened_at: events[0]?.at ?? now.toISOString(),
    updated_at: last.at,
    events,
  };
}

/** Amlidih: dirty water, one failed verification (reopened), then confirmed by households. */
function amlidihTicket(today: IsoDate): Ticket {
  const d10 = addDays(today, -10);
  const d9 = addDays(today, -9);
  const d8 = addDays(today, -8);
  const d7 = addDays(today, -7);
  const events = [
    event(istInstant(d10, '11:16'), 'system:reconcile', 'opened', null, 'OPEN', {
      day_status: 'DIRTY',
      dirty: 2,
      answered: 3,
      rule_version: RULE_VERSION,
    }),
    event(istInstant(d10, '11:17'), 'system:ticket-flow', 'notified', 'OPEN', 'ASSIGNED', {
      operator_id: 'op-aml-njm',
    }),
    event(istInstant(d9, '17:20'), 'op-aml-njm', 'operator_fixed', 'ASSIGNED', 'OPERATOR_REPORTED_FIXED', {
      via: 'DTMF',
      digits: '1',
    }),
    event(istInstant(d9, '17:21'), 'system:ticket-flow', 'verify_started', 'OPERATOR_REPORTED_FIXED', 'VERIFYING', {
      households: 3,
      quorum: 2,
    }),
    event(istInstant(d9, '18:05'), 'system:verify', 'reopened', 'VERIFYING', 'REOPENED', {
      verify_yes: 1,
      verify_no: 1,
    }),
    event(istInstant(d9, '18:06'), 'system:ticket-flow', 'notified', 'REOPENED', 'ASSIGNED', {
      operator_id: 'op-aml-njm',
    }),
    event(istInstant(d8, '12:40'), 'op-aml-njm', 'operator_fixed', 'ASSIGNED', 'OPERATOR_REPORTED_FIXED', {
      via: 'DTMF',
      digits: '1',
    }),
    event(istInstant(d8, '12:41'), 'system:ticket-flow', 'verify_started', 'OPERATOR_REPORTED_FIXED', 'VERIFYING', {
      households: 3,
      quorum: 2,
    }),
    event(istInstant(d7, '10:35'), 'system:verify', 'closed_verified', 'VERIFYING', 'CLOSED_VERIFIED', {
      verify_yes: 3,
      quorum: 2,
    }),
  ];
  return {
    id: 'tkt-aml-0003',
    village_id: 'v-amlidih',
    reason: 'DIRTY',
    state: 'CLOSED_VERIFIED',
    opened_at: events[0]?.at ?? '',
    updated_at: events[events.length - 1]?.at ?? '',
    events,
  };
}

function seedActivity(today: IsoDate, now: Date): ActivityItem[] {
  const y = addDays(today, -1);
  const fixedAt = minutesFrom(now, -150);
  const items: ActivityItem[] = [
    {
      at: istInstant(y, '10:30').toISOString(),
      kind: 'checkin_run',
      village_id: 'v-nayapara',
      text_en: 'Nayapara: daily check-in calls started for 4 households.',
      text_hi: 'नयापारा: 4 घरों को रोज़ की जाँच के कॉल शुरू हुए।',
    },
    {
      at: istInstant(y, '10:46').toISOString(),
      kind: 'day_status',
      village_id: 'v-nayapara',
      text_en: 'Nayapara: no supply again (4 of 4 said no). Ticket already open, so no duplicate.',
      text_hi: 'नयापारा: आज फिर पानी नहीं आया (4 में से 4 ने ना कहा)। शिकायत पहले से खुली है।',
    },
    {
      at: istInstant(y, '11:00').toISOString(),
      kind: 'policy_denied',
      village_id: 'v-amlidih',
      text_en: 'Amlidih: call to household 3 skipped, it was already called today (one-call-per-day).',
      text_hi: 'अमलीडीह: घर 3 को कॉल नहीं किया, आज पहले ही कॉल हो चुका था।',
    },
    {
      at: istInstant(y, '11:14').toISOString(),
      kind: 'day_status',
      village_id: 'v-amlidih',
      text_en: 'Amlidih: water supplied (3 of 3 said yes).',
      text_hi: 'अमलीडीह: पानी आया (3 में से 3 ने हाँ कहा)।',
    },
    {
      at: notAfter(istInstant(today, '10:46'), now).toISOString(),
      kind: 'day_status',
      village_id: 'v-nayapara',
      text_en: 'Nayapara: partial supply today (3 of 4 answered).',
      text_hi: 'नयापारा: आज थोड़ा पानी आया (4 में से 3 घरों ने जवाब दिया)।',
    },
    {
      at: fixedAt.toISOString(),
      kind: 'ticket',
      village_id: 'v-nayapara',
      text_en: 'Nayapara: pump operator pressed 1, "fixed". Calling households to confirm.',
      text_hi: 'नयापारा: नल जल मित्र ने 1 दबाया, "ठीक हो गया"। घरों से पुष्टि के कॉल जा रहे हैं।',
    },
    {
      at: minutesFrom(fixedAt, 30).toISOString(),
      kind: 'call',
      village_id: 'v-nayapara',
      text_en: 'Nayapara: household 2 confirmed water is back (1 of 2 needed).',
      text_hi: 'नयापारा: घर 2 ने पुष्टि की कि पानी आ रहा है (2 में से 1)।',
    },
  ];
  return items.sort((a, b) => a.at.localeCompare(b.at));
}

/** Builds the full demo store relative to `now`. */
export function seedMockState(now: Date): MockState {
  const today = istDate(now);
  const state: MockState = {
    villages: [],
    households: [],
    operators: OPERATORS.map((o) => ({ ...o, village_ids: [...o.village_ids] })),
    days: [],
    checkins: [],
    tickets: [],
    activity: [],
    context: {},
  };
  for (const seed of VILLAGE_SEEDS) {
    const village: Village = {
      ...seed.village,
      claimed_source: demoSource('JJM IMIS Har Ghar Jal report', now, istNoon(addDays(today, -1))),
    };
    state.villages.push(village);
    state.households.push(...seed.households.map((h) => maskedHousehold(village.id, h, now)));
    seed.days.forEach((_, i) => {
      const date = addDays(today, i - (SEED_DAYS - 1));
      const checkins = dayCheckins(seed, date, i, now);
      const computedAt = notAfter(
        minutesFrom(istInstant(date, village.checkin_local_time), 16),
        now,
      );
      state.checkins.push(...checkins);
      state.days.push(dayStatusFrom(village, date, checkins, computedAt));
    });
    state.context[village.id] = {
      groundwater: {
        ...seed.groundwater,
        source: demoSource('CGWB 2025 assessment, India-WRIS', now, new Date('2025-03-31T00:00:00Z')),
      },
      rain_7d_mm: { value: seed.rainMm, source: demoSource('Open-Meteo, last 7 days', now, now) },
      state_hgj: {
        villages: 20000,
        reported: 7600,
        certified: 6600,
        source: demoSource('JJM IMIS, Chhattisgarh', now, istNoon(addDays(today, -1))),
      },
    };
  }
  addLeakNote(state, addDays(today, -2));
  addVerifyAnswer(state, now);
  state.tickets.push(nayaparaTicket(today, now), amlidihTicket(today));
  state.activity = seedActivity(today, now);
  return state;
}

/** One spoken note, to show the agent's extraction next to keypad answers. */
function addLeakNote(state: MockState, date: IsoDate): void {
  const target = state.checkins.find(
    (c) => c.village_id === 'v-nayapara' && c.date === date && c.water === 'NO',
  );
  if (!target) return;
  target.note_transcript = 'स्कूल के पास वाला पाइप फूटा है, दो दिन से पानी बह रहा है।';
  target.note_issue = 'LEAK';
}

/** The single verification "yes" so far on the Nayapara ticket. */
function addVerifyAnswer(state: MockState, now: Date): void {
  const at = minutesFrom(now, -120);
  state.checkins.push({
    village_id: 'v-nayapara',
    date: istDate(at),
    household_id: 'hh-nyp-2',
    phone_masked: '+91XXXXXX7731',
    attempt: 1,
    call_id: `call-verify-${istDate(at)}-hh-nyp-2`,
    purpose: 'VERIFY',
    outcome: 'ANSWERED',
    water: 'YES',
    hours: null,
    clean: null,
    note_transcript: null,
    note_issue: null,
    captured_via: 'DTMF',
    captured_at: at.toISOString(),
  });
}
