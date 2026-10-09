import { describe, expect, it } from 'vitest';
import { createMockApi } from '../src/api/mock';
import type { Ticket } from '../src/api/types';
import { timelineLines } from '../src/lib/summary';

describe('AI advice on a complaint (mock)', () => {
  it('gives an overview, sends to the Sarpanch and calls the operator again', async () => {
    const api = createMockApi();
    const open = (await api.listTickets()).find((t) => t.state !== 'CLOSED_VERIFIED');
    expect(open).toBeDefined();
    const advice = await api.getOverview(open!.id);
    expect(advice.text).toMatch(/^Complaint #/);
    expect(advice.suggestion?.source).toBe('rules');
    const sent = await api.sendToSarpanch(open!.id);
    expect(sent.state).toBe('ESCALATED');
    expect(sent.events.at(-1)?.detail.to).toBe('SARPANCH');
    await expect(api.callOperatorAgain(open!.id)).resolves.toEqual({ call: 'queued' });
  });
});

describe('Complaint history lines', () => {
  const base: Ticket = {
    id: 't',
    village_id: 'v',
    reason: 'NO_SUPPLY',
    state: 'ESCALATED',
    opened_at: '2026-10-10T00:00:00Z',
    updated_at: '2026-10-10T02:00:00Z',
    events: [],
  } as unknown as Ticket;
  const ev = (kind: string, detail: Record<string, unknown>) => ({
    at: '2026-10-10T01:00:00Z',
    actor: 'operator:op-1',
    kind,
    from_state: null,
    to_state: null,
    detail,
  });

  it('names the reason, quotes the operator and says who it went to', () => {
    const lines = timelineLines({
      ...base,
      events: [
        ev('NOTE', { note: 'operator_reason', code: 'NEEDS_PANCHAYAT' }),
        ev('NOTE', { note: 'operator_voice', transcript: 'मोटर जल गई', summary_en: 'Motor burnt' }),
        ev('ESCALATED', { to: 'SARPANCH' }),
        ev('NOTE', { note: 'sarpanch_told' }),
        ev('NOTE', { note: 'sent_to_sarpanch', to: 'SARPANCH', reason: 'no_fix_48h' }),
      ],
    } as Ticket).map((l) => l.text.en);
    expect(lines[0]).toBe('Pump operator: not fixed yet. Cannot fix it alone: needs the Panchayat');
    expect(lines[1]).toBe('Pump operator said: "मोटर जल गई" (Motor burnt; AI-transcribed)');
    expect(lines[2]).toBe('Pump operator cannot fix it alone: sent to the Sarpanch');
    expect(lines[3]).toBe('The Sarpanch heard it on the phone (pressed 1)');
    expect(lines[4]).toBe('Not fixed for 48 hours: sent to the Sarpanch');
  });
});
