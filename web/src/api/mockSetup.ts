/**
 * Mock mode: the sample village (id "sample-village", 30 days of generated history) and the
 * first-time setup endpoints (§16): places, create village, team, bulk add families.
 */

import { addDays, istDate } from '../lib/time';
import { maskMobile, normaliseMobile } from '../lib/phones';
import { ApiError } from './client';
import type { MockState } from './mockSeed';
import { seedDemoState } from './mockSeedPanchayat';
import type {
  BulkAddResponse,
  CallLanguage,
  CreatePanchayatRequest,
  CreatePanchayatResponse,
  CreateVillageRequest,
  FamilyRow,
  RegisterPhotoResponse,
  RegisterRow,
  VillageSettings,
  DayStatus,
  DayStatusValue,
  HouseholdMasked,
  Operator,
  OperatorRole,
  Person,
  Place,
  TeamRole,
  Ticket,
  Village,
} from './types';

export const SAMPLE_ID = 'sample-village';
const OLD_ID = 'v-nayapara';
const DROP_ID = 'v-amlidih';
const HISTORY_DAYS = 30;
const SAMPLE_AREAS: Array<string | null> = ['Thakur para', 'Schoolpara', 'Harijan mohalla', 'Thakur para', null];
const MAX_PENDING = 25;

/** Known villages offered in setup (a small slice of the LGD list). */
export const MOCK_PLACES: Place[] = [
  { lgd_code: '442569', name: 'Kharkhara', name_hi: 'खरखरा', gram_panchayat: 'Kharkhara', block: 'Patan', district: 'Durg', census_households: 212 },
  { lgd_code: '442571', name: 'Kopedih', name_hi: 'कोपेडीह', gram_panchayat: 'Kopedih', block: 'Patan', district: 'Durg', census_households: 148 },
  { lgd_code: '442580', name: 'Selud', name_hi: 'सेलूद', gram_panchayat: 'Selud', block: 'Patan', district: 'Durg', census_households: 389 },
  { lgd_code: '441902', name: 'Arjunda', name_hi: 'अर्जुंदा', gram_panchayat: 'Arjunda', block: 'Gunderdehi', district: 'Balod', census_households: 520 },
  { lgd_code: '441915', name: 'Dhaba', name_hi: 'ढाबा', gram_panchayat: 'Dhaba', block: 'Gunderdehi', district: 'Balod', census_households: 176 },
];

/** Call languages; recordings exist for Hindi and Chhattisgarhi. */
export const MOCK_LANGUAGES: CallLanguage[] = [
  { code: 'hi', name: 'Hindi', ready: true },
  { code: 'hne', name: 'Chhattisgarhi', ready: true },
  { code: 'te', name: 'Telugu', ready: false },
  { code: 'mr', name: 'Marathi', ready: false },
  { code: 'or', name: 'Odia', ready: false },
  { code: 'bn', name: 'Bengali', ready: false },
  { code: 'gu', name: 'Gujarati', ready: false },
  { code: 'kn', name: 'Kannada', ready: false },
  { code: 'ml', name: 'Malayalam', ready: false },
  { code: 'pa', name: 'Punjabi', ready: false },
  { code: 'ta', name: 'Tamil', ready: false },
];

/** What the register reader returns in mock mode: four rows, one number unreadable. */
export const MOCK_REGISTER_ROWS: RegisterRow[] = [
  { name: 'Ramesh Sahu', phone: '+919826012345', area: 'Thakur para', phone_ok: true },
  { name: 'Sunita Verma', phone: '+917987654321', area: 'Thakur para', phone_ok: true },
  { name: 'Gita Bai', phone: '98261 234', area: 'Harijan mohalla', phone_ok: false },
  { name: 'Mohan Lal Yadav', phone: '+916260112233', area: null, phone_ok: true },
];

const TEAM: Record<TeamRole, OperatorRole> = {
  operator: 'NAL_JAL_MITRA',
  sarpanch: 'SARPANCH',
  secretary: 'PANCHAYAT_SECRETARY',
};

/** Rough weekly pattern for generated older days: mostly water, a few bad days. */
const PATTERN: DayStatusValue[] = ['SUPPLIED', 'SUPPLIED', 'PARTIAL', 'SUPPLIED', 'SUPPLIED', 'NO_SUPPLY', 'SUPPLIED'];

/** The demo store with one sample village: renamed, 30 days long, 5 complaints. */
export function seedSampleState(now: Date): MockState {
  const raw = JSON.stringify(seedDemoState(now))
    .replaceAll(OLD_ID, SAMPLE_ID)
    .replaceAll('नयापारा', 'नमूना गाँव')
    .replaceAll('Nayapara (demo)', 'Sample Gram Panchayat')
    .replaceAll('Nayapara', 'Sample village')
    .replaceAll(' (demo)', '')
    .replaceAll(' (डेमो)', '');
  const state = JSON.parse(raw) as MockState;
  const keep = <T extends { village_id: string }>(rows: T[]) => rows.filter((r) => r.village_id !== DROP_ID);
  state.villages = state.villages.filter((v) => v.id !== DROP_ID);
  state.households = keep(state.households);
  state.days = keep(state.days);
  state.checkins = keep(state.checkins);
  state.tickets = keep(state.tickets);
  state.waterPoints = keep(state.waterPoints);
  state.consents = keep(state.consents);
  state.broadcasts = keep(state.broadcasts);
  state.quality = keep(state.quality);
  state.activity = state.activity.filter((a) => a.village_id !== DROP_ID);
  delete state.official[DROP_ID];
  delete state.context[DROP_ID];
  state.operators = state.operators
    .map((o) => ({ ...o, village_ids: o.village_ids.filter((v) => v !== DROP_ID) }))
    .filter((o) => o.village_ids.length > 0);
  const village = state.villages.find((v) => v.id === SAMPLE_ID);
  if (village) {
    village.name = 'Sample village';
    village.name_hi = 'नमूना गाँव';
    village.checkin_local_time = '19:00';
    village.languages = ['hi', 'hne'];
    // Areas (mohalla/para) as families said them on their first call; one did not say.
    state.households
      .filter((h) => h.village_id === SAMPLE_ID)
      .forEach((h, i) => {
        h.hamlet ??= SAMPLE_AREAS[i % SAMPLE_AREAS.length] ?? null;
        if (i % 4 === 1) h.language = 'hne';
      });
    extendHistory(state, now);
    addClosedComplaints(state, village, now);
  }
  return state;
}

function extendHistory(state: MockState, now: Date): void {
  const today = istDate(now);
  const own = state.days.filter((d) => d.village_id === SAMPLE_ID).sort((a, b) => a.date.localeCompare(b.date));
  const template = own[0];
  if (!template) return;
  const have = new Set(own.map((d) => d.date));
  for (let i = HISTORY_DAYS - 1; i >= 1; i -= 1) {
    const date = addDays(today, -i);
    if (have.has(date)) continue;
    const status = PATTERN[i % PATTERN.length] ?? 'SUPPLIED';
    const yes = status === 'SUPPLIED' ? 4 : status === 'PARTIAL' ? 2 : 0;
    const no = status === 'NO_SUPPLY' ? 3 : status === 'PARTIAL' ? 1 : 0;
    const partial = status === 'PARTIAL' ? 1 : 0;
    const counts = { answered: yes + no + partial, yes, no, partial, dirty: 0, unreachable: 4 - (yes + no + partial) > 0 ? 1 : 0 };
    const day: DayStatus = {
      ...template,
      date,
      status,
      counts,
      computed_at: `${date}T13:46:00.000Z`,
      points: (template.points ?? []).map((p) => ({ ...p, status, counts })),
    };
    state.days.push(day);
  }
  state.days.sort((a, b) => a.date.localeCompare(b.date));
}

/** Older, already confirmed repairs so the sample has 5 complaints in all. */
function addClosedComplaints(state: MockState, village: Village, now: Date): void {
  const today = istDate(now);
  const own = () => state.tickets.filter((t) => t.village_id === village.id);
  const reasons: Ticket['reason'][] = ['NO_SUPPLY', 'LEAK', 'DIRTY', 'BROKEN'];
  let n = 1;
  while (own().length < 5) {
    const opened = addDays(today, -(n * 6 - 2));
    const closed = addDays(opened, 1);
    const reason = reasons[n % reasons.length] ?? 'NO_SUPPLY';
    const point = state.waterPoints.find((p) => p.village_id === village.id);
    state.tickets.push({
      id: `tkt-sample-old-${n}`,
      village_id: village.id,
      number: n,
      reason,
      state: 'CLOSED_VERIFIED',
      opened_at: `${opened}T14:10:00.000Z`,
      updated_at: `${closed}T13:50:00.000Z`,
      origin: 'reconcile',
      water_point_id: point?.id ?? null,
      reporters: ['hh-a', 'hh-b'],
      quorum: 2,
      events: [
        { at: `${opened}T14:10:00.000Z`, actor: 'system:reconcile', kind: 'opened', from_state: null, to_state: 'OPEN', detail: {} },
        { at: `${opened}T14:11:00.000Z`, actor: 'system:ticket-flow', kind: 'notified', from_state: 'OPEN', to_state: 'ASSIGNED', detail: {} },
        { at: `${closed}T06:30:00.000Z`, actor: 'operator:op', kind: 'operator_fixed', from_state: 'ASSIGNED', to_state: 'OPERATOR_REPORTED_FIXED', detail: {} },
        { at: `${closed}T13:40:00.000Z`, actor: 'system:verify', kind: 'verify_started', from_state: 'OPERATOR_REPORTED_FIXED', to_state: 'VERIFYING', detail: {} },
        { at: `${closed}T13:50:00.000Z`, actor: 'system:verify', kind: 'closed_verified', from_state: 'VERIFYING', to_state: 'CLOSED_VERIFIED', detail: { verify_yes: 2, quorum: 2 } },
      ],
    });
    n += 1;
  }
}

export interface SetupMockContext {
  state: MockState;
  /** Villages bound to this account; null = admin (sees all). */
  bound: string[] | null;
  reply: <T>(fn: () => T) => Promise<T>;
}

function invalid(message: string): ApiError {
  return new ApiError(400, 'invalid_request', message);
}

function phoneOf(person: Person): string {
  const phone = normaliseMobile(person.phone);
  if (!phone) throw invalid('enter a 10-digit mobile number');
  return phone;
}

function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 30) || 'village';
}

/** The §16 endpoints over the mock store. */
export function createSetupMock(ctx: SetupMockContext) {
  const { state, reply } = ctx;

  function findVillage(vid: string): Village {
    const v = state.villages.find((x) => x.id === vid);
    if (!v) throw new ApiError(404, 'not_found', `No village with id "${vid}".`);
    return v;
  }

  function putTeam(village: Village, role: TeamRole, person: Person): Operator {
    const phone = phoneOf(person);
    const id = `op-${village.id}-${role}`;
    const existing = state.operators.find((o) => o.id === id);
    const op: Operator = {
      id,
      role: TEAM[role],
      phone_e164: phone,
      display_name: person.name.trim() || null,
      village_ids: [village.id],
    };
    if (existing) Object.assign(existing, op);
    else state.operators.push(op);
    return { ...op, phone_e164: maskMobile(phone) };
  }

  const logins = new Set<string>();

  function addRows(vid: string, rows: FamilyRow[]): BulkAddResponse {
    const village = findVillage(vid);
    const added: HouseholdMasked[] = [];
    const skipped: BulkAddResponse['skipped'] = [];
    const pending = state.households.filter(
      (h) => h.village_id === vid && h.registered_via === 'console' && (h.consent_status ?? 'NONE') === 'NONE',
    ).length;
    let budget = MAX_PENDING - pending;
    for (const row of rows) {
      const phone = normaliseMobile(row.phone);
      if (!phone) {
        if (row.phone.trim()) skipped.push({ input: row.phone.trim().slice(0, 20), why: 'not a mobile number' });
        continue;
      }
      const masked = maskMobile(phone);
      const id = `hh-${vid}-${phone.slice(-6)}`;
      const same = state.households.find((h) => h.village_id === vid && h.id === id);
      if (same) {
        skipped.push({ input: masked, why: `already added (${same.consent_status ?? 'NONE'})` });
        continue;
      }
      if (budget <= 0) {
        skipped.push({ input: masked, why: '25 families are already waiting for their call' });
        continue;
      }
      const household: HouseholdMasked = {
        id,
        village_id: vid,
        phone_masked: masked,
        display_name: row.name?.trim() || null,
        hamlet: row.area?.trim() || null,
        language: village.languages?.[0] ?? 'hi',
        call_window: '09:00-21:00',
        consent_status: 'NONE',
        registered_via: 'console',
        active: true,
      };
      state.households.push(household);
      added.push(household);
      budget -= 1;
    }
    return { added, skipped };
  }

  return {
    listPlaces: (q?: string) =>
      reply(() => {
        const needle = (q ?? '').trim().toLowerCase();
        return MOCK_PLACES.filter(
          (p) => !needle || p.name.toLowerCase().includes(needle) || (p.name_hi ?? '').includes(needle),
        );
      }),

    createVillage: (request: CreateVillageRequest) =>
      reply(() => {
        const known = 'lgd_code' in request ? MOCK_PLACES.find((p) => p.lgd_code === request.lgd_code) : undefined;
        const name = known?.name ?? ('name' in request ? request.name.trim() : '');
        if (!name) throw invalid('village name is required');
        phoneOf(request.operator);
        if (request.sarpanch?.phone) phoneOf(request.sarpanch);
        const id = known ? `lgd-${known.lgd_code}` : `v-${slug(name)}`;
        let village = state.villages.find((v) => v.id === id);
        if (!village) {
          village = {
            id,
            name,
            name_hi: known?.name_hi ?? ('name_hi' in request ? request.name_hi || null : null),
            gram_panchayat: known?.gram_panchayat ?? ('gram_panchayat' in request ? request.gram_panchayat || null : null),
            block: known?.block ?? ('block' in request ? request.block || '-' : '-'),
            district: known?.district ?? ('district' in request ? request.district || '-' : '-'),
            lgd_code: known?.lgd_code ?? null,
            census_households: known?.census_households ?? null,
            checkin_local_time: '19:00',
            quorum: 2,
            active: true,
          };
          state.villages.push(village);
        }
        if (ctx.bound && !ctx.bound.includes(id)) ctx.bound.push(id);
        putTeam(village, 'operator', request.operator);
        if (request.sarpanch?.phone) putTeam(village, 'sarpanch', request.sarpanch);
        return village;
      }),

    getTeam: (vid: string) =>
      reply(() => {
        findVillage(vid);
        return state.operators
          .filter((o) => o.village_ids.includes(vid))
          .map((o) => ({ ...o, phone_e164: maskMobile(o.phone_e164) }));
      }),

    saveTeamMember: (vid: string, role: TeamRole, person: Person) =>
      reply(() => {
        if (!(role in TEAM)) throw invalid('role must be operator, sarpanch or secretary');
        return putTeam(findVillage(vid), role, person);
      }),


    addHouseholdsBulk: (vid: string, phones: string | string[]) =>
      reply(() => addRows(vid, (Array.isArray(phones) ? phones : phones.split('\n')).map((phone) => ({ phone })))),

    addFamilies: (vid: string, families: FamilyRow[]) => reply(() => addRows(vid, families)),

    callAgain: (vid: string, hid: string) =>
      reply((): { call: 'queued' } => {
        findVillage(vid);
        const h = state.households.find((x) => x.village_id === vid && x.id === hid);
        if (!h) throw invalid('no such family in this village');
        if ((h.consent_status ?? 'NONE') !== 'NONE') throw invalid('this family is not waiting for a call');
        return { call: 'queued' };
      }),

    readRegisterPhoto: (vid: string, imageBase64: string) =>
      reply((): RegisterPhotoResponse => {
        findVillage(vid);
        if (!imageBase64) throw invalid('image_base64 is not valid base64');
        return {
          rows: MOCK_REGISTER_ROWS.map((r) => ({ ...r })),
          model_id: 'mock',
          note: 'Read by AI from the photo. Check every number before adding.',
        };
      }),

    listLanguages: () => reply((): CallLanguage[] => MOCK_LANGUAGES.map((l) => ({ ...l }))),

    saveVillageSettings: (vid: string, settings: VillageSettings) =>
      reply((): Village => {
        const village = findVillage(vid);
        if (settings.languages) {
          const codes = [...new Set(settings.languages.map((c) => c.toLowerCase()))];
          const bad = codes.filter((c) => !MOCK_LANGUAGES.some((l) => l.code === c));
          if (codes.length === 0 || bad.length) throw invalid(`unknown call language: ${bad.join(', ') || 'none'}`);
          village.languages = codes;
        }
        if (settings.checkin_local_time) village.checkin_local_time = settings.checkin_local_time;
        return { ...village };
      }),

    createPanchayat: (request: CreatePanchayatRequest) =>
      reply((): CreatePanchayatResponse => {
        if (ctx.bound !== null) throw new ApiError(403, 'forbidden', 'only the JalSakshi team can set up a Panchayat');
        const username = request.username.trim().toLowerCase();
        if (!/^[a-z0-9._-]{3,30}$/.test(username)) throw invalid('username: 3-30 letters, digits, . _ or -');
        if (logins.has(username)) throw new ApiError(409, 'conflict', 'that username is taken');
        const v = request.village;
        const known = 'lgd_code' in v ? MOCK_PLACES.find((p) => p.lgd_code === v.lgd_code) : undefined;
        const name = known?.name ?? ('name' in v ? v.name.trim() : '');
        if (!name) throw invalid('village name is required');
        phoneOf(request.operator);
        for (const p of [request.sarpanch, request.secretary]) if (p?.phone) phoneOf(p);
        const id = known ? `lgd-${known.lgd_code}` : `v-${slug(name)}`;
        const languages = request.languages.filter((c) => MOCK_LANGUAGES.some((l) => l.code === c));
        let village = state.villages.find((x) => x.id === id);
        if (!village) {
          village = {
            id,
            name,
            name_hi: known?.name_hi ?? null,
            gram_panchayat: known?.gram_panchayat ?? ('gram_panchayat' in v ? v.gram_panchayat || null : null),
            block: known?.block ?? ('block' in v ? v.block || '-' : '-'),
            district: known?.district ?? ('district' in v ? v.district || '-' : '-'),
            lgd_code: known?.lgd_code ?? null,
            census_households: known?.census_households ?? null,
            checkin_local_time: '19:00',
            quorum: 2,
            active: true,
          };
          state.villages.push(village);
        }
        village.languages = languages.length ? languages : ['hi'];
        putTeam(village, 'operator', request.operator);
        if (request.sarpanch?.phone) putTeam(village, 'sarpanch', request.sarpanch);
        if (request.secretary?.phone) putTeam(village, 'secretary', request.secretary);
        const password =
          request.temporary_password || `Jal-${Math.random().toString(36).slice(2, 8)}-${Math.floor(10 + Math.random() * 89)}`;
        logins.add(username);
        return {
          username,
          temporary_password: password,
          village: { ...village },
          note: 'Share the password privately; it must be changed at first sign-in.',
        };
      }),
  };
}
