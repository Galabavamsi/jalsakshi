import { describe, expect, it } from 'vitest';
import type { ActivityItem, TicketEvent } from '../src/api/types';
import { callbackPath, normaliseDomain, readConfig } from '../src/config';
import { activityKey, mergeActivity, newestAt } from '../src/lib/activity';
import { actorLabel, detailEntries } from '../src/lib/events';
import { maskPhone, relative } from '../src/lib/format';
import { eventKey, eventLabel } from '../src/lib/labels';
import { checkinSource, fromSimulator } from '../src/lib/sources';
import { renderMarkdown } from '../src/lib/markdown';
import { tally } from '../src/lib/reliability';
import { addDays, dateRange, istDate, istHour } from '../src/lib/time';

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

  it('labels known detail keys and hides call ids', () => {
    const rows = detailEntries(event, { 'op-1': { hi: 'रमेश', en: 'operator' } });
    expect(rows.map((r) => r.label.en)).toEqual(['via', 'who', 'day status']);
    expect(rows[0]?.value).toContain('keypad');
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
