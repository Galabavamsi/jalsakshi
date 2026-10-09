/**
 * In-memory implementation of JalApi for VITE_API_MODE=mock. No network, no AWS.
 *
 * It behaves like the real API where the console can see it: Cedar denies come back as 403-style
 * results, simulator calls run a small IVR that records check-ins, recomputes today's status with
 * the r1 rule, and opens or verifies tickets. All data is labelled demo.
 */

import { effectiveConsent, isCallable } from '../lib/households';
import { addDays, istDate, minutesFrom } from '../lib/time';
import { ApiError, PolicyDeniedError, type JalApi } from './client';
import { officialAgeNote } from './mockAnalytics';
import { buildMockBrief } from './mockBrief';
import { startIvr, stepIvr, type IvrSession, type OperatorSummary } from './mockIvr';
import { createPanchayatMock } from './mockPanchayat';
import { dayStatusFrom, type MockState } from './mockSeed';
import { createSetupMock, seedSampleState } from './mockSetup';
import type {
  ActivityItem,
  CheckInMasked,
  DayStatus,
  IsoDate,
  Me,
  Observed7d,
  Operator,
  OperatorRole,
  PolicyDenied,
  Purpose,
  SimInputRequest,
  SimStartRequest,
  NextStep,
  Ticket,
  TicketEvent,
  TicketOverview,
  TicketState,
  Village,
  VillageSummary,
} from './types';

export interface MockApiOptions {
  /** Clock, injectable for tests. */
  now?: () => Date;
  /** Artificial delay per call, so loading states are visible in the browser. */
  latencyMs?: number;
  /** Pre-built store; defaults to the seeded demo data. */
  state?: MockState;
  /** Who the console user is, as written into ticket events. */
  actor?: string;
  /** The console user's role for Cedar checks (default: Panchayat Secretary, like the API). */
  role?: OperatorRole;
  /** 'admin' sees every village; 'new' starts with none (needs setup). Default 'admin'. */
  user?: MockUser;
}

export type MockUser = 'admin' | 'new' | 'member';

interface SimCall {
  villageId: string;
  householdId: string | null;
  operatorId: string | null;
  session: IvrSession;
}

const FIXABLE: TicketState[] = ['OPEN', 'ASSIGNED', 'REOPENED', 'ESCALATED'];
const DEMO_ACCOUNT = '000000000000';

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function notFound(what: string, id: string): ApiError {
  return new ApiError(404, 'not_found', `No ${what} with id "${id}".`);
}

// ---------------------------------------------------------------- store queries

function findVillage(state: MockState, vid: string): Village {
  const v = state.villages.find((x) => x.id === vid);
  if (!v) throw notFound('village', vid);
  return v;
}

function findTicket(state: MockState, tid: string): Ticket {
  const t = state.tickets.find((x) => x.id === tid);
  if (!t) throw notFound('ticket', tid);
  return t;
}

function openTicketFor(state: MockState, vid: string): Ticket | undefined {
  return state.tickets.find((t) => t.village_id === vid && t.state !== 'CLOSED_VERIFIED');
}

function callableHouseholds(state: MockState, vid: string): number {
  return state.households.filter((h) => h.village_id === vid && isCallable(h)).length;
}

function villageOperators(state: MockState, vid: string): Operator[] {
  return state.operators.filter((o) => o.village_ids.includes(vid));
}

/** Seven-day tally ending today, as in GET /api/villages. */
export function observed7d(days: DayStatus[], today: IsoDate): Observed7d {
  const from = addDays(today, -6);
  const window = days.filter((d) => d.date >= from && d.date <= today);
  const count = (s: DayStatus['status']) => window.filter((d) => d.status === s).length;
  return {
    days: window.length,
    supplied: count('SUPPLIED'),
    no_supply: count('NO_SUPPLY'),
    partial: count('PARTIAL'),
    dirty: count('DIRTY'),
    unverified: count('UNVERIFIED'),
  };
}

/** "Yes" answers from verification calls made after the operator last reported a fix. */
export function verifyYesCount(state: MockState, ticket: Ticket): number {
  const fixed = [...ticket.events].reverse().find((e) => e.kind === 'operator_fixed');
  if (!fixed) return 0;
  const since = new Date(fixed.at).getTime();
  const yes = new Set(
    state.checkins
      .filter(
        (c) =>
          c.village_id === ticket.village_id &&
          c.purpose === 'VERIFY' &&
          c.water === 'YES' &&
          new Date(c.captured_at).getTime() >= since,
      )
      .map((c) => c.household_id),
  );
  return yes.size;
}

// ---------------------------------------------------------------- store mutations

function addEvent(ticket: Ticket, event: TicketEvent): void {
  ticket.events.push(event);
  if (event.to_state) ticket.state = event.to_state;
  ticket.updated_at = event.at;
}

function pushActivity(
  state: MockState,
  at: Date,
  kind: string,
  villageId: string,
  textEn: string,
  textHi: string,
): void {
  const item: ActivityItem = { at: at.toISOString(), kind, village_id: villageId, text_en: textEn, text_hi: textHi };
  state.activity.push(item);
}

function quorumDenial(yes: number, quorum: number): PolicyDenied {
  return {
    denied: true,
    policy_id: 'verify-needs-quorum',
    reason_hi: `अभी ${quorum} में से केवल ${yes} ${yes === 1 ? 'घर' : 'घरों'} ने पानी आने की पुष्टि की है।`,
    reason_en: `Only ${yes} of ${quorum} households confirmed water.`,
  };
}

const CONSENT_DENIAL: PolicyDenied = {
  denied: true,
  policy_id: 'consent-required',
  reason_hi: 'इस घर की सहमति दर्ज नहीं है, इसलिए कॉल नहीं होगा।',
  reason_en: 'No consent on file for this household.',
};

const WITHDRAWN_DENIAL: PolicyDenied = {
  denied: true,
  policy_id: 'no-calls-after-withdrawal',
  reason_hi: 'इस परिवार ने कॉल के लिए मना किया है (या बंद कराई हैं), इसलिए कॉल नहीं होगी।',
  reason_en: 'This family said no to calls (or stopped them), so it is not called.',
};

/** Factory for the in-memory API. */
export function createMockApi(options: MockApiOptions = {}): JalApi {
  const now = options.now ?? (() => new Date());
  const state = options.state ?? seedSampleState(now());
  const latency = options.latencyMs ?? 0;
  const actor = options.actor ?? 'console:demo-user';
  const role: OperatorRole = options.role ?? 'PANCHAYAT_SECRETARY';
  const user: MockUser = options.user ?? 'admin';
  /** Villages bound to this account (null: admin, sees all). */
  const bound: string[] | null =
    user === 'admin' ? null : user === 'new' ? [] : state.villages.map((v) => v.id);
  const visible = (vid: string) => bound === null || bound.includes(vid);
  const calls = new Map<string, SimCall>();
  let seq = 0;

  async function reply<T>(fn: () => T): Promise<T> {
    if (latency > 0) await sleep(latency);
    return structuredClone(fn());
  }

  const panchayat = createPanchayatMock({
    state,
    now,
    actor,
    role,
    reply,
    activity: (kind, villageId, en, hi) => pushActivity(state, now(), kind, villageId, en, hi),
  });

  function markOperatorFixed(ticket: Ticket, operatorId: string, via: string): void {
    if (!FIXABLE.includes(ticket.state)) {
      throw new ApiError(
        409,
        'invalid_transition',
        `Ticket is ${ticket.state}; only an open, assigned or reopened ticket can be reported fixed.`,
      );
    }
    const at = now();
    const village = findVillage(state, ticket.village_id);
    addEvent(ticket, {
      at: at.toISOString(),
      actor: operatorId,
      kind: 'operator_fixed',
      from_state: ticket.state,
      to_state: 'OPERATOR_REPORTED_FIXED',
      detail: { via },
    });
    addEvent(ticket, {
      at: minutesFrom(at, 0.05).toISOString(),
      actor: 'system:ticket-flow',
      kind: 'verify_started',
      from_state: 'OPERATOR_REPORTED_FIXED',
      to_state: 'VERIFYING',
      detail: { households: callableHouseholds(state, village.id), quorum: village.quorum },
    });
    pushActivity(
      state,
      at,
      'ticket',
      village.id,
      `${village.name}: operator reported the repair. Calling households to confirm.`,
      `${village.name}: नल जल मित्र ने मरम्मत की सूचना दी। घरों से पुष्टि के कॉल जा रहे हैं।`,
    );
  }

  /** The water point a bad day is about: the first point with that status (null = whole village). */
  function badPoint(day: DayStatus): string | null {
    return (day.points ?? []).find((p) => p.status === day.status)?.water_point_id ?? null;
  }

  function openTicket(village: Village, day: DayStatus): void {
    const at = now();
    seq += 1;
    const reason = day.status === 'DIRTY' ? 'DIRTY' : 'NO_SUPPLY';
    const wpid = badPoint(day);
    const number = (state.ticketSeq[village.id] ?? 0) + 1;
    state.ticketSeq[village.id] = number;
    const point = state.waterPoints.find((p) => p.id === wpid);
    const ticket: Ticket = {
      id: `tkt-sim-${String(seq).padStart(4, '0')}`,
      village_id: village.id,
      reason,
      state: 'OPEN',
      opened_at: at.toISOString(),
      updated_at: at.toISOString(),
      events: [],
      number,
      water_point_id: wpid,
      origin: 'reconcile',
      reporters: [],
      quorum: point?.quorum ?? village.quorum,
      issue: null,
      blocker: null,
    };
    addEvent(ticket, {
      at: at.toISOString(),
      actor: 'system:reconcile',
      kind: 'opened',
      from_state: null,
      to_state: 'OPEN',
      detail: { day_status: day.status, ...day.counts, rule_version: day.rule_version },
    });
    const njm = villageOperators(state, village.id).find((o) => o.role === 'NAL_JAL_MITRA');
    addEvent(ticket, {
      at: minutesFrom(at, 0.05).toISOString(),
      actor: 'system:ticket-flow',
      kind: 'notified',
      from_state: 'OPEN',
      to_state: 'ASSIGNED',
      detail: { operator_id: point?.operator_ids[0] ?? njm?.id ?? null },
    });
    state.tickets.unshift(ticket);
    pushActivity(
      state,
      at,
      'ticket',
      village.id,
      `${village.name}: ticket opened (${reason === 'DIRTY' ? 'dirty water' : 'no supply'}). Calling the pump operator.`,
      `${village.name}: शिकायत खुली। नल जल मित्र को कॉल किया जा रहा है।`,
    );
  }

  /** Recomputes today's status after a new answer, opening a ticket if needed. */
  function recomputeToday(village: Village): void {
    const today = istDate(now());
    const checkins = state.checkins.filter(
      (c) => c.village_id === village.id && c.date === today && c.purpose === 'DAILY',
    );
    const next = dayStatusFrom(village, today, checkins, now());
    const index = state.days.findIndex((d) => d.village_id === village.id && d.date === today);
    const before = index >= 0 ? state.days[index] : undefined;
    if (index >= 0) state.days[index] = next;
    else state.days.push(next);
    if (before?.status !== next.status) {
      pushActivity(
        state,
        now(),
        'day_status',
        village.id,
        `${village.name}: today's status is now ${next.status} (${next.counts.answered} answered).`,
        `${village.name}: आज की स्थिति बदली (${next.counts.answered} घरों ने जवाब दिया)।`,
      );
    }
    const bad = next.status === 'NO_SUPPLY' || next.status === 'DIRTY';
    // One open ticket per water point and reason (OPENTKT#{wpid|village}#{reason}).
    const reason = next.status === 'DIRTY' ? 'DIRTY' : 'NO_SUPPLY';
    const wpid = badPoint(next);
    const already = state.tickets.some(
      (t) =>
        t.village_id === village.id &&
        t.state !== 'CLOSED_VERIFIED' &&
        t.reason === reason &&
        (t.water_point_id ?? null) === wpid,
    );
    if (bad && !already) openTicket(village, next);
  }

  function recordCheckin(call: SimCall, purpose: Purpose): CheckInMasked {
    const at = now();
    const date = istDate(at);
    const hh = state.households.find((h) => h.id === call.householdId);
    const previous = state.checkins.filter(
      (c) => c.household_id === call.householdId && c.date === date && c.purpose === purpose,
    );
    const { water, hours, clean } = call.session.answers;
    const checkin: CheckInMasked = {
      village_id: call.villageId,
      date,
      household_id: call.householdId ?? 'unknown',
      phone_masked: hh?.phone_masked ?? null,
      attempt: previous.reduce((max, c) => Math.max(max, c.attempt), 0) + 1,
      call_id: `sim-${date}-${call.householdId}-${previous.length + 1}`,
      purpose,
      outcome: 'ANSWERED',
      water,
      hours,
      clean,
      water_point_id: hh?.water_point_id ?? null,
      note_transcript: null,
      note_issue: null,
      captured_via: 'SIMULATOR',
      captured_at: at.toISOString(),
    };
    state.checkins.push(checkin);
    return checkin;
  }

  function commitVerify(call: SimCall, village: Village): void {
    const checkin = recordCheckin(call, 'VERIFY');
    const ticket = openTicketFor(state, village.id);
    if (!ticket || ticket.state !== 'VERIFYING' || !checkin.water) return;
    const at = now();
    if (checkin.water === 'NO') {
      addEvent(ticket, {
        at: at.toISOString(),
        actor: 'system:verify',
        kind: 'reopened',
        from_state: 'VERIFYING',
        to_state: 'REOPENED',
        detail: { household_id: checkin.household_id, water: 'NO' },
      });
      pushActivity(state, at, 'ticket', village.id,
        `${village.name}: a household says water is still not coming. Ticket reopened.`,
        `${village.name}: एक घर ने कहा पानी अभी भी नहीं आ रहा। शिकायत फिर से खुली।`);
      return;
    }
    const yes = verifyYesCount(state, ticket);
    addEvent(ticket, {
      at: at.toISOString(),
      actor: checkin.household_id,
      kind: 'verify_answer',
      from_state: null,
      to_state: null,
      detail: { water: checkin.water, verify_yes: yes, quorum: village.quorum },
    });
    pushActivity(state, at, 'call', village.id,
      `${village.name}: a household confirmed water is back (${yes} of ${village.quorum} needed).`,
      `${village.name}: एक घर ने पुष्टि की कि पानी आ रहा है (${village.quorum} में से ${yes})।`);
  }

  function commitCall(call: SimCall): void {
    const village = findVillage(state, call.villageId);
    const purpose = call.session.purpose;
    if (purpose === 'DAILY') {
      recordCheckin(call, 'DAILY');
      pushActivity(state, now(), 'call', village.id,
        `${village.name}: simulator check-in answered by a household.`,
        `${village.name}: सिम्युलेटर से एक घर ने जवाब दिया।`);
      recomputeToday(village);
    } else if (purpose === 'VERIFY') {
      commitVerify(call, village);
    } else if (call.session.answers.fixed && call.operatorId) {
      const ticket = openTicketFor(state, village.id);
      if (ticket && FIXABLE.includes(ticket.state)) markOperatorFixed(ticket, call.operatorId, 'DTMF');
    }
  }

  function operatorSummary(vid: string): OperatorSummary | undefined {
    const ticket = openTicketFor(state, vid);
    if (!ticket) return undefined;
    const opened = ticket.events.find((e) => e.kind === 'opened')?.detail ?? {};
    const key = ticket.reason === 'DIRTY' ? 'dirty' : 'no';
    const households = typeof opened[key] === 'number' ? (opened[key] as number) : 2;
    return { reason: ticket.reason === 'DIRTY' ? 'DIRTY' : 'NO_SUPPLY', households };
  }

  function resolveCallTarget(req: SimStartRequest): Omit<SimCall, 'session'> {
    if (req.operator_id) {
      const op = state.operators.find((o) => o.id === req.operator_id);
      if (!op) throw notFound('operator', req.operator_id);
      return { villageId: op.village_ids[0] ?? '', householdId: null, operatorId: op.id };
    }
    if (!req.household_id) {
      throw new ApiError(400, 'missing_target', 'Send household_id or operator_id.');
    }
    if (req.purpose === 'OPERATOR') {
      throw new ApiError(400, 'bad_purpose', 'OPERATOR calls need an operator_id.');
    }
    const hh = state.households.find((h) => h.id === req.household_id);
    if (!hh) throw notFound('household', req.household_id);
    const consent = effectiveConsent(hh);
    if (consent === 'DECLINED' || consent === 'WITHDRAWN') throw new PolicyDeniedError(WITHDRAWN_DENIAL);
    if (consent !== 'GRANTED') throw new PolicyDeniedError(CONSENT_DENIAL);
    return { villageId: hh.village_id, householdId: hh.id, operatorId: null };
  }

  return {
    ...panchayat,
    ...createSetupMock({ state, bound, reply }),

    getMe: () =>
      reply((): Me => {
        const ids = state.villages.map((v) => v.id).filter(visible);
        return {
          username: user === 'new' ? 'new-panchayat' : role === 'SARPANCH' ? 'sarpanch' : 'secretary',
          email: null,
          role,
          is_admin: bound === null,
          village_ids: ids,
          needs_setup: ids.length === 0,
          can_approve_announcements: role === 'SARPANCH',
        };
      }),

    listVillages: () =>
      reply((): VillageSummary[] => {
        const today = istDate(now());
        return state.villages.filter((v) => visible(v.id)).map((village) => {
          const days = state.days.filter((d) => d.village_id === village.id);
          return {
            village,
            today: days.find((d) => d.date === today) ?? null,
            open_ticket: openTicketFor(state, village.id) ?? null,
            open_tickets: state.tickets.filter(
              (t) => t.village_id === village.id && t.state !== 'CLOSED_VERIFIED',
            ),
            observed_7d: observed7d(days, today),
          };
        });
      }),

    getVillage: (vid) =>
      reply(() => {
        const official = state.official[vid] ?? null;
        return {
          village: findVillage(state, vid),
          households: state.households.filter((h) => h.village_id === vid),
          operators: villageOperators(state, vid),
          water_points: state.waterPoints.filter((p) => p.village_id === vid),
          official,
          official_note: official ? officialAgeNote(official, now()) : null,
          context: state.context[vid] ?? {},
        };
      }),

    getDays: (vid, from, to) =>
      reply(() => {
        findVillage(state, vid);
        return state.days
          .filter((d) => d.village_id === vid && d.date >= from && d.date <= to)
          .sort((a, b) => a.date.localeCompare(b.date));
      }),

    getCheckins: (vid, date, purpose = 'DAILY') =>
      reply(() =>
        state.checkins
          .filter((c) => c.village_id === vid && c.date === date && c.purpose === purpose)
          .sort((a, b) => a.captured_at.localeCompare(b.captured_at)),
      ),

    runCheckin: (vid) =>
      reply(() => {
        const village = findVillage(state, vid);
        seq += 1;
        pushActivity(state, now(), 'checkin_run', vid,
          `${village.name}: check-in run started from the console. Households already called today are skipped (one call per day).`,
          `${village.name}: कंसोल से जाँच कॉल शुरू। आज जिन घरों को कॉल हो चुका, उन्हें छोड़ा जाएगा।`);
        return {
          execution_arn: `arn:aws:states:ap-south-1:${DEMO_ACCOUNT}:execution:jalsakshi-demo-CheckInRun:console-${seq}`,
        };
      }),

    listTickets: (query) =>
      reply(() =>
        state.tickets
          .filter((t) => !query?.state || t.state === query.state)
          .filter((t) => !query?.village_id || t.village_id === query.village_id)
          .sort((a, b) => b.opened_at.localeCompare(a.opened_at)),
      ),

    getTicket: (tid) => reply(() => findTicket(state, tid)),

    getOverview: (tid) =>
      reply((): TicketOverview => {
        const ticket = findTicket(state, tid);
        const at = now();
        const hours = Math.max(0, Math.floor((at.getTime() - Date.parse(ticket.opened_at)) / 3_600_000));
        const families = Math.max(1, ticket.reporters?.length ?? 0);
        const told = ticket.events.some((e) => e.kind.toUpperCase() === 'NOTIFIED');
        const step: NextStep =
          ticket.state === 'ESCALATED' ? 'RAISE_WITH_BLOCK_OFFICE' : !told ? 'CALL_OPERATOR_AGAIN' : hours >= 72 ? 'SEND_TO_SARPANCH' : 'WAIT_FOR_REPAIR';
        const labels: Record<NextStep, string> = {
          CALL_OPERATOR_AGAIN: 'Call the pump operator again',
          SEND_TO_SARPANCH: 'Send it to the Sarpanch',
          RAISE_WITH_BLOCK_OFFICE: 'Raise it with the PHED block office',
          WAIT_FOR_REPAIR: 'Wait: the repair is in progress',
        };
        return {
          text: `Complaint #${ticket.number ?? '?'}: ${families === 1 ? '1 family' : `${families} families`} reported it, open for ${hours} hours.`,
          text_source: 'template',
          suggestion:
            ticket.state === 'CLOSED_VERIFIED'
              ? null
              : { step, label: labels[step], source: 'rules', confidence: null, probabilities: {}, urgent: null, reasons: ['Mock rules'] },
          facts: { number: ticket.number, hours_open: hours },
          generated_at: at.toISOString(),
        };
      }),

    sendToSarpanch: (tid) =>
      reply(() => {
        const ticket = findTicket(state, tid);
        if (ticket.state === 'CLOSED_VERIFIED') throw new ApiError(409, 'closed', 'this complaint is already closed');
        if (ticket.state !== 'ESCALATED') {
          addEvent(ticket, {
            at: now().toISOString(),
            actor,
            kind: 'ESCALATED',
            from_state: ticket.state,
            to_state: 'ESCALATED',
            detail: { to: 'SARPANCH', by: null, reason: 'panchayat_office' },
          });
        }
        return ticket;
      }),

    callOperatorAgain: (tid) =>
      reply((): { call: 'queued' } => {
        const ticket = findTicket(state, tid);
        if (ticket.state === 'CLOSED_VERIFIED') throw new ApiError(409, 'closed', 'this complaint is already closed');
        if (!['ASSIGNED', 'REOPENED', 'ESCALATED'].includes(ticket.state)) {
          throw new ApiError(409, 'not_waiting_for_operator', 'the pump operator is not waiting for a call now');
        }
        return { call: 'queued' };
      }),

    operatorFixed: (tid, operatorId) =>
      reply(() => {
        const ticket = findTicket(state, tid);
        if (!state.operators.some((o) => o.id === operatorId)) throw notFound('operator', operatorId);
        markOperatorFixed(ticket, operatorId, 'console');
        return ticket;
      }),

    closeTicket: (tid) =>
      reply(() => {
        const ticket = findTicket(state, tid);
        if (ticket.state === 'CLOSED_VERIFIED') {
          throw new ApiError(409, 'already_closed', 'This ticket is already closed.');
        }
        const village = findVillage(state, ticket.village_id);
        const quorum = ticket.quorum ?? village.quorum;
        const yes = verifyYesCount(state, ticket);
        const at = now();
        if (ticket.state !== 'VERIFYING' || yes < quorum) {
          const denied = quorumDenial(yes, quorum);
          addEvent(ticket, {
            at: at.toISOString(),
            actor,
            kind: 'close_denied',
            from_state: null,
            to_state: null,
            detail: { policy_id: denied.policy_id, verify_yes: yes, quorum: quorum },
          });
          pushActivity(state, at, 'policy_denied', village.id,
            `${village.name}: close blocked by Cedar. ${denied.reason_en}`,
            `${village.name}: शिकायत बंद करने से नियम ने रोका। ${denied.reason_hi}`);
          return { ok: false as const, denied };
        }
        addEvent(ticket, {
          at: at.toISOString(),
          actor,
          kind: 'closed_verified',
          from_state: 'VERIFYING',
          to_state: 'CLOSED_VERIFIED',
          detail: { verify_yes: yes, quorum: quorum },
        });
        pushActivity(state, at, 'ticket', village.id,
          `${village.name}: ticket closed after ${yes} households confirmed water.`,
          `${village.name}: ${yes} घरों की पुष्टि के बाद शिकायत बंद हुई।`);
        return { ok: true as const, ticket };
      }),

    getBrief: (vid, from, to) =>
      reply(() => {
        const village = findVillage(state, vid);
        const end = to ?? istDate(now());
        const start = from ?? addDays(end, -13);
        const days = state.days.filter((d) => d.village_id === vid && d.date >= start && d.date <= end);
        const tickets = state.tickets.filter(
          (t) => t.village_id === vid && istDate(new Date(t.opened_at)) <= end &&
            (t.state !== 'CLOSED_VERIFIED' || istDate(new Date(t.updated_at)) >= start),
        );
        return buildMockBrief({
          village,
          days,
          tickets,
          households: callableHouseholds(state, vid),
          from: start,
          to: end,
          now: now(),
        });
      }),

    getActivity: (since) =>
      reply(() =>
        state.activity
          .filter((a) => !since || new Date(a.at).getTime() > new Date(since).getTime())
          .sort((a, b) => a.at.localeCompare(b.at))
          .slice(-100),
      ),

    simStartCall: (req) =>
      reply(() => {
        const target = resolveCallTarget(req);
        const purpose: Purpose = target.operatorId ? 'OPERATOR' : req.purpose;
        const turn = startIvr(purpose, target.operatorId ? operatorSummary(target.villageId) : undefined);
        seq += 1;
        const callId = `sim-${seq}-${now().getTime().toString(36)}`;
        calls.set(callId, { ...target, session: turn.session });
        return { call_id: callId, actions: turn.actions };
      }),

    simInput: (callId, input: SimInputRequest) =>
      reply(() => {
        const call = calls.get(callId);
        if (!call) throw new ApiError(404, 'unknown_call', 'This call has ended or never started.');
        const turn = stepIvr(call.session, input);
        call.session = turn.session;
        if (turn.done) {
          calls.delete(callId);
          commitCall(call);
        }
        return { actions: turn.actions, done: turn.done };
      }),
  };
}
