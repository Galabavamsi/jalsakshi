import { describe, expect, it } from 'vitest';
import { operatorFixedAt, seedMockState } from '../src/api/mockSeed';
import type { CheckInMasked, TicketEvent } from '../src/api/types';
import { detailEntries } from '../src/lib/events';
import { policyCopy } from '../src/lib/policy';
import { promptCaption } from '../src/lib/prompts';
import { istHour } from '../src/lib/time';
import { verifyDates, verifyStartedAt, verifyTally } from '../src/lib/verify';

function verifyCheckin(hid: string, at: string, water: CheckInMasked['water'], attempt = 1): CheckInMasked {
  return {
    village_id: 'v-1',
    date: at.slice(0, 10),
    household_id: hid,
    attempt,
    call_id: `call-${hid}-${attempt}`,
    purpose: 'VERIFY',
    outcome: water ? 'ANSWERED' : 'UNREACHABLE',
    water,
    hours: null,
    clean: null,
    note_transcript: null,
    note_issue: null,
    captured_via: 'DTMF',
    captured_at: at,
  };
}

function ev(at: string, kind: string, detail: Record<string, unknown> = {}): TicketEvent {
  return { at, actor: 'system:ticket-flow', kind, from_state: null, to_state: null, detail };
}

describe('verification progress', () => {
  const since = '2026-10-08T10:00:00Z';

  it('counts the latest answer per household in the current round only', () => {
    const tally = verifyTally(
      [
        verifyCheckin('h1', '2026-10-08T09:00:00Z', 'YES'), // before the round: ignored
        verifyCheckin('h2', '2026-10-08T10:30:00Z', 'NO', 1),
        verifyCheckin('h2', '2026-10-08T11:30:00Z', 'YES', 2), // retry wins
        verifyCheckin('h3', '2026-10-08T10:40:00Z', null), // unreachable never counts
        { ...verifyCheckin('h4', '2026-10-08T10:50:00Z', 'YES'), purpose: 'DAILY' },
      ],
      since,
    );
    expect(tally).toEqual({ yes: 1, no: 0, answered: 1 });
  });

  it('finds the round start from backend and mock event kinds', () => {
    expect(
      verifyStartedAt([
        ev('2026-10-07T10:00:00Z', 'VERIFY_STARTED'),
        ev('2026-10-08T10:00:00Z', 'verify_started'),
        ev('2026-10-08T12:00:00Z', 'NOTE', { note: 'close_denied' }),
      ]),
    ).toBe('2026-10-08T10:00:00Z');
    expect(verifyStartedAt([ev('2026-10-08T10:00:00Z', 'OPENED')])).toBeNull();
  });

  it('asks for at most three days of check-ins', () => {
    expect(verifyDates('2026-10-08T10:00:00Z', '2026-10-09')).toEqual(['2026-10-08', '2026-10-09']);
    expect(verifyDates('2026-10-01T10:00:00Z', '2026-10-09')).toEqual([
      '2026-10-07',
      '2026-10-08',
      '2026-10-09',
    ]);
  });
});

describe('ticket event details', () => {
  it('shows a water answer in words, not the enum', () => {
    const rows = detailEntries(ev('2026-10-08T10:00:00Z', 'verify_answer', { water: 'YES' }), {});
    expect(rows[0]?.value).toEqual({ hi: 'हाँ, आया', en: 'Yes' });
  });
});

describe('IVR captions', () => {
  it('gives Devanagari, English and keypad choices for a question', () => {
    const c = promptCaption('household.q_water', 'Aaj nal mein paani aaya?');
    expect(c?.hi).toBe('आज नल में पानी आया?');
    expect(c?.choices?.map((x) => x.key)).toEqual(['1', '2', '3']);
  });

  it('carries the household count into the operator summary', () => {
    const c = promptCaption('operator.summary_no_supply', 'Shikayat karne wale gharon ki sankhya: 3.');
    expect(c?.hi).toContain('3 घरों');
    expect(c?.en).toContain('3 households');
  });

  it('returns null for an unknown prompt so the spoken text is shown instead', () => {
    expect(promptCaption('household.new_question', 'Kuch')).toBeNull();
  });
});

describe('policy notices', () => {
  it('explains known rules and falls back for unknown ones', () => {
    expect(policyCopy('verify-needs-quorum').title.en).toBe('This ticket cannot close yet');
    expect(policyCopy('stale-data').next?.en).toContain('check-in');
    expect(policyCopy('some-new-rule').title.en).toBe('Held back by a rule');
  });
});

describe('demo data respects calling hours', () => {
  it('places the seeded operator and verification calls between 09:00 and 21:00 IST', () => {
    for (const now of ['2026-10-08T19:03:00Z', '2026-10-09T02:00:00Z', '2026-10-09T08:30:00Z']) {
      const fixed = operatorFixedAt(new Date(now));
      expect(istHour(fixed)).toBeGreaterThanOrEqual(9);
      expect(istHour(new Date(fixed.getTime() + 30 * 60_000))).toBeLessThan(21);
      expect(fixed.getTime()).toBeLessThanOrEqual(Date.parse(now));
    }
  });

  it('has no check-ins for today before the village has been called', () => {
    const state = seedMockState(new Date('2026-10-08T23:00:00Z')); // 04:30 IST on 9 Oct
    expect(state.days.some((d) => d.date === '2026-10-09')).toBe(false);
    for (const c of state.checkins) {
      const hour = istHour(new Date(c.captured_at));
      expect(hour >= 9 && hour < 21).toBe(true);
    }
  });
});
