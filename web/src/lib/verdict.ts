/**
 * The one-line verdict on each village: does what households said agree with the state record?
 * Pure and deterministic, so the sentence on screen always follows from the counts beside it.
 */

import type { DayStatus, DayStatusValue, IsoDate, Observed7d, Village, VillageSummary } from '../api/types';
import { WINDOW_DAYS } from './reliability';
import { addDays } from './time';

export type VerdictKind = 'gap' | 'plain' | 'silent' | 'agree';

export interface Verdict {
  kind: VerdictKind;
  /** Days with a household-decided status (anything but UNVERIFIED). */
  heard: number;
  /** Days with no water or dirty water. */
  bad: number;
  supplied: number;
  partial: number;
  no: number;
  dirty: number;
  /** Length of the window the counts cover. */
  days: number;
}

type Counts = Pick<Observed7d, 'supplied' | 'partial' | 'no_supply' | 'dirty'>;

export function verdictOf(
  village: Pick<Village, 'claimed_hgj'>,
  observed: Counts,
  days = WINDOW_DAYS,
): Verdict {
  const supplied = Math.max(0, observed.supplied);
  const partial = Math.max(0, observed.partial);
  const no = Math.max(0, observed.no_supply);
  const dirty = Math.max(0, observed.dirty);
  const heard = supplied + partial + no + dirty;
  const bad = no + dirty;
  let kind: VerdictKind = 'plain';
  if (heard === 0) kind = 'silent';
  else if (village.claimed_hgj === true && bad > 0) kind = 'gap';
  else if (village.claimed_hgj === true) kind = 'agree';
  return { kind, heard, bad, supplied, partial, no, dirty, days };
}

/** The same counts as `observed_7d`, built from day statuses (the village page has days, not a summary). */
export function observedFromDays(days: DayStatus[], today: IsoDate, window = WINDOW_DAYS): Observed7d {
  const from = addDays(today, -(window - 1));
  const inWindow = days.filter((d) => d.date >= from && d.date <= today);
  const count = (s: DayStatusValue) => inWindow.filter((d) => d.status === s).length;
  return {
    days: inWindow.length,
    supplied: count('SUPPLIED'),
    partial: count('PARTIAL'),
    no_supply: count('NO_SUPPLY'),
    dirty: count('DIRTY'),
    unverified: count('UNVERIFIED'),
  };
}

const RANK: Record<VerdictKind, number> = { gap: 0, plain: 1, silent: 2, agree: 3 };

/** Biggest mismatch first: gap, plain, silent, agree; then more bad days; then by name. */
export function sortByVerdict(summaries: VillageSummary[]): VillageSummary[] {
  const keyed = summaries.map((s) => ({ s, v: verdictOf(s.village, s.observed_7d) }));
  keyed.sort(
    (a, b) =>
      RANK[a.v.kind] - RANK[b.v.kind] ||
      b.v.bad - a.v.bad ||
      a.s.village.name.localeCompare(b.s.village.name),
  );
  return keyed.map((k) => k.s);
}

/**
 * The tone of a painted panel: the week's most frequent status, a tie going to the worse one;
 * `UNVERIFIED` when households were silent all week.
 */
export function dominantStatus(observed: Observed7d): DayStatusValue {
  const worstFirst: Array<[DayStatusValue, number]> = [
    ['NO_SUPPLY', observed.no_supply],
    ['DIRTY', observed.dirty],
    ['PARTIAL', observed.partial],
    ['SUPPLIED', observed.supplied],
  ];
  let best: [DayStatusValue, number] = ['UNVERIFIED', 0];
  for (const entry of worstFirst) if (entry[1] > best[1]) best = entry;
  return best[0];
}
