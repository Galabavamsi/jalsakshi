/** Helpers for the claimed-versus-observed comparison on the village list. */

import type { DayStatusValue, Observed7d } from '../api/types';

export const WINDOW_DAYS = 7;

/** Tally order: good days first, then the problems, then days with no data. */
const ORDER: DayStatusValue[] = ['SUPPLIED', 'PARTIAL', 'DIRTY', 'NO_SUPPLY', 'UNVERIFIED'];

type CountField = Exclude<keyof Observed7d, 'source'>;

const FIELD: Record<DayStatusValue, CountField> = {
  SUPPLIED: 'supplied',
  PARTIAL: 'partial',
  DIRTY: 'dirty',
  NO_SUPPLY: 'no_supply',
  UNVERIFIED: 'unverified',
};

/**
 * One entry per day of the window, grouped by status (not by date).
 * `null` marks a day with no status at all, e.g. before the village joined.
 */
export function tally(observed: Observed7d, windowDays = WINDOW_DAYS): Array<DayStatusValue | null> {
  const out: Array<DayStatusValue | null> = [];
  for (const status of ORDER) {
    const n = Math.max(0, observed[FIELD[status]]);
    for (let i = 0; i < n && out.length < windowDays; i += 1) out.push(status);
  }
  while (out.length < windowDays) out.push(null);
  return out;
}
