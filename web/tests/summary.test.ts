import { describe, expect, it } from 'vitest';
import type { DayStatus, HouseholdMasked, Operator, Ticket, WaterPoint } from '../src/api/types';
import { whyText } from '../src/pages/BulkAdd';
import {
  callTimeText,
  complaintCounts,
  familyCounts,
  howLong,
  isDayOne,
  reporterCount,
  timelineLines,
  todos,
  waterLines,
} from '../src/lib/summary';

const NOW = new Date('2026-10-09T14:00:00Z'); // 7:30 pm IST

function hh(id: string, consent: HouseholdMasked['consent_status']): HouseholdMasked {
  return { id, village_id: 'v', phone_masked: '+91XXXXXX1234', language: 'hi', call_window: '', consent_status: consent, active: true };
}

function ticket(id: string, state: Ticket['state'], openedHoursAgo: number, extra: Partial<Ticket> = {}): Ticket {
  const opened = new Date(NOW.getTime() - openedHoursAgo * 3_600_000).toISOString();
  return { id, village_id: 'v', reason: 'NO_SUPPLY', state, opened_at: opened, updated_at: opened, events: [], number: Number(id), ...extra };
}

const OPERATOR: Operator = { id: 'op', role: 'NAL_JAL_MITRA', phone_e164: '+91XXXXXX0000', village_ids: ['v'] };

describe('familyCounts', () => {
  it('counts agreed, waiting and said no', () => {
    const c = familyCounts([hh('a', 'GRANTED'), hh('b', 'NONE'), hh('c', null), hh('d', 'DECLINED'), hh('e', 'WITHDRAWN')]);
    expect(c).toEqual({ agreed: 1, waiting: 2, saidNo: 2, total: 5 });
  });
});

describe('waterLines', () => {
  const point = (id: string): WaterPoint => ({ id, village_id: 'v', kind: 'PIPED', name: id, operator_ids: [], provisional: false, active: true });
  const day = {
    status: 'NO_SUPPLY',
    counts: { answered: 3 },
    points: [{ water_point_id: 'a', status: 'NO_SUPPLY', counts: {} }],
  } as unknown as DayStatus;
  it('gives one line per source, and "not enough answers" for a source with none', () => {
    expect(waterLines(day, [point('a'), point('b')]).map((l) => l.status)).toEqual(['NO_SUPPLY', 'NONE']);
  });
  it('falls back to one line for the village', () => {
    expect(waterLines(null, [])).toEqual([{ name: null, status: 'NONE' }]);
  });
});

describe('complaints', () => {
  it('splits open, being fixed and closed this week', () => {
    const c = complaintCounts(
      [
        ticket('1', 'OPEN', 5),
        ticket('2', 'VERIFYING', 30),
        ticket('3', 'CLOSED_VERIFIED', 50),
        { ...ticket('4', 'CLOSED_VERIFIED', 400), updated_at: '2026-09-01T00:00:00Z' },
      ],
      NOW,
    );
    expect(c).toEqual({ open: 2, fixing: 1, closedThisWeek: 1 });
  });
  it('says how long in plain words', () => {
    expect(howLong(new Date(NOW.getTime() - 3 * 86_400_000).toISOString(), NOW).en).toBe('3 days');
    expect(howLong(new Date(NOW.getTime() - 5 * 3_600_000).toISOString(), NOW).en).toBe('5 hours');
  });
  it('tells the story of a complaint in plain sentences', () => {
    const t = ticket('4', 'ASSIGNED', 2, {
      events: [
        { at: NOW.toISOString(), actor: 'x', kind: 'opened', to_state: 'OPEN', detail: { no: 2 } },
        { at: NOW.toISOString(), actor: 'x', kind: 'NOTIFIED', to_state: 'ASSIGNED', detail: {} },
      ],
    });
    expect(timelineLines(t).map((l) => l.text.en)).toEqual(['2 families said no water', 'Pump operator was called']);
  });
});

describe('todos', () => {
  it('asks for the pump operator first and stops at three', () => {
    const list = todos({
      vid: 'v',
      households: [hh('a', 'NONE'), hh('b', 'NONE'), hh('c', 'NONE')],
      operators: [],
      tickets: [ticket('4', 'ASSIGNED', 80), ticket('5', 'OPEN', 60), ticket('6', 'OPEN', 50)],
      now: NOW,
    });
    expect(list).toHaveLength(3);
    expect(list[0]?.text.en).toMatch(/pump operator/);
    expect(list[1]?.text.en).toBe('Complaint #4 is 3 days old. Call the pump operator.');
  });
  it('reminds about families still waiting for their call', () => {
    const list = todos({
      vid: 'v',
      households: [hh('a', 'GRANTED'), hh('b', 'NONE'), hh('c', 'NONE'), hh('d', 'NONE')],
      operators: [OPERATOR],
      tickets: [],
      now: NOW,
    });
    expect(list.map((x) => x.text.en)).toEqual(['3 families have not agreed yet. They get their call today.']);
  });
  it('is empty when nothing needs doing', () => {
    expect(todos({ vid: 'v', households: [hh('a', 'GRANTED')], operators: [OPERATOR], tickets: [], now: NOW })).toEqual([]);
  });
});

describe('day one', () => {
  it('is day one until any family has answered', () => {
    expect(isDayOne([])).toBe(true);
    expect(isDayOne([{ counts: { answered: 0 } } as DayStatus])).toBe(true);
    expect(isDayOne([{ counts: { answered: 2 } } as DayStatus])).toBe(false);
  });
  it('reads the call time', () => {
    expect(callTimeText('19:00').en).toBe('7 pm');
    expect(callTimeText('10:30').en).toBe('10:30 am');
  });
});

describe('plain words', () => {
  it('counts reporters from the opening answers when the list is shorter', () => {
    const opened = { at: NOW.toISOString(), actor: 'system', kind: 'opened', detail: { no: 3 } };
    expect(reporterCount(ticket('1', 'OPEN', 5, { reporters: ['a'], events: [opened] }))).toBe(3);
    expect(reporterCount(ticket('2', 'OPEN', 5))).toBe(1);
  });
  it('drops the consent code from "already added"', () => {
    expect(whyText('already added (GRANTED)')).toBe('already added');
    expect(whyText('not a mobile number')).toBe('not a mobile number');
  });
});
