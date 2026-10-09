/** Consent rules the console needs to read a household record (models.Household). */

import type { ConsentStatus, Household } from '../api/types';

type ConsentFields = Pick<Household, 'consent' | 'consent_status'>;

/**
 * `consent_status`, or GRANTED/NONE from `consent` for records written before v2.
 * Mirrors `Household.effective_consent` in core/models.py.
 */
export function effectiveConsent(h: ConsentFields): ConsentStatus {
  if (h.consent_status) return h.consent_status;
  return h.consent ? 'GRANTED' : 'NONE';
}

/** True when the daily check-in may call this household (active and consented). */
export function isCallable(h: ConsentFields & Pick<Household, 'active'>): boolean {
  return h.active && effectiveConsent(h) === 'GRANTED';
}

export const NO_AREA = 'Area not given';
export const NO_NAME = 'Name not given';

/** The area (mohalla, para, hamlet) a family said or the register showed, or null. */
export function areaOf(h: { hamlet?: string | null }): string | null {
  return h.hamlet?.trim() || null;
}

/** Every area named by these families, A to Z. */
export function areaList(households: Array<{ hamlet?: string | null }>): string[] {
  const set = new Set<string>();
  for (const h of households) {
    const a = areaOf(h);
    if (a) set.add(a);
  }
  return [...set].sort((a, b) => a.localeCompare(b));
}

/** "Thakur para, Schoolpara" for the families who reported a complaint; "Area not given" if none. */
export function reporterAreaText(
  reporters: string[] | undefined,
  households: Array<{ id: string; hamlet?: string | null }>,
): string {
  const ids = new Set(reporters ?? []);
  const areas = areaList(households.filter((h) => ids.has(h.id)));
  return areas.length ? areas.join(', ') : NO_AREA;
}

const LANGUAGE_NAMES: Record<string, string> = {
  hi: 'Hindi',
  hne: 'Chhattisgarhi',
  te: 'Telugu',
  mr: 'Marathi',
  or: 'Odia',
  bn: 'Bengali',
  gu: 'Gujarati',
  kn: 'Kannada',
  ml: 'Malayalam',
  pa: 'Punjabi',
  ta: 'Tamil',
};

/** "Chhattisgarhi" for "hne"; the code itself when unknown. */
export function languageName(code: string | null | undefined): string {
  if (!code) return LANGUAGE_NAMES.hi ?? 'Hindi';
  return LANGUAGE_NAMES[code] ?? code;
}

/** Families grouped by area, A to Z, with "area not given" (null) last. */
export function groupByArea<T extends { hamlet?: string | null }>(households: T[]): Array<{ area: string | null; items: T[] }> {
  const groups = new Map<string | null, T[]>();
  for (const h of households) {
    const key = areaOf(h);
    const list = groups.get(key);
    if (list) list.push(h);
    else groups.set(key, [h]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === null ? 1 : b === null ? -1 : a.localeCompare(b)))
    .map(([area, items]) => ({ area, items }));
}
