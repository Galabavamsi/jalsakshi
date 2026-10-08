/**
 * Place names in both scripts. The API stores village, block and district names as written by
 * the Panchayat (usually Devanagari); the English console shows a Latin spelling first and the
 * Devanagari beside it. Village spellings come from the stable `v-<slug>` id, so nothing is
 * machine-transliterated; a name with no known spelling is shown in Devanagari alone.
 */

import type { Village } from '../api/types';

/** Devanagari ↔ Latin for the blocks and districts the console knows. */
const GAZETTEER: ReadonlyArray<readonly [string, string]> = [
  ['दुर्ग', 'Durg'],
  ['पाटन', 'Patan'],
  ['धमधा', 'Dhamdha'],
  ['रायपुर', 'Raipur'],
  ['बेमेतरा', 'Bemetara'],
  ['छत्तीसगढ़', 'Chhattisgarh'],
];

const DEVANAGARI = /[ऀ-ॿ]/;
const DEMO_HI = /\s*\(डेमो\)\s*$/;
const DEMO_EN = /\s*\(demo\)\s*$/i;

export function hasDevanagari(text: string): boolean {
  return DEVANAGARI.test(text);
}

function titleCase(slug: string): string {
  return slug
    .split('-')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/** "v-nayapara" → "Nayapara"; null for ids without a readable slug ("v-1"). */
export function nameFromId(id: string): string | null {
  const m = /^v-([a-z][a-z-]*[a-z])$/.exec(id.trim().toLowerCase());
  return m?.[1] ? titleCase(m[1]) : null;
}

/**
 * Latin spelling of a village: the name itself when it is already Latin, else the id's slug,
 * plus " (demo)" when the stored name ends in "(डेमो)". Null when there is no known spelling.
 */
export function romanVillage(village: Pick<Village, 'id' | 'name'>): string | null {
  const name = village.name.trim();
  if (name && !hasDevanagari(name)) return name;
  const fromId = nameFromId(village.id);
  if (!fromId) return null;
  return DEMO_HI.test(name) ? `${fromId} (demo)` : fromId;
}

/** The Devanagari spelling of a village without the "(डेमो)" marker, or null for a Latin name. */
export function devanagariVillage(village: Pick<Village, 'name'>): string | null {
  const name = village.name.trim();
  return hasDevanagari(name) ? name.replace(DEMO_HI, '') : null;
}

/** Latin spelling of a block or district: from the gazetteer, or the name itself when Latin. */
export function romanPlace(name: string): string | null {
  const n = name.trim();
  if (!hasDevanagari(n)) return n;
  return GAZETTEER.find(([hi]) => hi === n)?.[1] ?? null;
}

/** Devanagari spelling of a block or district, or null when the console does not know it. */
export function devanagariPlace(name: string): string | null {
  const n = name.trim();
  if (hasDevanagari(n)) return n;
  return GAZETTEER.find(([, en]) => en.toLowerCase() === n.toLowerCase())?.[0] ?? null;
}

/** One village name as a plain string for sentences: Latin in English, Devanagari in Hindi. */
export function villageLabel(village: Pick<Village, 'id' | 'name'>, locale: 'en' | 'hi'): string {
  if (locale === 'en') return romanVillage(village) ?? village.name;
  const deva = devanagariVillage(village);
  if (!deva) return village.name.replace(DEMO_EN, ' (डेमो)');
  return DEMO_HI.test(village.name) ? `${deva} (डेमो)` : deva;
}

/** "Patan block, Durg district" / "पाटन विकासखंड, दुर्ग ज़िला". */
export function placeLine(village: Pick<Village, 'block' | 'district'>, locale: 'en' | 'hi'): string {
  if (locale === 'en') {
    const block = romanPlace(village.block) ?? village.block;
    const district = romanPlace(village.district) ?? village.district;
    return `${block} block, ${district} district`;
  }
  const block = devanagariPlace(village.block) ?? village.block;
  const district = devanagariPlace(village.district) ?? village.district;
  return `${block} विकासखंड, ${district} ज़िला`;
}
