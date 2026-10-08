/** Display formatting. Every helper returns Hindi first and English second. */

import type { IsoDate, IsoDateTime } from '../api/types';
import { IST, ageMs, istNoon } from './time';

export interface Bilingual {
  hi: string;
  en: string;
}

const dayMonth = (locale: string) =>
  new Intl.DateTimeFormat(locale, { timeZone: IST, day: 'numeric', month: 'short' });
const dayMonthLong = (locale: string) =>
  new Intl.DateTimeFormat(locale, { timeZone: IST, day: 'numeric', month: 'long', year: 'numeric' });
const weekday = (locale: string) =>
  new Intl.DateTimeFormat(locale, { timeZone: IST, weekday: 'short' });
const clock = new Intl.DateTimeFormat('en-GB', {
  timeZone: IST,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const fmtHiShort = dayMonth('hi-IN');
const fmtEnShort = dayMonth('en-IN');
const fmtHiLong = dayMonthLong('hi-IN');
const fmtEnLong = dayMonthLong('en-IN');
const fmtHiWeekday = weekday('hi-IN');
const fmtEnWeekday = weekday('en-IN');
const numberFmt = new Intl.NumberFormat('en-IN');

/** "8 अक्टू॰" / "8 Oct" for a calendar date. */
export function shortDate(date: IsoDate): Bilingual {
  const d = istNoon(date);
  return { hi: fmtHiShort.format(d), en: fmtEnShort.format(d) };
}

/** "8 अक्टूबर 2026" / "8 October 2026". */
export function longDate(date: IsoDate): Bilingual {
  const d = istNoon(date);
  return { hi: fmtHiLong.format(d), en: fmtEnLong.format(d) };
}

/** "गुरु" / "Thu". */
export function weekdayName(date: IsoDate): Bilingual {
  const d = istNoon(date);
  return { hi: fmtHiWeekday.format(d), en: fmtEnWeekday.format(d) };
}

/** "10:42" in IST. */
export function clockTime(at: IsoDateTime): string {
  return clock.format(new Date(at));
}

/** "8 अक्टू॰, 10:42" / "8 Oct, 10:42 IST". */
export function dateTime(at: IsoDateTime): Bilingual {
  const d = new Date(at);
  const t = clock.format(d);
  return { hi: `${fmtHiShort.format(d)}, ${t}`, en: `${fmtEnShort.format(d)}, ${t} IST` };
}

/** Indian digit grouping: 7,603 and 1,23,456. */
export function num(value: number): string {
  return numberFmt.format(value);
}

/** "5 मिनट पहले" / "5 min ago", coarsening to hours and days. */
export function relative(at: IsoDateTime, now: Date = new Date()): Bilingual {
  const mins = Math.round(ageMs(at, now) / 60_000);
  if (mins < 1) return { hi: 'अभी', en: 'just now' };
  if (mins < 60) return { hi: `${mins} मिनट पहले`, en: `${mins} min ago` };
  const hours = Math.round(mins / 60);
  if (hours < 24) return { hi: `${hours} घंटे पहले`, en: `${hours} h ago` };
  const days = Math.round(hours / 24);
  return { hi: `${days} दिन पहले`, en: `${days} ${days === 1 ? 'day' : 'days'} ago` };
}

/** "+91XXXXXX1234" from any E.164 number, for numbers the API did not mask. */
export function maskPhone(e164: string): string {
  const digits = e164.replace(/\D/g, '');
  if (digits.length < 4) return 'XXXX';
  const country = e164.startsWith('+91') ? '+91' : '+';
  return `${country}XXXXXX${digits.slice(-4)}`;
}
