/** How far a ticket's verification round has got: households that confirmed water is back. */

import type { CheckInMasked, IsoDate, TicketEvent } from '../api/types';
import { eventKey } from './labels';
import { addDays, dateRange, istDate } from './time';

export interface VerifyTally {
  /** Households whose latest verification answer is "yes, water is back". */
  yes: number;
  /** Households whose latest verification answer is "no". */
  no: number;
  /** Households that answered at all. */
  answered: number;
}

/** Time of the latest "verification calls started" event, or null when there is none. */
export function verifyStartedAt(events: TicketEvent[]): string | null {
  let latest: string | null = null;
  for (const e of events) {
    if (eventKey(e.kind, e.detail) !== 'verify_started') continue;
    if (latest === null || e.at > latest) latest = e.at;
  }
  return latest;
}

/** The IST dates whose VERIFY check-ins belong to a round that started at `since` (at most 3). */
export function verifyDates(since: string, today: IsoDate): IsoDate[] {
  const start = istDate(new Date(since));
  const from = start < addDays(today, -2) ? addDays(today, -2) : start;
  return dateRange(from, today);
}

/**
 * Counts the current round's answers: VERIFY check-ins captured at or after `since`, taking the
 * latest attempt per household. Unanswered calls never count as yes.
 */
export function verifyTally(checkins: CheckInMasked[], since: string | null): VerifyTally {
  const sinceMs = since ? Date.parse(since) : -Infinity;
  const latest = new Map<string, CheckInMasked>();
  for (const c of checkins) {
    if (c.purpose !== 'VERIFY' || Date.parse(c.captured_at) < sinceMs) continue;
    const prev = latest.get(c.household_id);
    if (!prev || c.attempt > prev.attempt || (c.attempt === prev.attempt && c.captured_at > prev.captured_at)) {
      latest.set(c.household_id, c);
    }
  }
  const tally: VerifyTally = { yes: 0, no: 0, answered: 0 };
  for (const c of latest.values()) {
    if (c.outcome !== 'ANSWERED') continue;
    tally.answered += 1;
    if (c.water === 'YES') tally.yes += 1;
    else if (c.water === 'NO') tally.no += 1;
  }
  return tally;
}
