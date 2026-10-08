/** Date helpers pinned to India Standard Time, whatever the browser's time zone. */

import type { IsoDate, IsoDateTime } from '../api/types';

export const IST = 'Asia/Kolkata';
const IST_OFFSET = '+05:30';

const isoDateFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: IST,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const hourFmt = new Intl.DateTimeFormat('en-GB', { timeZone: IST, hour: '2-digit', hour12: false });

/** The IST calendar date of an instant, "YYYY-MM-DD". */
export function istDate(at: Date): IsoDate {
  return isoDateFmt.format(at);
}

/** The IST hour (0-23) of an instant. */
export function istHour(at: Date): number {
  return Number(hourFmt.format(at)) % 24;
}

/** Adds whole days to a calendar date. */
export function addDays(date: IsoDate, days: number): IsoDate {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Every date from `from` to `to`, inclusive. Empty when `to` is before `from`. */
export function dateRange(from: IsoDate, to: IsoDate): IsoDate[] {
  const out: IsoDate[] = [];
  for (let d = from; d <= to && out.length < 400; d = addDays(d, 1)) out.push(d);
  return out;
}

/** The instant of a local IST wall-clock time on a date, e.g. ("2026-10-08", "10:30"). */
export function istInstant(date: IsoDate, hhmm: string): Date {
  return new Date(`${date}T${hhmm}:00${IST_OFFSET}`);
}

/** Noon IST on a date: a safe instant for formatting a calendar day. */
export function istNoon(date: IsoDate): Date {
  return istInstant(date, '12:00');
}

/** Milliseconds between an ISO time and now (positive when in the past). */
export function ageMs(at: IsoDateTime, now: Date = new Date()): number {
  return now.getTime() - new Date(at).getTime();
}

/** Shifts an instant by minutes. */
export function minutesFrom(at: Date, minutes: number): Date {
  return new Date(at.getTime() + minutes * 60_000);
}
