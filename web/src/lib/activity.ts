/** Merging polled activity into the feed without duplicates. */

import type { ActivityItem, DayStatusValue } from '../api/types';

export const FEED_LIMIT = 200;

/** Identity of an entry; the API has no ids, so time, kind, village and text together. */
export function activityKey(item: ActivityItem): string {
  return `${item.at}|${item.kind}|${item.village_id ?? ''}|${item.text_en}`;
}

/** Newest first, de-duplicated, capped at FEED_LIMIT. */
export function mergeActivity(current: ActivityItem[], incoming: ActivityItem[]): ActivityItem[] {
  const seen = new Set(current.map(activityKey));
  const fresh = incoming.filter((item) => {
    const key = activityKey(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  if (fresh.length === 0) return current;
  return [...fresh, ...current]
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
    .slice(0, FEED_LIMIT);
}

/** The `since` cursor for the next poll: the newest time seen so far. */
export function newestAt(items: ReadonlyArray<Pick<ActivityItem, 'at'>>): string | undefined {
  let best: string | undefined;
  let bestMs = -Infinity;
  for (const item of items) {
    const ms = new Date(item.at).getTime();
    if (ms > bestMs) {
      bestMs = ms;
      best = item.at;
    }
  }
  return best;
}

/** Cedar policy ids the console knows, to pick out of a policy-decision row's text. */
const POLICY_ID =
  /\b(verify-needs-quorum|stale-data|calling-hours|consent-required|one-call-per-day|no-household-view-for-dept|policy-evaluation-error)\b/;

export function isPolicyItem(item: Pick<ActivityItem, 'kind'>): boolean {
  const k = item.kind.toLowerCase();
  return k.includes('policy') || k.includes('denied');
}

/** The Cedar policy id a decision row names, or null. */
export function activityPolicyId(item: Pick<ActivityItem, 'kind' | 'text_en'>): string | null {
  if (!isPolicyItem(item)) return null;
  return POLICY_ID.exec(item.text_en)?.[1] ?? null;
}

/**
 * The day status a households' row reports, read from its English text; null for rows that are
 * not households' answers (runs, tickets, rule decisions). Used only for the row's marker colour:
 * the row's own words always say the same thing.
 */
export function activityStatus(item: Pick<ActivityItem, 'kind' | 'text_en'>): DayStatusValue | null {
  const k = item.kind.toLowerCase();
  const text = item.text_en.toLowerCase();
  if (k === 'day_status' || k.includes('status')) {
    if (text.includes('no supply') || text.includes('no water')) return 'NO_SUPPLY';
    if (text.includes('dirty')) return 'DIRTY';
    if (text.includes('partial')) return 'PARTIAL';
    if (text.includes('unverified') || text.includes('too few')) return 'UNVERIFIED';
    if (text.includes('supplied') || text.includes('water came')) return 'SUPPLIED';
    return null;
  }
  if (k === 'call' || k.includes('checkin_answer') || k.includes('verify')) {
    if (text.includes('confirmed water') || text.includes('said yes')) return 'SUPPLIED';
    if (text.includes('no water') || text.includes('said no')) return 'NO_SUPPLY';
  }
  return null;
}
