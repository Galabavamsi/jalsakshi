/**
 * Language switch for the residents' page (/v/:id) only: villagers can read it in English or Hindi
 * (`?lang=hi` or the EN | हिन्दी buttons). The console itself is plain English (`lib/text.ts`).
 * Strings are { en, hi } pairs; read them with `const t = useT(); t(m.title); t(m.count, { n })`.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { flushSync } from 'react-dom';
import type { Bilingual } from '../lib/format';

export type { Bilingual };
export type Locale = 'en' | 'hi';
export const LOCALES: readonly Locale[] = ['en', 'hi'];
export const DEFAULT_LOCALE: Locale = 'en';
export const STORAGE_KEY = 'jalsakshi.lang';

/** A message with parameters (interpolation, plurals). Both languages take the same params. */
export interface BilingualFn<P> {
  en: (p: P) => string;
  hi: (p: P) => string;
}

/** Anything a namespace may hold: a plain pair or a parameterised pair. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Message = Bilingual | BilingualFn<any>;
export type Messages = Record<string, Message>;

/** Declares a namespace; keeps each entry's exact type, so `t(m.x, params)` is type-checked. */
export function defineMessages<T extends Messages>(messages: T): T {
  return messages;
}

/** A parameterised message: `msgFn<{ n: number }>({ en: ({ n }) => ..., hi: ({ n }) => ... })`. */
export function msgFn<P>(m: BilingualFn<P>): BilingualFn<P> {
  return m;
}

const enPluralRules = new Intl.PluralRules('en');

/** "1 family" / "3 families". Write the zero case yourself ("No families yet"). */
export function enCount(n: number, one: string, other: string): string {
  return `${n} ${enPluralRules.select(n) === 'one' ? one : other}`;
}

export function isLocale(v: unknown): v is Locale {
  return v === 'en' || v === 'hi';
}

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null; // blocked storage, sandboxed iframe
  }
}

/** The saved choice, or null when there is none or storage cannot be read. */
export function readStoredLocale(): Locale | null {
  try {
    const v = storage()?.getItem(STORAGE_KEY);
    return isLocale(v) ? v : null;
  } catch {
    return null;
  }
}

/** Saves the choice; when storage is blocked it just won't survive a reload. */
export function writeStoredLocale(l: Locale): void {
  try {
    storage()?.setItem(STORAGE_KEY, l);
  } catch {
    /* private mode or blocked site data */
  }
}

/**
 * `?lang=` (saved) > stored choice > English. Deliberately ignores navigator.language: the
 * console opens in English for everyone.
 */
export function resolveInitialLocale(
  search: string = typeof window === 'undefined' ? '' : window.location.search,
): Locale {
  const fromUrl = new URLSearchParams(search).get('lang');
  if (isLocale(fromUrl)) {
    writeStoredLocale(fromUrl);
    return fromUrl;
  }
  return readStoredLocale() ?? DEFAULT_LOCALE;
}

/** The URL without `?lang=`, or null when there is nothing to remove. */
export function urlWithoutLang(href: string): string | null {
  const url = new URL(href);
  if (!url.searchParams.has('lang')) return null;
  url.searchParams.delete('lang');
  return `${url.pathname}${url.search}${url.hash}`;
}

export const DOCUMENT_TITLE: Bilingual = { en: 'JalSakshi', hi: 'à¤à¤² à¤¸à¤¾à¤à¥à¤·à¥' };

const DEFAULT_TITLES = new Set(['', 'JalSakshi', 'à¤à¤² à¤¸à¤¾à¤à¥à¤·à¥', 'JalSakshi console', 'à¤à¤² à¤¸à¤¾à¤à¥à¤·à¥ à¤à¤à¤¸à¥à¤²']);

/**
 * Sets <html lang>. Called before the first render too, so the first paint is right. The title
 * changes only while no page has set its own ("{Page} Â· {village} Â· JalSakshi", PageHeader).
 */
export function applyDocumentLocale(l: Locale): void {
  if (typeof document === 'undefined') return;
  const html = document.documentElement;
  html.lang = l;
  html.dir = 'ltr';
  html.dataset.locale = l;
  if (DEFAULT_TITLES.has(document.title)) document.title = DOCUMENT_TITLE[l];
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

interface LocaleContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ initial, children }: { initial: Locale; children: ReactNode }) {
  const [locale, setState] = useState<Locale>(initial);

  useEffect(() => applyDocumentLocale(locale), [locale]);

  const setLocale = useCallback((next: Locale) => {
    writeStoredLocale(next);
    // The choice now lives in storage; drop ?lang= so a shared link does not pin it.
    const clean = urlWithoutLang(window.location.href);
    if (clean !== null) window.history.replaceState(window.history.state, '', clean);
    const commit = () => {
      flushSync(() => setState(next));
      applyDocumentLocale(next);
    };
    const run = () => {
      // Cross-fade the swap where supported; instant otherwise or with reduced motion.
      if (typeof document.startViewTransition === 'function' && !prefersReducedMotion()) {
        document.startViewTransition(commit);
      } else {
        commit();
      }
    };
    run();
  }, []);

  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error('useLocale needs <LocaleProvider>');
  return ctx;
}

/** Pure pickers, usable in tests and non-React code. */
export function pick(m: Bilingual, l: Locale): string {
  return m[l];
}

export function pickFn<P>(m: BilingualFn<P>, l: Locale, params: P): string {
  return m[l](params);
}

/** API objects that carry `<key>_en` and `<key>_hi` (reason_*, text_*). */
export type Localized<K extends string> = Record<`${K}_${Locale}`, string>;

export function pickField<K extends string>(o: Localized<K>, key: K, l: Locale): string {
  return o[`${key}_${l}` as const];
}

export interface Translate {
  (m: Bilingual): string;
  <P>(m: BilingualFn<P>, params: P): string;
}

/** t(pair) or t(fn, params); a wrong param shape is a compile error. */
export function useT(): Translate {
  const { locale } = useLocale();
  return useMemo(() => {
    function t(m: Bilingual): string;
    function t<P>(m: BilingualFn<P>, params: P): string;
    function t<P>(m: Bilingual | BilingualFn<P>, params?: P): string {
      const v = m[locale];
      return typeof v === 'function' ? v(params as P) : v;
    }
    return t;
  }, [locale]);
}
