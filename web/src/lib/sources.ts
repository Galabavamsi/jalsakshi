/** SourceTags the console derives for numbers the API returns without one. */

import type { CheckIn, IsoDateTime, SourceTag } from '../api/types';
import type { Bilingual } from './format';

/**
 * Household check-in tallies come from JalSakshi's own calls. Where the API returns them without
 * a SourceTag, the console labels them here: live from phone calls, simulated in demo mode or
 * when the answers were keyed into the web-phone simulator.
 */
export function checkinSource(
  computedAt: IsoDateTime | null | undefined,
  demo: boolean,
  simulator = false,
): SourceTag {
  const at = computedAt ?? new Date().toISOString();
  let source = 'JalSakshi household check-ins';
  if (demo) source += ' (demo)';
  else if (simulator) source += ' (web-phone simulator)';
  return {
    source,
    observed_at: at,
    fetched_at: at,
    freshness: demo || simulator ? 'simulated' : 'live',
    url: null,
  };
}

/** True when any of these answers was keyed into the web-phone simulator. */
export function fromSimulator(checkins: ReadonlyArray<Pick<CheckIn, 'captured_via'>> | undefined): boolean {
  return (checkins ?? []).some((c) => c.captured_via === 'SIMULATOR');
}

const CHECKIN_SOURCE = /^JalSakshi household check-ins\s*(\((demo|web-phone simulator)\))?$/;

/**
 * Descriptive words inside dataset names, glossed for Hindi. The proper names themselves
 * (CGWB, JJM IMIS, India-WRIS, Open-Meteo) stay as published; only these exact phrases change.
 */
const HI_PHRASES: ReadonlyArray<[RegExp, string]> = [
  [/\bHar Ghar Jal report\b/i, 'हर घर जल रिपोर्ट'],
  [/\bassessment\b/i, 'आकलन'],
  [/\blast (\d+) days\b/i, 'पिछले $1 दिन'],
  [/\bChhattisgarh\b/, 'छत्तीसगढ़'],
];

/**
 * A source's name in the console's language. Dataset names (CGWB, JJM IMIS, Open-Meteo) are
 * proper names and stay as published; the console's own check-in label is translated, and a
 * few descriptive words around dataset names are glossed (HI_PHRASES).
 */
export function sourceName(source: string): Bilingual {
  const m = CHECKIN_SOURCE.exec(source.trim());
  if (m) {
    const tag = m[2];
    const en = tag === 'demo' ? ' (demo)' : tag ? ' (web-phone simulator)' : '';
    const hi = tag === 'demo' ? ' (डेमो)' : tag ? ' (वेब-फ़ोन सिम्युलेटर)' : '';
    return { en: `Household phone check-ins${en}`, hi: `घरों के फ़ोन जवाब${hi}` };
  }
  let hi = source.replace(/\(demo\)\s*$/i, '(डेमो)');
  for (const [pattern, gloss] of HI_PHRASES) hi = hi.replace(pattern, gloss);
  return { en: source, hi };
}
