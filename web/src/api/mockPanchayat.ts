/**
 * Mock-mode Gram Panchayat routes (ARCHITECTURE.md §15.12): water points, adding families,
 * the consent ledger, console complaints, announcements with the Cedar rules the backend applies
 * (sarpanch-only approval, 2 a week, calling hours), water-quality tests, analytics, the weekly
 * summary and the residents' view. No call is ever placed; the activity feed says so.
 */

import { effectiveConsent, isCallable } from '../lib/households';
import { addDays, istDate, istHour, minutesFrom } from '../lib/time';
import { ApiError, type JalApi } from './client';
import { mockAnalytics, mockPublicView, mockWeeklySummary, officialAgeNote } from './mockAnalytics';
import type { MockState } from './mockSeed';
import { DEMO_NOTICE_SHA } from './mockSeedPanchayat';
import type {
  Broadcast,
  HouseholdMasked,
  OperatorRole,
  PolicyDenied,
  QualityTest,
  Ticket,
  TicketEvent,
  Village,
  WaterPoint,
} from './types';
import { ACCESS_KINDS, BROADCAST_KINDS, TICKET_REASONS, WATER_POINT_KINDS } from './types';

export const DPDP_LABEL =
  "Designed to the DPDP Act 2023 / Rules 2025 standard; the Act's consent provisions are in force from May 2027.";

const PHONE = /^\+91\d{10}$/;
const SLUG = /^[a-z0-9-]{1,40}$/;
const WINDOW = /^\d{2}:\d{2}-\d{2}:\d{2}$/;
const WEEKLY_LIMIT = 2;
const MAX_RANGE_DAYS = 92;
const ANALYTICS_DAYS = 30;

export interface PanchayatMockContext {
  state: MockState;
  now: () => Date;
  actor: string;
  /** The console user's Cognito group, as Cedar sees it. */
  role: OperatorRole;
  reply: <T>(fn: () => T) => Promise<T>;
  activity: (kind: string, villageId: string, en: string, hi: string) => void;
}

export type PanchayatApi = Pick<
  JalApi,
  | 'listWaterPoints'
  | 'saveWaterPoint'
  | 'addHousehold'
  | 'getConsents'
  | 'raiseTicket'
  | 'listBroadcasts'
  | 'draftBroadcast'
  | 'approveBroadcast'
  | 'sendBroadcast'
  | 'cancelBroadcast'
  | 'listQuality'
  | 'addQuality'
  | 'getAnalytics'
  | 'getSummary'
  | 'listPublicVillages'
  | 'getPublicVillage'
>;

const DENY: Record<string, PolicyDenied> = {
  sarpanch: {
    denied: true,
    policy_id: 'broadcast-needs-sarpanch',
    reason_en: 'Only the sarpanch can approve an announcement.',
    reason_hi: 'घोषणा को सिर्फ़ सरपंच मंज़ूरी दे सकते हैं।',
  },
  notApproved: {
    denied: true,
    policy_id: 'broadcast-not-approved',
    reason_en: 'The sarpanch has not approved this announcement yet.',
    reason_hi: 'सरपंच ने अभी इस घोषणा को मंज़ूरी नहीं दी है।',
  },
  weekly: {
    denied: true,
    policy_id: 'broadcast-weekly-limit',
    reason_en: 'At most 2 announcements a week can be sent to the village.',
    reason_hi: 'गाँव में हफ़्ते में ज़्यादा से ज़्यादा 2 घोषणाएँ भेजी जा सकती हैं।',
  },
  hours: {
    denied: true,
    policy_id: 'calling-hours',
    reason_en: 'This call is not allowed right now.',
    reason_hi: 'अभी यह कॉल नहीं हो सकती।',
  },
};

const invalid = (message: string) => new ApiError(400, 'invalid_request', message);
const conflict = (message: string) => new ApiError(409, 'conflict', message);

/** FNV-1a: a stable demo household id for a number, without keeping the number. */
function phoneId(phone: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < phone.length; i += 1) {
    h ^= phone.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `hh-${h.toString(16).padStart(8, '0')}`;
}

export function createPanchayatMock(ctx: PanchayatMockContext): PanchayatApi {
  const { state, now, reply } = ctx;
  let seq = 0;

  function village(vid: string): Village {
    const v = state.villages.find((x) => x.id === vid);
    if (!v) throw new ApiError(404, 'not_found', `No village with id "${vid}".`);
    return v;
  }

  function knownPoint(vid: string, raw: string | null | undefined): string | null {
    if (!raw) return null;
    if (!state.waterPoints.some((p) => p.village_id === vid && p.id === raw)) {
      throw invalid(`unknown water point '${raw}'`);
    }
    return raw;
  }

  function findBroadcast(vid: string, bid: string): Broadcast {
    const b = state.broadcasts.find((x) => x.village_id === vid && x.id === bid);
    if (!b) throw new ApiError(404, 'not_found', `announcement '${bid}' not found`);
    return b;
  }

  function sentLastWeek(vid: string): number {
    const since = now().getTime() - 7 * 86_400_000;
    return state.broadcasts.filter(
      (b) => b.village_id === vid && b.state === 'SENT' && b.sent_at && Date.parse(b.sent_at) >= since,
    ).length;
  }

  function addEvent(ticket: Ticket, event: TicketEvent): void {
    ticket.events.push(event);
    if (event.to_state) ticket.state = event.to_state;
    ticket.updated_at = event.at;
  }

  function routeOperator(vid: string, wpid: string | null): string | null {
    const point = state.waterPoints.find((p) => p.id === wpid);
    if (point?.operator_ids[0]) return point.operator_ids[0];
    const ops = state.operators.filter((o) => o.village_ids.includes(vid));
    return (
      (ops.find((o) => o.role === 'NAL_JAL_MITRA') ?? ops.find((o) => o.role === 'SARPANCH'))?.id ?? null
    );
  }

  function period(vid: string, from?: string, to?: string): { start: string; end: string } {
    const end = to || istDate(now());
    const start = from || addDays(end, -(ANALYTICS_DAYS - 1));
    if (start > end) throw invalid('from must not be after to');
    if (addDays(start, MAX_RANGE_DAYS) <= end) throw invalid(`at most ${MAX_RANGE_DAYS} days per request`);
    village(vid);
    return { start, end };
  }

  return {
    listWaterPoints: (vid) =>
      reply(() => {
        village(vid);
        return state.waterPoints.filter((p) => p.village_id === vid);
      }),

    saveWaterPoint: (vid, input) =>
      reply(() => {
        village(vid);
        seq += 1;
        const id = input.id || `wp-${now().getTime().toString(36).slice(-5)}${seq}`;
        if (!SLUG.test(id)) throw invalid('id must be lowercase letters, digits or -');
        const existing = state.waterPoints.find((p) => p.village_id === vid && p.id === id);
        const kind = input.kind ?? existing?.kind ?? 'PIPED';
        if (!(WATER_POINT_KINDS as readonly string[]).includes(kind)) throw invalid(`unknown kind '${kind}'`);
        const window = input.supply_window || existing?.supply_window || null;
        if (window && !WINDOW.test(window)) throw invalid('supply_window must look like 06:30-08:00');
        const point: WaterPoint = {
          id,
          village_id: vid,
          kind,
          name: input.name || existing?.name || id,
          name_hi: input.name_hi || existing?.name_hi || null,
          hamlet: input.hamlet || existing?.hamlet || null,
          supply_window: window,
          operator_ids: input.operator_ids ?? existing?.operator_ids ?? [],
          quorum: input.quorum || existing?.quorum || null,
          location: existing?.location ?? null,
          provisional: false,
          active: input.active ?? existing?.active ?? true,
        };
        if (existing) Object.assign(existing, point);
        else state.waterPoints.push(point);
        return point;
      }),

    addHousehold: (vid, request) =>
      reply(() => {
        village(vid);
        const phone = String(request.phone ?? '').replace(/\s+/g, '');
        if (!PHONE.test(phone)) throw invalid('phone must look like +91XXXXXXXXXX');
        if (request.access && !(ACCESS_KINDS as readonly string[]).includes(request.access)) {
          throw invalid(`unknown access '${request.access}'`);
        }
        const id = phoneId(phone);
        const existing = state.households.find((h) => h.village_id === vid && h.id === id);
        if (existing && effectiveConsent(existing) === 'GRANTED')
          return { household: existing, call: 'none' as const };
        if (existing && effectiveConsent(existing) === 'DECLINED') {
          throw new ApiError(409, 'consent_declined', 'this family declined JalSakshi calls');
        }
        const masked = `+91XXXXXX${phone.slice(-4)}`;
        const household: HouseholdMasked = {
          id,
          village_id: vid,
          phone_masked: masked,
          display_name: request.display_name?.trim() || null,
          language: 'hi',
          call_window: '09:00-20:00',
          consent: null,
          consent_status: 'NONE',
          access: request.access ?? null,
          water_point_id: null,
          registered_via: 'console',
          active: true,
        };
        if (existing) Object.assign(existing, household);
        else state.households.push(household);
        const call = request.call === false ? ('none' as const) : ('queued' as const);
        ctx.activity(
          'consent',
          vid,
          `Secretary added a family (${masked}); consent call ${call} (demo: no real call is placed).`,
          `सचिव ने एक परिवार जोड़ा (${masked}); सहमति कॉल: ${call} (डेमो: कोई असली कॉल नहीं)।`,
        );
        return { household, call };
      }),

    getConsents: (vid) =>
      reply(() => {
        village(vid);
        return {
          events: state.consents.filter((e) => e.village_id === vid).sort((a, b) => a.at.localeCompare(b.at)),
          notice_version: 'hi-1',
          notice_sha256: DEMO_NOTICE_SHA,
          label: DPDP_LABEL,
        };
      }),

    raiseTicket: (vid, request) =>
      reply(() => {
        const v = village(vid);
        if (!(TICKET_REASONS as readonly string[]).includes(request.reason)) {
          throw invalid(`unknown reason '${String(request.reason)}'`);
        }
        const household = state.households.find((h) => h.village_id === vid && h.id === request.household_id);
        if (!household) throw new ApiError(422, 'household_required', 'pick the family that reported it');
        const wpid = household.water_point_id ?? null;
        const at = now();
        const open = state.tickets.find(
          (t) =>
            t.village_id === vid &&
            t.state !== 'CLOSED_VERIFIED' &&
            (t.water_point_id ?? null) === wpid &&
            t.reason === request.reason,
        );
        if (open) {
          if (!(open.reporters ?? []).includes(household.id)) {
            open.reporters = [...(open.reporters ?? []), household.id];
          }
          addEvent(open, {
            at: at.toISOString(),
            actor: ctx.actor,
            kind: 'NOTE',
            from_state: null,
            to_state: null,
            detail: { note: 'another_report', household_id: household.id },
          });
          return open;
        }
        const number = (state.ticketSeq[vid] ?? 0) + 1;
        state.ticketSeq[vid] = number;
        const pointQuorum = state.waterPoints.find((p) => p.id === wpid)?.quorum ?? v.quorum;
        const ticket: Ticket = {
          id: `tkt-${vid.replace(/^v-/, '').slice(0, 3)}-${String(number).padStart(4, '0')}`,
          village_id: vid,
          reason: request.reason,
          state: 'OPEN',
          opened_at: at.toISOString(),
          updated_at: at.toISOString(),
          events: [],
          number,
          water_point_id: wpid,
          origin: 'console',
          reporters: [household.id],
          quorum: Math.min(pointQuorum, 1),
          issue: null,
          blocker: null,
        };
        addEvent(ticket, {
          at: at.toISOString(),
          actor: ctx.actor,
          kind: 'opened',
          from_state: null,
          to_state: 'OPEN',
          detail: { origin: 'console', household_id: household.id },
        });
        addEvent(ticket, {
          at: minutesFrom(at, 0.05).toISOString(),
          actor: 'system:ticket-flow',
          kind: 'notified',
          from_state: 'OPEN',
          to_state: 'ASSIGNED',
          detail: { operator_id: routeOperator(vid, wpid) },
        });
        state.tickets.push(ticket);
        ctx.activity(
          'ticket',
          vid,
          `Complaint #${number} raised at the Panchayat office. Calling the operator (demo: no real call).`,
          `पंचायत कार्यालय में शिकायत #${number} दर्ज। ज़िम्मेदार व्यक्ति को कॉल (डेमो: कोई असली कॉल नहीं)।`,
        );
        return ticket;
      }),

    listBroadcasts: (vid) =>
      reply(() => {
        village(vid);
        return {
          broadcasts: state.broadcasts
            .filter((b) => b.village_id === vid)
            .sort((a, b) => a.created_at.localeCompare(b.created_at)),
          sent_last_7_days: sentLastWeek(vid),
          weekly_limit: WEEKLY_LIMIT,
        };
      }),

    draftBroadcast: (vid, request) =>
      reply(() => {
        village(vid);
        const text = String(request.text_hi ?? '').trim();
        if (text.length < 1 || text.length > 400) throw invalid('text_hi must be 1-400 characters');
        const kind = request.kind || 'CUSTOM';
        if (!(BROADCAST_KINDS as readonly string[]).includes(kind)) throw invalid(`unknown kind '${kind}'`);
        seq += 1;
        const draft: Broadcast = {
          id: `bc-demo-${now().getTime().toString(36)}-${seq}`,
          village_id: vid,
          water_point_id: knownPoint(vid, request.water_point_id),
          kind,
          text_hi: text,
          state: 'DRAFT',
          created_by: ctx.actor,
          created_at: now().toISOString(),
          approved_by: null,
          approved_at: null,
          sent_at: null,
          recipients: 0,
          delivered: 0,
          heard: 0,
        };
        state.broadcasts.push(draft);
        ctx.activity(
          'broadcast',
          vid,
          `Announcement drafted (${kind}); waiting for the sarpanch`,
          'घोषणा का मसौदा बना; सरपंच की मंज़ूरी बाकी',
        );
        return draft;
      }),

    approveBroadcast: (vid, bid) =>
      reply(() => {
        const b = findBroadcast(vid, bid);
        if (b.state !== 'DRAFT') throw conflict(`announcement is ${b.state}, not DRAFT`);
        if (ctx.role !== 'SARPANCH') {
          ctx.activity(
            'policy_denied',
            vid,
            `Cedar broadcast-needs-sarpanch: ${DENY.sarpanch?.reason_en}`,
            `नियम ने रोका: ${DENY.sarpanch?.reason_hi}`,
          );
          return { ok: false as const, denied: DENY.sarpanch as PolicyDenied };
        }
        Object.assign(b, { state: 'APPROVED', approved_by: ctx.actor, approved_at: now().toISOString() });
        ctx.activity(
          'broadcast',
          vid,
          'The sarpanch approved an announcement',
          'सरपंच ने घोषणा को मंज़ूरी दी',
        );
        return { ok: true as const, value: b };
      }),

    sendBroadcast: (vid, bid) =>
      reply(() => {
        const b = findBroadcast(vid, bid);
        const hour = istHour(now());
        let denied: PolicyDenied | null = null;
        if (b.state !== 'APPROVED') denied = DENY.notApproved as PolicyDenied;
        else if (sentLastWeek(vid) >= WEEKLY_LIMIT) denied = DENY.weekly as PolicyDenied;
        else if (hour < 9 || hour >= 21) denied = DENY.hours as PolicyDenied;
        if (denied) {
          ctx.activity(
            'policy_denied',
            vid,
            `Cedar ${denied.policy_id}: ${denied.reason_en}`,
            `नियम ने रोका: ${denied.reason_hi}`,
          );
          return { ok: false as const, denied };
        }
        const before = { ...b };
        const recipients = state.households.filter(
          (h) =>
            h.village_id === vid &&
            isCallable(h) &&
            (!b.water_point_id || h.water_point_id === b.water_point_id),
        ).length;
        Object.assign(b, { state: 'SENT', sent_at: now().toISOString(), recipients });
        ctx.activity(
          'broadcast',
          vid,
          `Announcement sent to ${recipients} families (demo: no real calls are placed).`,
          `घोषणा ${recipients} परिवारों को भेजी गई (डेमो: कोई असली कॉल नहीं)।`,
        );
        return { ok: true as const, value: { ...before, queued: true } };
      }),

    cancelBroadcast: (vid, bid) =>
      reply(() => {
        const b = findBroadcast(vid, bid);
        if (b.state === 'SENT') throw conflict('a sent announcement cannot be cancelled');
        b.state = 'CANCELLED';
        return b;
      }),

    listQuality: (vid) =>
      reply(() => {
        village(vid);
        const official = state.official[vid] ?? null;
        return {
          tests: state.quality
            .filter((q) => q.village_id === vid)
            .sort((a, b) => a.tested_at.localeCompare(b.tested_at)),
          official,
          official_note: official ? officialAgeNote(official, now()) : null,
        };
      }),

    addQuality: (vid, request) =>
      reply(() => {
        village(vid);
        if (request.result !== 'SAFE' && request.result !== 'UNSAFE') throw invalid('unknown result');
        const method = request.method || 'FTK';
        if (method !== 'FTK' && method !== 'LAB') throw invalid('unknown method');
        const testedAt = request.tested_at ? new Date(request.tested_at) : now();
        if (Number.isNaN(testedAt.getTime())) throw invalid('tested_at must be an ISO time');
        seq += 1;
        const test: QualityTest = {
          id: `qt-demo-${now().getTime().toString(36)}-${seq}`,
          village_id: vid,
          water_point_id: knownPoint(vid, request.water_point_id),
          tested_at: testedAt.toISOString(),
          method,
          result: request.result,
          parameters: Object.fromEntries(
            Object.entries(request.parameters ?? {}).map(([k, v]) => [String(k), String(v)]),
          ),
          entered_by: ctx.actor,
          note: request.note?.trim() || null,
        };
        state.quality.push(test);
        const dirty = state.tickets.find(
          (t) =>
            t.village_id === vid &&
            t.reason === 'DIRTY' &&
            t.state !== 'CLOSED_VERIFIED' &&
            (t.water_point_id ?? null) === (test.water_point_id ?? null),
        );
        if (dirty) {
          addEvent(dirty, {
            at: now().toISOString(),
            actor: ctx.actor,
            kind: 'NOTE',
            from_state: null,
            to_state: null,
            detail: { note: 'quality_test', result: test.result, method: test.method },
          });
        }
        return test;
      }),

    getAnalytics: (vid, from, to) =>
      reply(() => {
        const { start, end } = period(vid, from, to);
        return mockAnalytics(state, village(vid), start, end, now());
      }),

    getSummary: (vid) =>
      reply(() => {
        const v = village(vid);
        const end = istDate(now());
        const analytics = mockAnalytics(state, v, addDays(end, -6), end, now());
        return mockWeeklySummary(
          v,
          analytics,
          state.waterPoints.filter((p) => p.village_id === vid),
        );
      }),

    listPublicVillages: () =>
      reply(() =>
        state.villages
          .filter((v) => v.active)
          .map((v) => ({ id: v.id, name: v.name, name_hi: v.name_hi ?? null, lgd_code: v.lgd_code ?? null })),
      ),

    getPublicVillage: (vid) =>
      reply(() => {
        const v = state.villages.find((x) => x.id === vid && x.active);
        if (!v) throw new ApiError(404, 'not_found', `No village with id "${vid}".`);
        return mockPublicView(state, v, now());
      }),
  };
}
