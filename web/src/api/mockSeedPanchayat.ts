/**
 * Gram Panchayat demo data (ARCHITECTURE.md §15) on top of the seeded demo villages: water points,
 * families with their consent state, the consent ledger, numbered complaints (one from a voice
 * note, one from a missed call), announcements, water-quality tests and a demo stand-in for the
 * government record.
 *
 * Everything here is demo data for the two demo villages (never the pilot village). Phones are
 * masked placeholders, names say nothing about real people, every SourceTag is `simulated`.
 */

import { addDays, istDate, istInstant, istNoon } from '../lib/time';
import { demoSource, pointStatuses, seedMockState, type MockState } from './mockSeed';
import type {
  AccessKind,
  ActivityItem,
  Broadcast,
  ConsentEvent,
  ConsentStatus,
  HouseholdMasked,
  OfficialRecord,
  QualityTest,
  Ticket,
  TicketEvent,
  WaterPoint,
} from './types';

export const DEMO_NOTICE_SHA = 'demo-notice-hi-1-sha256-not-computed';

const POINTS: WaterPoint[] = [
  {
    id: 'wp-nyp-piped',
    village_id: 'v-nayapara',
    kind: 'PIPED',
    name: 'Nayapara piped supply (demo)',
    name_hi: 'नयापारा नल जल योजना (डेमो)',
    supply_window: '06:30-08:00',
    operator_ids: ['op-nyp-njm'],
    quorum: null,
    provisional: false,
    active: true,
  },
  {
    id: 'wp-nyp-handpump',
    village_id: 'v-nayapara',
    kind: 'HANDPUMP',
    name: 'School handpump (demo)',
    name_hi: 'स्कूल वाला हैंडपंप (डेमो)',
    hamlet: 'Schoolpara',
    supply_window: null,
    operator_ids: ['op-nyp-hpm'],
    quorum: 1,
    provisional: false,
    active: true,
  },
  {
    id: 'wp-nyp-tanker',
    village_id: 'v-nayapara',
    kind: 'TANKER',
    name: 'Nayapara tanker',
    name_hi: 'नयापारा टैंकर',
    supply_window: null,
    operator_ids: [],
    quorum: null,
    provisional: true,
    active: true,
  },
  {
    id: 'wp-aml-piped',
    village_id: 'v-amlidih',
    kind: 'PIPED',
    name: 'Amlidih piped supply (demo)',
    name_hi: 'अमलीडीह नल जल योजना (डेमो)',
    supply_window: '07:00-09:00',
    operator_ids: ['op-aml-njm'],
    quorum: null,
    provisional: false,
    active: true,
  },
  {
    id: 'wp-aml-borewell',
    village_id: 'v-amlidih',
    kind: 'BOREWELL',
    name: 'Amlidih borewell or well',
    name_hi: 'अमलीडीह बोरवेल या कुआँ',
    supply_window: null,
    operator_ids: [],
    quorum: null,
    provisional: true,
    active: true,
  },
];

/** How the seeded households draw water, and where their answers count. */
const ACCESS_OF: Record<string, { access: AccessKind; point: string }> = {
  'hh-nyp-1': { access: 'HOUSE_TAP', point: 'wp-nyp-piped' },
  'hh-nyp-2': { access: 'HOUSE_TAP', point: 'wp-nyp-piped' },
  'hh-nyp-3': { access: 'STANDPOST', point: 'wp-nyp-piped' },
  'hh-nyp-4': { access: 'STANDPOST', point: 'wp-nyp-piped' },
  'hh-nyp-5': { access: 'HANDPUMP', point: 'wp-nyp-handpump' },
  'hh-aml-1': { access: 'HOUSE_TAP', point: 'wp-aml-piped' },
  'hh-aml-2': { access: 'HOUSE_TAP', point: 'wp-aml-piped' },
  'hh-aml-3': { access: 'STANDPOST', point: 'wp-aml-piped' },
};

interface ExtraFamily {
  id: string;
  village: string;
  name: string | null;
  last4: string;
  status: ConsentStatus;
  access: AccessKind | null;
  point: string | null;
  via: 'ivr' | 'console';
}

/** Families outside the daily-call rotation of the base seed. */
const EXTRA_FAMILIES: ExtraFamily[] = [
  {
    id: 'hh-nyp-6',
    village: 'v-nayapara',
    name: 'फूलबती ठाकुर',
    last4: '3359',
    status: 'GRANTED',
    access: 'HANDPUMP',
    point: 'wp-nyp-handpump',
    via: 'ivr',
  },
  {
    id: 'hh-nyp-7',
    village: 'v-nayapara',
    name: null,
    last4: '6610',
    status: 'WITHDRAWN',
    access: 'HOUSE_TAP',
    point: 'wp-nyp-piped',
    via: 'ivr',
  },
  {
    id: 'hh-nyp-8',
    village: 'v-nayapara',
    name: 'सावित्री मरकाम',
    last4: '4471',
    status: 'NONE',
    access: 'TANKER',
    point: 'wp-nyp-tanker',
    via: 'console',
  },
  {
    id: 'hh-nyp-9',
    village: 'v-nayapara',
    name: null,
    last4: '2208',
    status: 'DECLINED',
    access: null,
    point: null,
    via: 'ivr',
  },
];

const MECHANIC = {
  id: 'op-nyp-hpm',
  role: 'HANDPUMP_MECHANIC' as const,
  phone_e164: '+910000000106',
  display_name: 'संतोष यादव',
  village_ids: ['v-nayapara'],
};

function masked(last4: string): string {
  return `+91XXXXXX${last4}`;
}

function ev(
  at: Date,
  actor: string,
  kind: string,
  from: Ticket['state'] | null,
  to: Ticket['state'] | null,
  detail: Record<string, unknown> = {},
): TicketEvent {
  return { at: at.toISOString(), actor, kind, from_state: from, to_state: to, detail };
}

function consent(
  village: string,
  hid: string,
  last4: string,
  action: ConsentEvent['action'],
  at: Date,
  channel: ConsentEvent['channel'],
  digits: string | null,
): ConsentEvent {
  return {
    village_id: village,
    household_id: hid,
    phone_masked: masked(last4),
    action,
    notice_version: 'hi-1',
    notice_sha256: DEMO_NOTICE_SHA,
    channel,
    call_id: channel === 'ivr_keypad' ? `call-demo-register-${hid}-${istDate(at)}` : null,
    digits,
    at: at.toISOString(),
  };
}

function decorateHouseholds(state: MockState, now: Date): void {
  for (const h of state.households) {
    const where = ACCESS_OF[h.id];
    h.access = where?.access ?? null;
    h.water_point_id = where?.point ?? null;
    h.consent_status = h.consent ? 'GRANTED' : 'NONE';
    h.registered_via = h.consent ? 'seed' : 'console';
  }
  const yesterday = addDays(istDate(now), -1);
  for (const f of EXTRA_FAMILIES) {
    const household: HouseholdMasked = {
      id: f.id,
      village_id: f.village,
      phone_masked: masked(f.last4),
      display_name: f.name,
      language: 'hi',
      call_window: '09:00-20:00',
      consent:
        f.status === 'GRANTED'
          ? {
              given_at: istInstant(yesterday, '17:40').toISOString(),
              channel: 'ivr_keypad',
              notice_version: 'hi-1',
              call_id: `call-demo-register-${f.id}-${yesterday}`,
            }
          : null,
      consent_status: f.status,
      access: f.access,
      water_point_id: f.point,
      registered_via: f.via,
      active: f.status === 'GRANTED' || f.status === 'NONE',
    };
    state.households.push(household);
  }
}

/** Check-ins carry the household's water point; day statuses gain their per-point detail. */
const FALLBACKS = ['OTHER_SOURCE', 'BOUGHT', 'NONE', 'OTHER_SOURCE'] as const;

function decorateDays(state: MockState): void {
  const pointOf = new Map(state.households.map((h) => [h.id, h.water_point_id ?? null]));
  let n = 0;
  for (const c of state.checkins) {
    c.water_point_id = pointOf.get(c.household_id) ?? null;
    // A NO answer gets the extra question: where did the family get drinking water instead?
    if (c.purpose === 'DAILY' && c.water === 'NO') {
      c.fallback = FALLBACKS[n % FALLBACKS.length];
      n += 1;
    }
  }
  for (const day of state.days) {
    const village = state.villages.find((v) => v.id === day.village_id);
    const checkins = state.checkins.filter((c) => c.village_id === day.village_id && c.date === day.date);
    day.points = pointStatuses(checkins, village?.quorum ?? 2);
  }
}

function decorateTickets(state: MockState, now: Date): void {
  const yesterday = addDays(istDate(now), -1);
  for (const t of state.tickets) {
    t.number = t.id === 'tkt-nyp-0007' ? 7 : t.id === 'tkt-aml-0003' ? 3 : null;
    t.water_point_id = t.village_id === 'v-nayapara' ? 'wp-nyp-piped' : 'wp-aml-piped';
    t.origin = 'reconcile';
    t.reporters = [];
    t.quorum = 2;
  }

  // #8: a resident's voice note (missed call, option 3), understood by the agent; parts needed.
  const leakAt = istInstant(yesterday, '18:20');
  const leakEvents = [
    ev(leakAt, 'system:notes', 'opened', null, 'OPEN', { origin: 'voice_note', household_id: 'hh-nyp-3' }),
    ev(istInstant(yesterday, '18:21'), 'system:ticket-flow', 'notified', 'OPEN', 'ASSIGNED', {
      operator_id: 'op-nyp-njm',
    }),
    ev(istInstant(yesterday, '19:05'), 'operator:op-nyp-njm', 'NOTE', null, null, {
      note: 'operator_reason',
      code: 'PARTS_NEEDED',
      via: 'DTMF',
      digits: '2',
    }),
  ];
  state.tickets.push({
    id: 'tkt-nyp-0008',
    village_id: 'v-nayapara',
    reason: 'LEAK',
    state: 'ASSIGNED',
    opened_at: leakAt.toISOString(),
    updated_at: leakEvents[leakEvents.length - 1]?.at ?? leakAt.toISOString(),
    events: leakEvents,
    number: 8,
    water_point_id: 'wp-nyp-piped',
    origin: 'voice_note',
    reporters: ['hh-nyp-3'],
    quorum: 1,
    blocker: 'PARTS_NEEDED',
    issue: {
      issue: 'LEAK',
      summary_hi: 'स्कूल के पास पाइप फूटा है; दो दिन से पानी बह रहा है।',
      summary_en: 'A pipe has burst near the school; water has been running to waste for two days.',
      transcript: 'स्कूल के पास वाला पाइप फूटा है, दो दिन से पानी बह रहा है, कोई देखने नहीं आया।',
      location_hint: 'near the school',
      days_affected: 2,
      confidence: 0.86,
      model_id: 'demo (no model call)',
    },
  });

  // #9: a missed call (option 1 on the handpump's family): the handpump is broken.
  const brokenAt = istInstant(yesterday, '17:50');
  const brokenEvents = [
    ev(brokenAt, 'system:report', 'opened', null, 'OPEN', {
      origin: 'report',
      household_id: 'hh-nyp-6',
      digits: '1',
    }),
    ev(istInstant(yesterday, '17:51'), 'system:ticket-flow', 'notified', 'OPEN', 'ASSIGNED', {
      operator_id: 'op-nyp-hpm',
    }),
  ];
  state.tickets.push({
    id: 'tkt-nyp-0009',
    village_id: 'v-nayapara',
    reason: 'BROKEN',
    state: 'ASSIGNED',
    opened_at: brokenAt.toISOString(),
    updated_at: brokenEvents[brokenEvents.length - 1]?.at ?? brokenAt.toISOString(),
    events: brokenEvents,
    number: 9,
    water_point_id: 'wp-nyp-handpump',
    origin: 'report',
    reporters: ['hh-nyp-6'],
    quorum: 1,
    blocker: null,
    issue: null,
  });
  state.ticketSeq = { 'v-nayapara': 9, 'v-amlidih': 3 };
}

function seedConsents(now: Date): ConsentEvent[] {
  const today = istDate(now);
  const at = (daysAgo: number, hhmm: string) => istInstant(addDays(today, -daysAgo), hhmm);
  const nyp = 'v-nayapara';
  const aml = 'v-amlidih';
  return [
    consent(nyp, 'hh-nyp-1', '0412', 'GRANTED', at(30, '10:05'), 'ivr_keypad', '1'),
    consent(nyp, 'hh-nyp-2', '7731', 'GRANTED', at(30, '11:30'), 'in_person', null),
    consent(aml, 'hh-aml-1', '3317', 'GRANTED', at(30, '11:05'), 'ivr_keypad', '1'),
    consent(aml, 'hh-aml-2', '6624', 'GRANTED', at(30, '11:12'), 'ivr_keypad', '1'),
    consent(nyp, 'hh-nyp-3', '2290', 'GRANTED', at(29, '10:12'), 'ivr_keypad', '1'),
    consent(nyp, 'hh-nyp-4', '5108', 'GRANTED', at(29, '12:00'), 'in_person', null),
    consent(aml, 'hh-aml-3', '1185', 'GRANTED', at(28, '12:30'), 'in_person', null),
    consent(nyp, 'hh-nyp-7', '6610', 'GRANTED', at(20, '18:10'), 'ivr_keypad', '1'),
    consent(nyp, 'hh-nyp-10', '5521', 'MINOR', at(12, '17:02'), 'ivr_keypad', '2'),
    consent(nyp, 'hh-nyp-7', '6610', 'WITHDRAWN', at(6, '10:41'), 'ivr_keypad', '9'),
    consent(nyp, 'hh-nyp-9', '2208', 'DECLINED', at(3, '16:20'), 'ivr_keypad', '3'),
    consent(nyp, 'hh-nyp-6', '3359', 'GRANTED', at(1, '17:40'), 'ivr_keypad', '1'),
  ].sort((a, b) => a.at.localeCompare(b.at));
}

function broadcast(
  id: string,
  village: string,
  kind: Broadcast['kind'],
  text: string,
  created: Date,
  extra: Partial<Broadcast> = {},
): Broadcast {
  return {
    id,
    village_id: village,
    water_point_id: null,
    kind,
    text_hi: text,
    state: 'DRAFT',
    created_by: 'console:demo-secretary',
    created_at: created.toISOString(),
    approved_by: null,
    approved_at: null,
    sent_at: null,
    recipients: 0,
    delivered: 0,
    heard: 0,
    ...extra,
  };
}

function seedBroadcasts(now: Date): Broadcast[] {
  const today = istDate(now);
  const at = (daysAgo: number, hhmm: string) => istInstant(addDays(today, -daysAgo), hhmm);
  const sarpanch = 'console:demo-sarpanch';
  return [
    broadcast(
      'bc-demo-aml-1',
      'v-amlidih',
      'BOIL_WATER',
      'गंदे पानी की शिकायत की जाँच होने तक पानी उबालकर पिएँ।',
      at(10, '12:00'),
      {
        state: 'SENT',
        water_point_id: 'wp-aml-piped',
        approved_by: 'console:demo-sarpanch-aml',
        approved_at: at(10, '12:30').toISOString(),
        sent_at: at(10, '13:00').toISOString(),
        recipients: 3,
        delivered: 3,
        heard: 3,
      },
    ),
    broadcast(
      'bc-demo-nyp-1',
      'v-nayapara',
      'SUPPLY_CHANGE',
      'कल पानी सुबह 6:30 से 8:00 बजे तक ही आएगा, टंकी की सफ़ाई होगी।',
      at(3, '09:30'),
      {
        state: 'SENT',
        water_point_id: 'wp-nyp-piped',
        approved_by: sarpanch,
        approved_at: at(3, '10:00').toISOString(),
        sent_at: at(3, '11:00').toISOString(),
        recipients: 4,
        delivered: 4,
        heard: 3,
      },
    ),
    broadcast(
      'bc-demo-nyp-2',
      'v-nayapara',
      'REPAIR_DONE',
      'स्कूल के पास का फूटा पाइप ठीक कराया जा रहा है। पानी न आए तो मिस्ड कॉल दें।',
      at(1, '11:00'),
      {
        state: 'APPROVED',
        approved_by: sarpanch,
        approved_at: at(1, '12:15').toISOString(),
      },
    ),
    broadcast(
      'bc-demo-nyp-3',
      'v-nayapara',
      'MEETING',
      'रविवार सुबह 10 बजे पंचायत भवन में पानी समिति की बैठक है।',
      at(1, '15:00'),
      {
        state: 'APPROVED',
        approved_by: sarpanch,
        approved_at: at(1, '16:10').toISOString(),
      },
    ),
    broadcast(
      'bc-demo-nyp-4',
      'v-nayapara',
      'BOIL_WATER',
      'स्कूल वाले हैंडपंप का पानी जाँच होने तक उबालकर पिएँ।',
      at(1, '18:30'),
      {
        water_point_id: 'wp-nyp-handpump',
      },
    ),
  ];
}

function seedQuality(now: Date): QualityTest[] {
  const today = istDate(now);
  const at = (daysAgo: number, hhmm: string) => istInstant(addDays(today, -daysAgo), hhmm).toISOString();
  const tests: QualityTest[] = [
    {
      id: 'qt-demo-aml-1',
      village_id: 'v-amlidih',
      water_point_id: 'wp-aml-piped',
      tested_at: at(10, '13:00'),
      method: 'FTK',
      result: 'UNSAFE',
      parameters: { 'Turbidity (NTU)': '>10' },
      entered_by: 'console:demo-secretary-aml',
      note: 'Taken during the dirty-water complaint (demo).',
    },
    {
      id: 'qt-demo-aml-2',
      village_id: 'v-amlidih',
      water_point_id: 'wp-aml-piped',
      tested_at: at(8, '10:00'),
      method: 'LAB',
      result: 'SAFE',
      parameters: { pH: '7.1', 'Turbidity (NTU)': '2', 'E. coli': 'Absent' },
      entered_by: 'console:demo-secretary-aml',
      note: 'District lab, after the pipe repair (demo).',
    },
    {
      id: 'qt-demo-nyp-1',
      village_id: 'v-nayapara',
      water_point_id: 'wp-nyp-piped',
      tested_at: at(5, '11:00'),
      method: 'FTK',
      result: 'SAFE',
      parameters: { pH: '7.4', 'Turbidity (NTU)': '<5', 'Residual chlorine (mg/L)': '0.2' },
      entered_by: 'console:demo-secretary',
      note: 'Field test kit at the school tap (demo).',
    },
  ];
  return tests.sort((a, b) => a.tested_at.localeCompare(b.tested_at));
}

function seedOfficial(now: Date): Record<string, OfficialRecord> {
  const asOn = istNoon(addDays(istDate(now), -1));
  const source = demoSource('JJM IMIS / WQMIS public dashboard', now, asOn);
  return {
    'v-nayapara': {
      village_lgd: 'demo-nayapara',
      imis_village_id: 'demo',
      name: 'Nayapara (demo)',
      gram_panchayat: 'Nayapara (demo)',
      households: 128,
      tap_connections: 128,
      hgj_status: 'REPORTED',
      schemes: [
        {
          scheme_id: 'demo-scheme-1',
          name: 'Nayapara single-village scheme (demo)',
          status: 'Completed',
          functional_status: 'Functional',
        },
      ],
      source_type: 'Borewell (groundwater) in village (demo)',
      wq: {
        last_household_test: '2024-02-12',
        household_test_dates: ['2023-09-04', '2024-02-12'],
        last_household_values_date: '2024-02-12',
        last_household_values: {
          pH: '7.1–7.3',
          'TDS (mg/L)': '410–436',
          'Nitrate (mg/L, limit 45)': '31–33',
          Fluoride: '0.4',
        },
        samples_summary: '2 household tap samples (demo), all Safe',
        contamination_flags: [],
        ftk_this_fy: '2026-27',
        ftk_samples_this_fy: 4,
        ftk_note: 'No chlorine test in field test kit samples (demo)',
      },
      source,
    },
    'v-amlidih': {
      village_lgd: 'demo-amlidih',
      imis_village_id: 'demo',
      name: 'Amlidih (demo)',
      gram_panchayat: 'Amlidih (demo)',
      households: 96,
      tap_connections: 91,
      hgj_status: 'CERTIFIED',
      wq: {
        last_household_test: '2025-11-20',
        household_test_dates: ['2025-11-20'],
        last_household_values_date: '2025-11-20',
        last_household_values: { pH: '6.9–7.0', 'Iron (mg/L, limit 1.0)': '0.8–1.4' },
        samples_summary: '3 household tap samples (demo), 1 Not safe',
        contamination_flags: ['FY 2025-26 lab: iron above the limit, 1 sample (demo)'],
      },
      source,
    },
  };
}

function seedActivity(now: Date): ActivityItem[] {
  const y = addDays(istDate(now), -1);
  return [
    {
      at: istInstant(y, '17:40').toISOString(),
      kind: 'consent',
      village_id: 'v-nayapara',
      text_en: 'Nayapara: a family gave a missed call, heard the notice and pressed 1 to agree (demo).',
      text_hi: 'नयापारा: एक परिवार ने मिस्ड कॉल दी, सूचना सुनी और सहमति के लिए 1 दबाया (डेमो)।',
    },
    {
      at: istInstant(y, '17:50').toISOString(),
      kind: 'ticket',
      village_id: 'v-nayapara',
      text_en: 'Nayapara: complaint #9 opened by missed call: the school handpump is broken.',
      text_hi: 'नयापारा: मिस्ड कॉल से शिकायत #9 खुली: स्कूल वाला हैंडपंप ख़राब है।',
    },
    {
      at: istInstant(y, '18:20').toISOString(),
      kind: 'ticket',
      village_id: 'v-nayapara',
      text_en:
        'Nayapara: complaint #8 opened from a resident’s voice note (AI-transcribed, not yet confirmed): leak near the school.',
      text_hi:
        'नयापारा: एक निवासी के आवाज़ संदेश से शिकायत #8 खुली (AI से लिखी, अभी पुष्टि नहीं): स्कूल के पास रिसाव।',
    },
  ];
}

/** Adds the §15 demo records to a seeded store (in place). */
export function seedPanchayat(state: MockState, now: Date): MockState {
  const names: Record<string, { name_hi: string; gp: string; census: number; population: number }> = {
    'v-nayapara': { name_hi: 'नयापारा', gp: 'Nayapara (demo)', census: 131, population: 562 },
    'v-amlidih': { name_hi: 'अमलीडीह', gp: 'Amlidih (demo)', census: 104, population: 455 },
  };
  for (const v of state.villages) {
    const extra = names[v.id];
    if (!extra) continue;
    v.name_hi = extra.name_hi;
    v.gram_panchayat = extra.gp;
    v.census_households = extra.census;
    v.census_population = extra.population;
    v.census_source = demoSource('Census 2011 village directory', now);
    v.lgd_code = null;
  }
  state.operators.push({ ...MECHANIC, village_ids: [...MECHANIC.village_ids] });
  state.waterPoints = POINTS.map((p) => ({ ...p, operator_ids: [...p.operator_ids] }));
  decorateHouseholds(state, now);
  decorateDays(state);
  decorateTickets(state, now);
  state.consents = seedConsents(now);
  state.broadcasts = seedBroadcasts(now);
  state.quality = seedQuality(now);
  state.official = seedOfficial(now);
  state.activity = [...state.activity, ...seedActivity(now)].sort((a, b) => a.at.localeCompare(b.at));
  return state;
}

/** The full demo store the mock API starts from. */
export function seedDemoState(now: Date): MockState {
  return seedPanchayat(seedMockState(now), now);
}
