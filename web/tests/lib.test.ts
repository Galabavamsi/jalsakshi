import { describe, expect, it } from 'vitest';
import type { ActivityItem, DayStatus, TicketEvent, VillageSummary } from '../src/api/types';
import { callbackPath, normaliseDomain, readConfig } from '../src/config';
import { activityKey, activityPolicyId, activityStatus, mergeActivity, newestAt } from '../src/lib/activity';
import { actorLabel, detailEntries, viaLabel } from '../src/lib/events';
import { maskPhone, relative } from '../src/lib/format';
import { STATUS, eventKey, eventLabel } from '../src/lib/labels';
import { devanagariVillage, placeLine, romanPlace, romanVillage, villageLabel } from '../src/lib/places';
import { checkinSource, fromSimulator, sourceName } from '../src/lib/sources';
import { renderMarkdown } from '../src/lib/markdown';
import { tally } from '../src/lib/reliability';
import { addDays, dateRange, istDate, istHour } from '../src/lib/time';
import { dominantStatus, observedFromDays, sortByVerdict, verdictOf } from '../src/lib/verdict';

describe('time (IST)', () => {
  it('uses the India date even when UTC is still on the previous day', () => {
    expect(istDate(new Date('2026-10-07T19:00:00Z'))).toBe('2026-10-08');
    expect(istHour(new Date('2026-10-07T19:00:00Z'))).toBe(0);
  });

  it('adds days across month ends and builds inclusive ranges', () => {
    expect(addDays('2026-09-30', 1)).toBe('2026-10-01');
    expect(addDays('2026-10-01', -1)).toBe('2026-09-30');
    expect(dateRange('2026-10-01', '2026-10-03')).toEqual(['2026-10-01', '2026-10-02', '2026-10-03']);
    expect(dateRange('2026-10-03', '2026-10-01')).toEqual([]);
  });
});

describe('format', () => {
  it('masks phones to the last four digits', () => {
    expect(maskPhone('+919876501234')).toBe('+91XXXXXX1234');
  });

  it('describes age in Hindi and English', () => {
    const now = new Date('2026-10-08T10:00:00Z');
    expect(relative('2026-10-08T09:55:00Z', now)).toEqual({ hi: '5 मिनट पहले', en: '5 min ago' });
    expect(relative('2026-10-06T10:00:00Z', now).en).toBe('2 days ago');
  });
});

describe('config', () => {
  it('needs nothing in mock mode', () => {
    expect(readConfig({ VITE_API_MODE: 'mock' })).toMatchObject({ mode: 'mock', missing: [] });
    expect(readConfig({ MODE: 'mock' }).mode).toBe('mock');
  });

  it('lists missing variables for the real API', () => {
    const cfg = readConfig({ VITE_API_BASE: 'https://api.test' });
    expect(cfg.mode).toBe('http');
    expect(cfg.missing).toEqual(['VITE_COGNITO_DOMAIN', 'VITE_COGNITO_CLIENT_ID', 'VITE_REDIRECT_URI']);
  });

  it('builds the Cognito settings', () => {
    const cfg = readConfig({
      VITE_API_BASE: 'https://api.test/',
      VITE_COGNITO_DOMAIN: 'jal.auth.ap-south-1.amazoncognito.com/',
      VITE_COGNITO_CLIENT_ID: 'abc',
      VITE_REDIRECT_URI: 'https://console.test/auth/callback',
    });
    expect(cfg.missing).toEqual([]);
    expect(cfg.apiBase).toBe('https://api.test');
    expect(cfg.cognito).toMatchObject({
      domain: 'https://jal.auth.ap-south-1.amazoncognito.com',
      logoutUri: 'https://console.test/',
      scope: 'openid email profile',
    });
    expect(callbackPath(cfg)).toBe('/auth/callback');
  });

  it('rejects a redirect URI that is not a URL', () => {
    const cfg = readConfig({
      VITE_API_BASE: 'https://api.test',
      VITE_COGNITO_DOMAIN: 'x',
      VITE_COGNITO_CLIENT_ID: 'y',
      VITE_REDIRECT_URI: 'not a url',
    });
    expect(cfg.missing).toEqual(['VITE_REDIRECT_URI (not a valid URL)']);
    expect(normaliseDomain('https://a.test//')).toBe('https://a.test');
  });
});

describe('markdown', () => {
  it('renders tables and headings', () => {
    const html = renderMarkdown('# शीर्षक\n\n| a | b |\n|---|---|\n| 1 | 2 |');
    expect(html).toContain('<h1>शीर्षक</h1>');
    expect(html).toContain('<td>2</td>');
  });

  it('escapes raw HTML and drops unsafe links and images', () => {
    const html = renderMarkdown(
      '<script>alert(1)</script>\n\n[x](javascript:alert(1)) ![p](https://e.test/a.png) [ok](https://e.test)',
    );
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('javascript:');
    expect(html).not.toContain('<img');
    expect(html).toContain('<a href="https://e.test"');
  });
});

describe('activity feed', () => {
  const item = (at: string, text = at): ActivityItem => ({
    at,
    kind: 'call',
    village_id: 'v1',
    text_en: text,
    text_hi: text,
  });

  it('merges newest first without duplicates', () => {
    const a = item('2026-10-08T10:00:00Z');
    const b = item('2026-10-08T10:05:00Z');
    const merged = mergeActivity([a], [a, b]);
    expect(merged.map(activityKey)).toEqual([activityKey(b), activityKey(a)]);
    expect(mergeActivity(merged, [a])).toBe(merged);
  });

  it('compares times as instants, not strings', () => {
    expect(newestAt([{ at: '2026-10-08T10:00:00+00:00' }, { at: '2026-10-08T15:00:00+05:30' }])).toBe(
      '2026-10-08T10:00:00+00:00',
    );
    expect(newestAt([])).toBeUndefined();
  });
});

describe('reliability tally', () => {
  it('orders good days first and pads missing days', () => {
    expect(
      tally({ days: 5, supplied: 2, partial: 1, dirty: 0, no_supply: 1, unverified: 1 }),
    ).toEqual(['SUPPLIED', 'SUPPLIED', 'PARTIAL', 'NO_SUPPLY', 'UNVERIFIED', null, null]);
  });
});

describe('ticket events', () => {
  const event: TicketEvent = {
    at: '2026-10-08T05:00:00Z',
    actor: 'op-1',
    kind: 'operator_fixed',
    from_state: 'ASSIGNED',
    to_state: 'OPERATOR_REPORTED_FIXED',
    detail: { via: 'DTMF', operator_id: 'op-1', call_id: 'hidden', day_status: 'NO_SUPPLY' },
  };

  it('names actors from the roster and system ids', () => {
    const people = { 'op-1': { hi: 'रमेश', en: 'Pump operator' } };
    expect(actorLabel('op-1', people)).toEqual(people['op-1']);
    expect(actorLabel('system:reconcile', {}).en).toBe('System: day reconciler');
    expect(actorLabel('console:asha', {}).en).toBe('Console user asha');
  });

  it('labels known detail keys, hides call ids and moves the channel to the byline', () => {
    const rows = detailEntries(event, { 'op-1': { hi: 'रमेश', en: 'operator' } });
    expect(rows.map((r) => r.label.en)).toEqual(['who', 'day status']);
    expect(rows[1]?.value).toEqual({ hi: 'पानी नहीं आया', en: 'No water' });
    expect(viaLabel(event)?.en).toBe('phone keypad');
    expect(viaLabel({ detail: {} })).toBeNull();
  });

  it('falls back to the target state for unknown kinds', () => {
    expect(eventLabel('mystery', 'VERIFYING').en).toBe('Checking with households');
    expect(eventLabel('some_new_kind').en).toBe('Some new kind');
  });

  it('maps backend event kinds and NOTE details to console labels', () => {
    expect(eventKey('VERIFIED_OK')).toBe('closed_verified');
    expect(eventKey('VERIFY_FAILED')).toBe('reopened');
    expect(eventKey('NOTE', { note: 'close_denied', policy_id: 'verify-needs-quorum' })).toBe(
      'close_denied',
    );
    expect(eventKey('NOTE', {})).toBe('note');
    expect(eventKey('opened')).toBe('opened');
    expect(eventLabel(eventKey('NOTE', { note: 'day_still_bad' })).en).toContain('Still failing');
  });

  it('names operator actors and hides the note key', () => {
    const people = { 'op-1': { hi: 'रमेश', en: 'Pump operator' } };
    expect(actorLabel('operator:op-1', people)).toEqual(people['op-1']);
    expect(actorLabel('operator:op-9', {}).en).toBe('Operator op-9');
    const note: TicketEvent = {
      ...event,
      kind: 'NOTE',
      detail: { note: 'day_still_bad', status: 'NO_SUPPLY', to: 'PHED_AE_SIM' },
    };
    const rows = detailEntries(note, {});
    expect(rows.map((r) => r.label.en)).toEqual(['day status', 'sent to']);
  });
});

describe('check-in sources', () => {
  it('labels simulator answers as simulated', () => {
    expect(checkinSource(null, false).freshness).toBe('live');
    expect(checkinSource(null, false, true).freshness).toBe('simulated');
    expect(checkinSource(null, true).source).toContain('demo');
    expect(fromSimulator([{ captured_via: 'DTMF' }, { captured_via: 'SIMULATOR' }])).toBe(true);
    expect(fromSimulator(undefined)).toBe(false);
  });
});

describe('verdict (record against households)', () => {
  const village = (claimed: boolean | null) => ({ claimed_hgj: claimed });
  const counts = (supplied: number, no_supply: number, dirty = 0, partial = 0) => ({
    supplied,
    no_supply,
    dirty,
    partial,
  });

  it('classifies gap, agree, plain and silent', () => {
    expect(verdictOf(village(true), counts(2, 5)).kind).toBe('gap');
    expect(verdictOf(village(true), counts(2, 0, 1)).kind).toBe('gap');
    expect(verdictOf(village(true), counts(6, 0, 0, 1)).kind).toBe('agree');
    expect(verdictOf(village(false), counts(2, 5)).kind).toBe('plain');
    expect(verdictOf(village(null), counts(2, 5)).kind).toBe('plain');
    expect(verdictOf(village(true), counts(0, 0)).kind).toBe('silent');
    expect(verdictOf(village(true), counts(2, 5))).toMatchObject({ heard: 7, bad: 5, days: 7 });
  });

  it('puts the biggest mismatch first', () => {
    const summary = (id: string, name: string, claimed: boolean, supplied: number, no: number): VillageSummary => ({
      village: {
        id,
        name,
        block: 'पाटन',
        district: 'दुर्ग',
        claimed_hgj: claimed,
        checkin_local_time: '10:30',
        quorum: 2,
        active: true,
      },
      observed_7d: { days: 7, supplied, no_supply: no, partial: 0, dirty: 0, unverified: 7 - supplied - no },
    });
    const sorted = sortByVerdict([
      summary('v-agree', 'A', true, 7, 0),
      summary('v-silent', 'B', true, 0, 0),
      summary('v-small-gap', 'C', true, 6, 1),
      summary('v-plain', 'D', false, 3, 4),
      summary('v-big-gap', 'E', true, 2, 5),
    ]);
    expect(sorted.map((s) => s.village.id)).toEqual(['v-big-gap', 'v-small-gap', 'v-plain', 'v-silent', 'v-agree']);
  });

  it('tones the painted panel by the most frequent status, ties to the worse', () => {
    const o = (supplied: number, no_supply: number, partial = 0, dirty = 0) => ({
      days: 7,
      supplied,
      no_supply,
      partial,
      dirty,
      unverified: 0,
    });
    expect(dominantStatus(o(2, 5))).toBe('NO_SUPPLY');
    expect(dominantStatus(o(3, 3))).toBe('NO_SUPPLY');
    expect(dominantStatus(o(5, 1, 1))).toBe('SUPPLIED');
    expect(dominantStatus(o(0, 0))).toBe('UNVERIFIED');
  });

  it('counts the last seven days from day statuses', () => {
    const day = (date: string, status: DayStatus['status']): DayStatus => ({
      village_id: 'v',
      date,
      status,
      counts: { answered: 3, yes: 0, no: 0, partial: 0, dirty: 0, unreachable: 0 },
      rule_version: 'r1',
      computed_at: `${date}T06:00:00Z`,
    });
    const o = observedFromDays(
      [
        day('2026-10-01', 'SUPPLIED'),
        day('2026-10-03', 'NO_SUPPLY'),
        day('2026-10-09', 'NO_SUPPLY'),
        day('2026-10-08', 'DIRTY'),
      ],
      '2026-10-09',
    );
    expect(o).toMatchObject({ days: 3, supplied: 0, no_supply: 2, dirty: 1 });
  });
});

describe('place names', () => {
  it('spells villages from their id, keeping the demo marker', () => {
    expect(romanVillage({ id: 'v-nayapara', name: 'नयापारा' })).toBe('Nayapara');
    expect(romanVillage({ id: 'v-nayapara', name: 'नयापारा (डेमो)' })).toBe('Nayapara (demo)');
    expect(romanVillage({ id: 'v-amli-dih', name: 'अमलीडीह' })).toBe('Amli Dih');
    expect(romanVillage({ id: 'v-1', name: 'नयापारा' })).toBeNull();
    expect(romanVillage({ id: 'v-1', name: 'Nayapara' })).toBe('Nayapara');
    expect(devanagariVillage({ name: 'नयापारा (डेमो)' })).toBe('नयापारा');
  });

  it('gives one plain label per language', () => {
    expect(villageLabel({ id: 'v-nayapara', name: 'नयापारा (डेमो)' }, 'en')).toBe('Nayapara (demo)');
    expect(villageLabel({ id: 'v-nayapara', name: 'नयापारा (डेमो)' }, 'hi')).toBe('नयापारा (डेमो)');
    expect(villageLabel({ id: 'v-1', name: 'नयापारा' }, 'en')).toBe('नयापारा');
  });

  it('writes block and district in either script', () => {
    expect(placeLine({ block: 'पाटन', district: 'दुर्ग' }, 'en')).toBe('Patan block, Durg district');
    expect(placeLine({ block: 'Dhamdha', district: 'Durg' }, 'hi')).toBe('धमधा विकासखंड, दुर्ग ज़िला');
    expect(placeLine({ block: 'अज्ञात', district: 'दुर्ग' }, 'en')).toBe('अज्ञात block, Durg district');
    expect(romanPlace('Bemetara')).toBe('Bemetara');
  });
});

describe('activity rows', () => {
  const row = (kind: string, text_en: string) => ({ kind, text_en });

  it('reads the reported status for the painted marker', () => {
    expect(activityStatus(row('day_status', 'Nayapara: no supply again (4 of 4 said no).'))).toBe('NO_SUPPLY');
    expect(activityStatus(row('day_status', 'Amlidih: water supplied (3 of 3 said yes).'))).toBe('SUPPLIED');
    expect(activityStatus(row('day_status', 'Nayapara: partial supply today.'))).toBe('PARTIAL');
    expect(activityStatus(row('call', 'household 2 confirmed water is back (1 of 2 needed).'))).toBe('SUPPLIED');
    expect(activityStatus(row('ticket', 'pump operator pressed 1, "fixed".'))).toBeNull();
  });

  it('finds the Cedar policy id on decision rows only', () => {
    expect(activityPolicyId(row('policy_denied', 'skipped, already called today (one-call-per-day).'))).toBe(
      'one-call-per-day',
    );
    expect(activityPolicyId(row('day_status', 'one-call-per-day'))).toBeNull();
  });
});

describe('source names', () => {
  it('translates only the console check-in label', () => {
    expect(sourceName('JalSakshi household check-ins (demo)')).toEqual({
      en: 'Household phone check-ins (demo)',
      hi: 'घरों के फ़ोन जवाब (डेमो)',
    });
    expect(sourceName(checkinSource(null, false, true).source).en).toBe(
      'Household phone check-ins (web-phone simulator)',
    );
    // Proper names stay as published; only the descriptive words around them are glossed.
    expect(sourceName('CGWB 2025 assessment, India-WRIS (demo)').hi).toBe('CGWB 2025 आकलन, India-WRIS (डेमो)');
    expect(sourceName('JJM IMIS Har Ghar Jal report (demo)')).toEqual({
      en: 'JJM IMIS Har Ghar Jal report (demo)',
      hi: 'JJM IMIS हर घर जल रिपोर्ट (डेमो)',
    });
    expect(sourceName('Open-Meteo, last 7 days').hi).toBe('Open-Meteo, पिछले 7 दिन');
    expect(sourceName('JJM IMIS, Chhattisgarh (demo)').hi).toBe('JJM IMIS, छत्तीसगढ़ (डेमो)');
  });
});

describe('status labels', () => {
  it('are English first with a short word and a meaning in both languages', () => {
    expect(STATUS.NO_SUPPLY.en).toBe('No water');
    expect(STATUS.NO_SUPPLY.short).toEqual({ en: 'None', hi: 'नहीं' });
    expect(STATUS.UNVERIFIED.en).toBe('Not confirmed');
    expect(STATUS.SUPPLIED.meaning.en).toBe('Households said water came');
  });
});
