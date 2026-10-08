/** Merging polled activity into the feed without duplicates. */

import type { ActivityItem } from '../api/types';

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
