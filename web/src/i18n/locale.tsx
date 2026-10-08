/**
 * Console language. English is the default for everyone; Hindi is opt-in via the header switcher
 * or `?lang=hi`. The phone IVR is always Hindi and is not affected by this setting.
 *
 * Strings stay as { en, hi } pairs next to the code that uses them (lib/labels.ts works this way),
 * so a missing translation is a compile error. Components pick one language at render time.
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

export const DOCUMENT_TITLE: Bilingual = { en: 'JalSakshi console', hi: 'जल साक्षी कंसोल' };

/** Sets <html lang> and the title. Called before the first render too, so the first paint is right. */
export function applyDocumentLocale(l: Locale): void {
  if (typeof document === 'undefined') return;
  const html = document.documentElement;
  html.lang = l;
  html.dir = 'ltr';
  html.dataset.locale = l;
  document.title = DOCUMENT_TITLE[l];
}

const DEVANAGARI_FAMILY = '"Anek Devanagari Variable"';

/** Warms the Devanagari webfont before showing Hindi, so the switch does not flash. */
export function preloadHindiFont(timeoutMs = 1200): Promise<void> {
  if (typeof document === 'undefined' || !('fonts' in document)) return Promise.resolve();
  const load = document.fonts.load(`450 1em ${DEVANAGARI_FAMILY}`, 'हिन्दी').then(() => undefined);
  const timeout = new Promise<void>((resolve) => window.setTimeout(resolve, timeoutMs));
  return Promise.race([load, timeout]).catch(() => undefined);
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
    if (next === 'hi') void preloadHindiFont().then(run);
    else run();
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

const SWITCHED: Bilingual = {
  en: 'Showing the console in English.',
  hi: 'कंसोल अब हिन्दी में है।',
};

const OPTIONS: Array<{ id: Locale; label: string; name: string }> = [
  { id: 'en', label: 'EN', name: 'English' },
  { id: 'hi', label: 'हिन्दी', name: 'हिन्दी (Hindi)' },
];

/** EN | हिन्दी. Each label is in its own language and script; no flags. */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale } = useLocale();
  const [announce, setAnnounce] = useState('');
  const choose = (next: Locale) => {
    if (next === locale) return;
    setLocale(next);
    setAnnounce(SWITCHED[next]);
  };
  return (
    <div
      role="group"
      aria-label={locale === 'hi' ? 'भाषा' : 'Language'}
      className={className ? `lang-switch ${className}` : 'lang-switch'}
    >
      {OPTIONS.map((o) => (
        <button
          key={o.id}
          type="button"
          lang={o.id}
          translate="no"
          aria-pressed={locale === o.id}
          aria-label={o.name}
          className="lang-opt"
          onPointerEnter={o.id === 'hi' ? () => void preloadHindiFont() : undefined}
          onFocus={o.id === 'hi' ? () => void preloadHindiFont() : undefined}
          onClick={() => choose(o.id)}
        >
          {o.label}
        </button>
      ))}
      <span className="visually-hidden" role="status" aria-live="polite">
        {announce}
      </span>
    </div>
  );
}
