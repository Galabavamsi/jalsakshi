import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';
import type { ActivityItem } from '../src/api/types';
import { Bi } from '../src/components/Bi';
import { householdsTitle, runCheckinConfirm, verdictText, villagesLede } from '../src/i18n/messages';
import {
  DEFAULT_LOCALE,
  LanguageSwitcher,
  LocaleProvider,
  STORAGE_KEY,
  pick,
  pickField,
  pickFn,
  readStoredLocale,
  resolveInitialLocale,
  urlWithoutLang,
  writeStoredLocale,
  type Locale,
} from '../src/i18n/locale';
import { verdictOf } from '../src/lib/verdict';

/** A minimal window with localStorage for the node test environment. */
function fakeWindow(initial: Record<string, string> = {}, opts: { throws?: boolean } = {}) {
  const data = new Map(Object.entries(initial));
  const storage = {
    getItem: (k: string) => {
      if (opts.throws) throw new Error('SecurityError');
      return data.get(k) ?? null;
    },
    setItem: (k: string, v: string) => {
      if (opts.throws) throw new Error('QuotaExceededError');
      data.set(k, v);
    },
  };
  (globalThis as { window?: unknown }).window = { localStorage: storage, location: { search: '' } };
  return data;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

function render(locale: Locale, node: Parameters<typeof createElement>[0], props: object = {}) {
  return renderToStaticMarkup(createElement(LocaleProvider, { initial: locale, children: createElement(node, props) }));
}

describe('initial language', () => {
  it('is English with no window, no URL and nothing saved', () => {
    expect(DEFAULT_LOCALE).toBe('en');
    expect(resolveInitialLocale('')).toBe('en');
  });

  it('takes ?lang=hi and saves it', () => {
    const data = fakeWindow();
    expect(resolveInitialLocale('?lang=hi')).toBe('hi');
    expect(data.get(STORAGE_KEY)).toBe('hi');
  });

  it('remembers the saved choice on the next load', () => {
    fakeWindow({ [STORAGE_KEY]: 'hi' });
    expect(resolveInitialLocale('')).toBe('hi');
    expect(resolveInitialLocale('?lang=en')).toBe('en');
    expect(readStoredLocale()).toBe('en');
  });

  it('ignores an unknown stored or URL value', () => {
    fakeWindow({ [STORAGE_KEY]: 'xx' });
    expect(resolveInitialLocale('?lang=fr')).toBe('en');
  });

  it('works when storage is blocked', () => {
    fakeWindow({}, { throws: true });
    expect(() => writeStoredLocale('hi')).not.toThrow();
    expect(readStoredLocale()).toBeNull();
    expect(resolveInitialLocale('?lang=hi')).toBe('hi');
    expect(resolveInitialLocale('')).toBe('en');
  });

  it('drops ?lang= from the URL after a switch, keeping the rest', () => {
    expect(urlWithoutLang('https://c.test/villages/v-1?lang=hi&x=1#top')).toBe('/villages/v-1?x=1#top');
    expect(urlWithoutLang('https://c.test/activity')).toBeNull();
  });
});

describe('switching language', () => {
  it('renders Bi in English by default and in Hindi when chosen, one language at a time', () => {
    const en = render('en', Bi, { en: 'Villages', hi: 'गाँव' });
    expect(en).toBe('<span lang="en">Villages</span>');
    const hi = render('hi', Bi, { t: { en: 'Villages', hi: 'गाँव' }, as: 'h2' });
    expect(hi).toBe('<h2 lang="hi">गाँव</h2>');
  });

  it('marks the active option in the switcher', () => {
    const html = render('en', LanguageSwitcher);
    expect(html).toContain('aria-label="Language"');
    expect(html).toMatch(/<button[^>]*lang="en"[^>]*aria-pressed="true"/);
    expect(html).toMatch(/<button[^>]*lang="hi"[^>]*aria-pressed="false"/);
    expect(render('hi', LanguageSwitcher)).toContain('aria-label="भाषा"');
  });

  it('picks pairs, messages and bilingual API fields by locale', () => {
    const pair = { en: 'Close ticket', hi: 'शिकायत बंद करें' };
    expect(pick(pair, 'en')).toBe('Close ticket');
    expect(pick(pair, 'hi')).toBe('शिकायत बंद करें');
    const denied = { denied: true as const, policy_id: 'p', reason_en: 'Only 1 of 2.', reason_hi: 'केवल 1।' };
    expect(pickField(denied, 'reason', 'en')).toBe('Only 1 of 2.');
    const item: ActivityItem = { at: '', kind: 'x', text_en: 'a', text_hi: 'ब' };
    expect(pickField(item, 'text', 'hi')).toBe('ब');
    expect(pickFn(householdsTitle, 'hi', { n: 5 })).toBe('पंजीकृत घर (5)');
  });
});

describe('messages', () => {
  it('writes plurals and an explicit zero', () => {
    expect(runCheckinConfirm.en({ n: 1 })).toBe('This calls 1 household now. Anyone already called today is skipped.');
    expect(runCheckinConfirm.en({ n: 4 })).toContain('4 households');
    expect(villagesLede.en({ gap: 0, claimed: 2 })).toContain('back the record');
    expect(villagesLede.en({ gap: 2, claimed: 2 })).toContain('in 2 of 2 villages');
    expect(villagesLede.en({ gap: 1, claimed: 1 })).toContain('in 1 of 1 village on record');
  });

  it('states the gap between the record and the households', () => {
    const v = verdictOf({ claimed_hgj: true }, { supplied: 2, partial: 0, no_supply: 5, dirty: 0 });
    expect(verdictText.en({ ...v, checkinTime: '10:30' })).toBe(
      'The record says tap water in every home. Households said no water on 5 of the last 7 days.',
    );
    expect(verdictText.hi({ ...v, checkinTime: '10:30' })).toContain('पिछले 7 में से 5 दिन पानी नहीं आया');
    const both = verdictOf({ claimed_hgj: true }, { supplied: 3, partial: 0, no_supply: 1, dirty: 2 });
    expect(verdictText.en({ ...both, checkinTime: '10:30' })).toContain('no water on 1 and dirty water on 2');
    const silent = verdictOf({ claimed_hgj: true }, { supplied: 0, partial: 0, no_supply: 0, dirty: 0 });
    expect(verdictText.en({ ...silent, checkinTime: '11:00' })).toBe(
      "No household answers yet this week. Today's calls at 11:00 IST.",
    );
  });
});
