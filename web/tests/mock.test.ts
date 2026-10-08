import { beforeEach, describe, expect, it } from 'vitest';
import type { JalApi } from '../src/api/client';
import { createMockApi } from '../src/api/mock';
import { reconcileCounts, seedMockState } from '../src/api/mockSeed';
import type { Action } from '../src/api/types';
import { addDays, istDate } from '../src/lib/time';

// 20:00 IST on Thu 8 Oct 2026.
const NOW = new Date('2026-10-08T14:30:00Z');
const TODAY = istDate(NOW);

let clock: Date;
let api: JalApi;

beforeEach(() => {
  clock = new Date(NOW);
  api = createMockApi({ now: () => clock, actor: 'console:test' });
});

/** Advances the clock a little so events get distinct times. */
function tick(minutes = 1): void {
  clock = new Date(clock.getTime() + minutes * 60_000);
}

async function call(target: { household_id?: string; operator_id?: string }, purpose: 'DAILY' | 'VERIFY' | 'OPERATOR', digits: string[]) {
  tick();
  const start = await api.simStartCall({ ...target, purpose });
  const actions: Action[][] = [start.actions];
  let done = false;
  for (const d of digits) {
    tick();
    const res = await api.simInput(start.call_id, d === 'timeout' ? { timeout: true } : { digits: d });
    actions.push(res.actions);
    done = res.done;
  }
  return { callId: start.call_id, actions, done };
}

describe('reconcile mirror (rule r1)', () => {
  const c = (answered: number, yes: number, no: number, partial: number, dirty = 0) => ({
    answered,
    yes,
    no,
    partial,
    dirty,
    unreachable: 0,
  });

  it('follows the ARCHITECTURE §4 table top to bottom', () => {
    expect(reconcileCounts(c(1, 1, 0, 0), 2)).toBe('UNVERIFIED');
    expect(reconcileCounts(c(3, 0, 3, 0), 2)).toBe('NO_SUPPLY');
    // A tie between no and yes + partial still counts as no supply.
    expect(reconcileCounts(c(4, 2, 2, 0), 2)).toBe('NO_SUPPLY');
    expect(reconcileCounts(c(5, 3, 2, 0), 2)).toBe('PARTIAL');
    expect(reconcileCounts(c(3, 3, 0, 0, 2), 2)).toBe('DIRTY');
    expect(reconcileCounts(c(3, 2, 0, 1), 2)).toBe('PARTIAL');
    expect(reconcileCounts(c(3, 3, 0, 0), 2)).toBe('SUPPLIED');
  });
});

describe('seeded demo data', () => {
  it('has two Durg villages with 14 days each, consistent with the rule', () => {
    const state = seedMockState(NOW);
    expect(state.villages).toHaveLength(2);
    expect(state.villages.every((v) => v.district === 'दुर्ग')).toBe(true);
    for (const v of state.villages) {
      const days = state.days.filter((d) => d.village_id === v.id);
      expect(days).toHaveLength(14);
      expect(days.at(-1)?.date).toBe(TODAY);
      for (const d of days) expect(d.status).toBe(reconcileCounts(d.counts, v.quorum));
    }
  });

  it('labels every source as simulated demo data', () => {
    const state = seedMockState(NOW);
    const sources = [
      ...state.villages.map((v) => v.claimed_source),
      ...Object.values(state.context).flatMap((c) => [
        c.groundwater?.source,
        c.rain_7d_mm?.source,
        c.state_hgj?.source,
      ]),
    ];
    for (const s of sources) {
      expect(s?.freshness).toBe('simulated');
      expect(s?.source).toMatch(/demo/);
    }
  });

  it('never stores a raw household phone number', () => {
    const state = seedMockState(NOW);
    for (const h of state.households) {
      expect(h).not.toHaveProperty('phone_e164');
      expect(h.phone_masked).toMatch(/^\+91XXXXXX\d{4}$/);
    }
  });
});

describe('mock API', () => {
  it('lists villages with today, open ticket and a 7-day tally', async () => {
    const rows = await api.listVillages();
    expect(rows).toHaveLength(2);
    const nayapara = rows.find((r) => r.village.id === 'v-nayapara');
    expect(nayapara?.today?.date).toBe(TODAY);
    expect(nayapara?.open_ticket?.state).toBe('VERIFYING');
    const o = nayapara?.observed_7d;
    expect(o?.days).toBe(7);
    expect((o?.supplied ?? 0) + (o?.partial ?? 0) + (o?.no_supply ?? 0) + (o?.dirty ?? 0) + (o?.unverified ?? 0)).toBe(7);
    expect(rows.find((r) => r.village.id === 'v-amlidih')?.open_ticket).toBeNull();
  });

  it('has one CLOSED_VERIFIED ticket with a reopen in its timeline', async () => {
    const closed = await api.listTickets({ state: 'CLOSED_VERIFIED' });
    expect(closed).toHaveLength(1);
    const kinds = closed[0]?.events.map((e) => e.kind);
    expect(kinds).toContain('reopened');
    expect(kinds?.at(-1)).toBe('closed_verified');
  });

  it('returns days in range, oldest first', async () => {
    const days = await api.getDays('v-nayapara', addDays(TODAY, -6), TODAY);
    expect(days.map((d) => d.date)).toEqual(
      [6, 5, 4, 3, 2, 1, 0].map((n) => addDays(TODAY, -n)),
    );
  });

  it('denies closing without quorum, and records the attempt', async () => {
    const result = await api.closeTicket('tkt-nyp-0007');
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.denied.policy_id).toBe('verify-needs-quorum');
    expect(result.denied.reason_en).toBe('Only 1 of 2 households confirmed water.');
    const ticket = await api.getTicket('tkt-nyp-0007');
    expect(ticket.state).toBe('VERIFYING');
    expect(ticket.events.at(-1)?.kind).toBe('close_denied');
  });

  it('closes once a second household confirms through the simulator', async () => {
    const verify = await call({ household_id: 'hh-nyp-3' }, 'VERIFY', ['1']);
    expect(verify.done).toBe(true);
    tick();
    const result = await api.closeTicket('tkt-nyp-0007');
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.ticket.state).toBe('CLOSED_VERIFIED');
  });

  it('reopens the ticket when a household says water is still not coming', async () => {
    await call({ household_id: 'hh-nyp-1' }, 'VERIFY', ['2']);
    const ticket = await api.getTicket('tkt-nyp-0007');
    expect(ticket.state).toBe('REOPENED');
  });

  it('refuses simulator calls to a household without consent (Cedar)', async () => {
    await expect(api.simStartCall({ household_id: 'hh-nyp-5', purpose: 'DAILY' })).rejects.toMatchObject({
      status: 403,
      denied: { policy_id: 'consent-required' },
    });
  });

  it('records a simulator daily answer and recomputes today', async () => {
    const before = await api.getCheckins('v-amlidih', TODAY);
    await call({ household_id: 'hh-aml-1' }, 'DAILY', ['2', '#']);
    await call({ household_id: 'hh-aml-2' }, 'DAILY', ['2', '#']);
    const after = await api.getCheckins('v-amlidih', TODAY);
    expect(after.length).toBe(before.length + 2);
    expect(after.at(-1)?.captured_via).toBe('SIMULATOR');
    const [today] = await api.getDays('v-amlidih', TODAY, TODAY);
    // Two NO answers out of three (latest attempt per household) reach quorum.
    expect(today?.status).toBe('NO_SUPPLY');
    const open = await api.listTickets({ village_id: 'v-amlidih' });
    expect(open.some((t) => t.state === 'ASSIGNED' && t.reason === 'NO_SUPPLY')).toBe(true);
  });

  it('moves an assigned ticket to VERIFYING when the operator presses 1', async () => {
    await call({ household_id: 'hh-nyp-1' }, 'VERIFY', ['2']); // reopen first
    await call({ operator_id: 'op-nyp-njm' }, 'OPERATOR', ['1']);
    const ticket = await api.getTicket('tkt-nyp-0007');
    expect(ticket.state).toBe('VERIFYING');
    expect(ticket.events.at(-2)?.kind).toBe('operator_fixed');
  });

  it('rejects operator-fixed on a ticket that is already verifying', async () => {
    await expect(api.operatorFixed('tkt-nyp-0007', 'op-nyp-njm')).rejects.toMatchObject({
      status: 409,
    });
  });

  it('returns only newer activity for a since cursor', async () => {
    const all = await api.getActivity();
    const newest = all.at(-1)?.at;
    expect(await api.getActivity(newest)).toEqual([]);
    tick();
    await api.runCheckin('v-nayapara');
    const fresh = await api.getActivity(newest);
    expect(fresh).toHaveLength(1);
    expect(fresh[0]?.kind).toBe('checkin_run');
  });

  it('builds a template brief whose numbers match the days', async () => {
    const brief = await api.getBrief('v-nayapara', addDays(TODAY, -13), TODAY);
    expect(brief.generated_by).toBe('template');
    expect(brief.numbers.days).toBe(14);
    expect(brief.markdown_hi).toContain('ग्राम सभा साक्ष्य पत्र');
    expect(brief.markdown_hi).toContain('डेमो');
    expect(brief.sources.every((s) => s.freshness === 'simulated')).toBe(true);
  });

  it('answers unknown ids with 404', async () => {
    await expect(api.getVillage('nope')).rejects.toMatchObject({ status: 404 });
    await expect(api.getTicket('nope')).rejects.toMatchObject({ status: 404 });
  });
});
