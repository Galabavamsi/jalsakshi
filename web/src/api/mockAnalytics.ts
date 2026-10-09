/**
 * Mock-mode mirrors of core/analytics.py, core/summary.py, handlers/public.py and
 * data/official.official_age_note, so VITE_API_MODE=mock shows the same shapes and rules:
 * unknown days are excluded from reliability, a repair counts only once households confirmed
 * it, and the residents' view carries no names or phones.
 */

import { addDays, dateRange, istDate } from '../lib/time';
import { effectiveConsent } from '../lib/households';
import type { MockState } from './mockSeed';
import type {
  BroadcastAnalytics,
  DayStatus,
  DayStatusValue,
  Freshness,
  HouseholdAnalytics,
  IsoDate,
  OfficialRecord,
  OpenTicketAge,
  PointAnalytics,
  PublicVillageView,
  QualityTest,
  Ticket,
  Village,
  VillageAnalytics,
  WaterPoint,
  WaterPointKind,
  WeeklySummary,
} from './types';

export const RULE_NOTE =
  'Unknown days are excluded from reliability and shown separately; resident-reported, not a household census.';
const SOURCE_NAME = 'JalSakshi household check-ins (resident-reported) (demo)';

const VERIFIED = new Set(['VERIFIED_OK', 'closed_verified']);
const FAILED = new Set(['VERIFY_FAILED', 'reopened']);

const ist = (at: string) => istDate(new Date(at));
const hours = (ms: number) => Math.max(0, ms / 3_600_000);
const round1 = (n: number) => Math.round(n * 10) / 10;

function pctOf(part: number, whole: number): number | null {
  return whole > 0 ? round1((part / whole) * 100) : null;
}

function tally(keys: Iterable<string>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const k of keys) out[k] = (out[k] ?? 0) + 1;
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => a.localeCompare(b)));
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return round1(s.length % 2 ? (s[mid] as number) : ((s[mid - 1] as number) + (s[mid] as number)) / 2);
}

const isOpen = (t: Ticket) => t.state !== 'CLOSED_VERIFIED';

function verifiedAt(t: Ticket): string | null {
  const e = t.events.find((x) => VERIFIED.has(x.kind));
  if (e) return e.at;
  return t.state === 'CLOSED_VERIFIED' ? t.updated_at : null;
}

interface Period {
  start: IsoDate;
  end: IsoDate;
  days: number;
}

const inPeriod = (p: Period, at: string) => {
  const d = ist(at);
  return d >= p.start && d <= p.end;
};

function pointStatusesFor(days: DayStatus[], wid: string | null): DayStatusValue[] {
  const out: DayStatusValue[] = [];
  for (const day of days) {
    const points = day.points ?? [];
    if (points.length === 0) {
      if (wid === null) out.push(day.status);
      continue;
    }
    for (const p of points) if ((p.water_point_id ?? null) === wid) out.push(p.status);
  }
  return out;
}

function pointAnalytics(
  wid: string | null,
  name: string | null,
  kind: WaterPointKind | null,
  statuses: DayStatusValue[],
  tickets: Ticket[],
  tests: QualityTest[],
  period: Period,
  now: Date,
): PointAnalytics {
  const count = (s: DayStatusValue) => statuses.filter((x) => x === s).length;
  const observed = statuses.filter((s) => s !== 'UNVERIFIED').length;
  const supplied = count('SUPPLIED');
  const openNow = tickets
    .filter((t) => isOpen(t) && Date.parse(t.opened_at) <= now.getTime() && ist(t.opened_at) <= period.end)
    .sort((a, b) => a.opened_at.localeCompare(b.opened_at));
  const repairs = tickets
    .map((t) => {
      const v = verifiedAt(t);
      return v && inPeriod(period, v) ? hours(Date.parse(v) - Date.parse(t.opened_at)) : null;
    })
    .filter((h): h is number => h !== null)
    .sort((a, b) => a - b);
  const dated = tests.filter((q) => ist(q.tested_at) <= period.end);
  const latest = dated.sort((a, b) => b.tested_at.localeCompare(a.tested_at))[0];
  const openTickets: OpenTicketAge[] = openNow.map((t) => ({
    ticket_id: t.id,
    number: t.number ?? null,
    reason: t.reason,
    state: t.state,
    age_hours: round1(hours(now.getTime() - Date.parse(t.opened_at))),
    blocker: t.blocker ?? null,
  }));
  return {
    water_point_id: wid,
    name,
    kind,
    days_in_period: period.days,
    observed,
    supplied,
    partial: count('PARTIAL'),
    no_supply: count('NO_SUPPLY'),
    dirty: count('DIRTY'),
    unknown: period.days - observed,
    reliability_pct: pctOf(supplied, observed),
    complaints_by_reason: tally(tickets.filter((t) => inPeriod(period, t.opened_at)).map((t) => t.reason)),
    open_tickets: openTickets,
    repairs_closed: repairs.length,
    median_repair_hours: median(repairs),
    worst_repair_hours: repairs.length ? round1(repairs[repairs.length - 1] as number) : null,
    reopened: tickets.reduce(
      (n, t) => n + t.events.filter((e) => FAILED.has(e.kind) && inPeriod(period, e.at)).length,
      0,
    ),
    blockers: tally(
      tickets.flatMap((t) =>
        t.events
          .filter(
            (e) =>
              (e.kind === 'NOTE' || e.kind === 'note') &&
              e.detail.note === 'operator_reason' &&
              typeof e.detail.code === 'string' &&
              inPeriod(period, e.at),
          )
          .map((e) => String(e.detail.code)),
      ),
    ),
    last_quality: latest
      ? { result: latest.result, method: latest.method, tested_at: latest.tested_at }
      : null,
    dirty_without_test: openNow.some(
      (t) =>
        t.reason === 'DIRTY' &&
        !tests.some(
          (q) => (q.water_point_id ?? null) === (t.water_point_id ?? null) && q.tested_at >= t.opened_at,
        ),
    ),
  };
}

function householdAnalytics(state: MockState, village: Village, period: Period): HouseholdAnalytics {
  const households = state.households.filter((h) => h.village_id === village.id);
  const status = households.map(effectiveConsent);
  const consented = households.filter((h) => h.active && effectiveConsent(h) === 'GRANTED').length;
  const checkins = state.checkins.filter(
    (c) => c.village_id === village.id && c.date >= period.start && c.date <= period.end,
  );
  const latest = new Map<string, (typeof checkins)[number]>();
  for (const c of checkins) {
    if (c.purpose !== 'DAILY') continue;
    const key = `${c.date}|${c.household_id}`;
    const prev = latest.get(key);
    if (!prev || c.attempt > prev.attempt) latest.set(key, c);
  }
  const called = latest.size;
  const answered = [...latest.values()].filter((c) => c.outcome === 'ANSWERED' && c.water).length;
  const census = village.census_households ?? null;
  return {
    registered: households.length,
    consented,
    withdrawn: status.filter((s) => s === 'WITHDRAWN').length,
    declined: status.filter((s) => s === 'DECLINED').length,
    pending: status.filter((s) => s === 'NONE').length,
    census_households: census,
    coverage_pct: pctOf(consented, census ?? 0),
    called,
    answered,
    answer_rate_pct: pctOf(answered, called),
    fallback_counts: tally(checkins.flatMap((c) => (c.fallback ? [c.fallback] : []))),
    reports_by_resident: checkins.filter((c) => c.purpose === 'REPORT').length,
    consent_events: tally(
      state.consents
        .filter((e) => e.village_id === village.id && inPeriod(period, e.at))
        .map((e) => e.action),
    ),
  };
}

function broadcastAnalytics(state: MockState, vid: string, period: Period): BroadcastAnalytics {
  const sent = state.broadcasts.filter(
    (b) => b.village_id === vid && b.state === 'SENT' && b.sent_at && inPeriod(period, b.sent_at),
  );
  return {
    sent: sent.length,
    recipients: sent.reduce((n, b) => n + b.recipients, 0),
    delivered: sent.reduce((n, b) => n + b.delivered, 0),
    heard: sent.reduce((n, b) => n + b.heard, 0),
  };
}

/** core/analytics.village_analytics for the demo store. */
export function mockAnalytics(
  state: MockState,
  village: Village,
  start: IsoDate,
  end: IsoDate,
  now: Date,
  freshness: Freshness = 'simulated',
): VillageAnalytics {
  const period: Period = { start, end, days: dateRange(start, end).length };
  const days = state.days
    .filter((d) => d.village_id === village.id && d.date >= start && d.date <= end)
    .sort((a, b) => a.date.localeCompare(b.date));
  const tickets = state.tickets.filter((t) => t.village_id === village.id);
  const tests = state.quality.filter((q) => q.village_id === village.id);
  const points = state.waterPoints.filter((p) => p.village_id === village.id);
  const ids: Array<string | null> = points.filter((p) => p.active).map((p) => p.id);
  const mentioned = new Set<string | null>();
  for (const d of days) {
    if (!d.points?.length) mentioned.add(null);
    for (const p of d.points ?? []) mentioned.add(p.water_point_id ?? null);
  }
  for (const t of tickets) mentioned.add(t.water_point_id ?? null);
  for (const wid of [...mentioned].filter((w): w is string => w !== null).sort()) {
    if (!ids.includes(wid)) ids.push(wid);
  }
  if (mentioned.has(null)) ids.push(null);
  const byId = new Map(points.map((p) => [p.id, p]));
  const pointRows = ids.map((wid) =>
    pointAnalytics(
      wid,
      wid ? (byId.get(wid)?.name ?? null) : null,
      wid ? (byId.get(wid)?.kind ?? null) : null,
      pointStatusesFor(days, wid),
      tickets.filter((t) => (t.water_point_id ?? null) === wid),
      tests.filter((q) => (q.water_point_id ?? null) === wid),
      period,
      now,
    ),
  );
  const totals = pointAnalytics(
    null,
    village.name,
    null,
    days.map((d) => d.status),
    tickets,
    tests,
    period,
    now,
  );
  const observedAt = days.reduce<string | null>(
    (m, d) => (!m || d.computed_at > m ? d.computed_at : m),
    null,
  );
  return {
    village_id: village.id,
    start,
    end,
    generated_at: now.toISOString(),
    source: {
      source: SOURCE_NAME,
      observed_at: observedAt,
      fetched_at: now.toISOString(),
      freshness,
      url: null,
    },
    rule_note: RULE_NOTE,
    points: pointRows,
    village: totals,
    households: householdAnalytics(state, village, period),
    broadcasts: broadcastAnalytics(state, village.id, period),
    tickets_opened: Object.values(totals.complaints_by_reason).reduce((a, b) => a + b, 0),
    tickets_closed_verified: totals.repairs_closed,
    median_repair_hours: totals.median_repair_hours,
  };
}

// ---------------------------------------------------------------- weekly summary (core/summary.py)

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;

/** core/summary.weekly_summary_text, same template and wording. */
export function mockWeeklySummary(
  village: Village,
  a: VillageAnalytics,
  points: WaterPoint[],
): WeeklySummary {
  const numbers: Record<string, number | null> = {};
  const hi: string[] = [];
  const en: string[] = [];
  const h = a.households;
  const nameHi = village.name_hi || village.name;
  hi.push(
    `Namaste, ${nameHi} gaon ki saptahik JalSakshi report: ${h.registered} ghar jude hain, ${h.consented} ne sahmati di hai.`,
  );
  en.push(
    `Namaste, weekly JalSakshi report for ${village.name}: ${count(h.registered, 'household')} registered, ${h.consented} consented.`,
  );
  Object.assign(numbers, { households_registered: h.registered, households_consented: h.consented });

  const rows = a.points.length ? a.points : [a.village];
  const named = new Map(points.map((p) => [p.id, p]));
  const restOfVillage = rows.some((p) => p.water_point_id !== null);
  const ranked = rows
    .map((p, i) => ({ p, i }))
    .sort((x, y) => {
      const kx = [x.p.reliability_pct === null ? 1 : 0, x.p.reliability_pct ?? 0, -x.p.no_supply, x.i];
      const ky = [y.p.reliability_pct === null ? 1 : 0, y.p.reliability_pct ?? 0, -y.p.no_supply, y.i];
      for (let k = 0; k < kx.length; k += 1)
        if (kx[k] !== ky[k]) return (kx[k] as number) - (ky[k] as number);
      return 0;
    })
    .slice(0, 3);
  for (const { p } of ranked) {
    const wid = p.water_point_id;
    const known = wid ? named.get(wid) : undefined;
    const labelHi = known
      ? known.name_hi || known.name
      : wid
        ? p.name || wid
        : restOfVillage
          ? 'baaki gaon'
          : `${nameHi} gaon`;
    const labelEn = known
      ? known.name
      : wid
        ? p.name || wid
        : restOfVillage
          ? 'the rest of the village'
          : village.name;
    const days = p.days_in_period;
    numbers.days = days;
    if (p.observed === 0) {
      hi.push(`Pichhle ${days} din mein ${labelHi} ki jaankari nahi mili.`);
      en.push(`Last ${days} days at ${labelEn}: no information received.`);
      continue;
    }
    const key = wid ?? 'village';
    let exHi = '';
    let exEn = '';
    if (p.partial) {
      exHi += `, ${p.partial} din thoda aaya`;
      exEn += `, partly on ${p.partial}`;
    }
    if (p.dirty) {
      exHi += `, ${p.dirty} din gandla paani`;
      exEn += `, dirty on ${p.dirty}`;
    }
    hi.push(
      `Pichhle ${days} din mein ${labelHi}: ${p.supplied} din paani aaya, ${p.no_supply} din nahi aaya${exHi}, ${p.unknown} din ki jaankari nahi.`,
    );
    en.push(
      `Last ${days} days at ${labelEn}: water came on ${count(p.supplied, 'day')}, did not come on ${p.no_supply}${exEn}, no information for ${p.unknown}.`,
    );
    Object.assign(numbers, {
      [`${key}.supplied`]: p.supplied,
      [`${key}.no_supply`]: p.no_supply,
      [`${key}.partial`]: p.partial,
      [`${key}.dirty`]: p.dirty,
      [`${key}.unknown`]: p.unknown,
    });
  }

  const open = a.village.open_tickets;
  numbers.open_complaints = open.length;
  if (open.length === 0) {
    hi.push('Abhi koi shikayat khuli nahi hai.');
    en.push('No complaint is open now.');
  } else {
    const oldest = Math.max(...open.map((t) => t.age_hours));
    const d = Math.floor(oldest / 24);
    const hr = Math.floor(oldest);
    let ageHi = 'kuch der';
    let ageEn = 'under an hour';
    if (d >= 1) {
      ageHi = `${d} din`;
      ageEn = count(d, 'day');
      numbers.oldest_open_days = d;
    } else if (hr >= 1) {
      ageHi = `${hr} ghante`;
      ageEn = count(hr, 'hour');
      numbers.oldest_open_hours = hr;
    }
    if (open.length === 1) {
      hi.push(`1 shikayat ${ageHi} se khuli hai.`);
      en.push(`1 complaint is open, for ${ageEn}.`);
    } else {
      hi.push(`${open.length} shikayat khuli hain, sabse purani ${ageHi} se.`);
      en.push(`${open.length} complaints are open; the oldest for ${ageEn}.`);
    }
  }

  const closed = a.tickets_closed_verified;
  numbers.closed_verified = closed;
  if (closed === 0) {
    hi.push('Is dauran koi shikayat gharon ki pushti se band nahi hui.');
    en.push('No complaint was closed with household confirmation in this period.');
  } else {
    let sHi = `${closed} shikayat gharon ki pushti ke baad band hui`;
    let sEn = `${count(closed, 'complaint')} closed after households confirmed water was back`;
    if (a.median_repair_hours !== null) {
      const m = Math.floor(a.median_repair_hours + 0.5);
      if (m >= 1) {
        sHi += `, marammat mein aam taur par ${m} ghante lage`;
        sEn += `; median repair time ${count(m, 'hour')}`;
        numbers.median_repair_hours = m;
      } else {
        sHi += ', marammat mein aam taur par ek ghante se kam laga';
        sEn += '; median repair time under an hour';
      }
    }
    hi.push(`${sHi}.`);
    en.push(`${sEn}.`);
  }
  hi.push('Poori report JalSakshi console par hai.');
  en.push('The full report is on the JalSakshi console.');
  return {
    village_id: village.id,
    start: a.start,
    end: a.end,
    text_hi: hi.join(' '),
    text_en: en.join(' '),
    numbers,
    source: a.source,
  };
}

// ---------------------------------------------------------------- official record age (data/official.py)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "Last official household tap test: 17 Aug 2023 (3 years ago)". */
export function officialAgeNote(record: OfficialRecord, now: Date): string {
  const tested = record.wq?.last_household_test;
  if (!tested) return 'No official household tap test on record';
  const today = istDate(now);
  const [ty, tm, td] = tested.split('-').map(Number) as [number, number, number];
  const [ny, nm, nd] = today.split('-').map(Number) as [number, number, number];
  let ago: string;
  if (tested > today) ago = 'in the future';
  else {
    const months = (ny - ty) * 12 + nm - tm - (nd < td ? 1 : 0);
    const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'} ago`;
    if (months >= 12) ago = plural(Math.floor(months / 12), 'year');
    else if (months >= 1) ago = plural(months, 'month');
    else {
      const days = dateRange(tested, today).length - 1;
      ago = days === 0 ? 'today' : plural(days, 'day');
    }
  }
  return `Last official household tap test: ${td} ${MONTHS[tm - 1]} ${ty} (${ago})`;
}

// ---------------------------------------------------------------- residents' view (handlers/public.py)

/** handlers/public.public_view for the demo store: village-level facts, no names or phones. */
export function mockPublicView(state: MockState, village: Village, now: Date): PublicVillageView {
  const today = istDate(now);
  const start = addDays(today, -29);
  const points = state.waterPoints.filter((p) => p.village_id === village.id);
  const byId = new Map(points.map((p) => [p.id, p]));
  const tickets = state.tickets.filter((t) => t.village_id === village.id);
  const closed = tickets.filter((t) => !isOpen(t));
  const repairHours = closed
    .map((t) => {
      const v = t.events.find((e) => VERIFIED.has(e.kind))?.at;
      return v ? hours(Date.parse(v) - Date.parse(t.opened_at)) : null;
    })
    .filter((h): h is number => h !== null);
  const official = state.official[village.id];
  return {
    village: {
      id: village.id,
      name: village.name,
      name_hi: village.name_hi ?? null,
      gram_panchayat: village.gram_panchayat ?? null,
      block: village.block,
      district: village.district,
      lgd_code: village.lgd_code ?? null,
    },
    generated_at: now.toISOString(),
    water_points: points
      .filter((p) => p.active)
      .map((p) => ({ id: p.id, name: p.name, name_hi: p.name_hi ?? null, kind: p.kind })),
    days: state.days
      .filter((d) => d.village_id === village.id && d.date >= start && d.date <= today)
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((d) => ({
        date: d.date,
        status: d.status,
        points: (d.points ?? []).map((p) => ({ water_point_id: p.water_point_id ?? null, status: p.status })),
        answered: d.counts.answered,
      })),
    open_complaints: tickets
      .filter(isOpen)
      .sort((a, b) => a.opened_at.localeCompare(b.opened_at))
      .map((t) => ({
        number: t.number ?? null,
        reason: t.reason,
        water_point: t.water_point_id ? (byId.get(t.water_point_id)?.name ?? null) : null,
        water_point_hi: t.water_point_id ? (byId.get(t.water_point_id)?.name_hi ?? null) : null,
        state: t.state,
        opened_at: t.opened_at,
        age_hours: round1(hours(now.getTime() - Date.parse(t.opened_at))),
        families: (t.reporters ?? []).length,
      })),
    repairs_confirmed: { count: closed.length, median_hours: median(repairHours) },
    announcements: state.broadcasts
      .filter((b) => b.village_id === village.id && b.state === 'SENT' && b.sent_at)
      .map((b) => ({ kind: b.kind, text_hi: b.text_hi, sent_at: b.sent_at as string }))
      .slice(0, 10),
    families_reporting: state.households.filter(
      (h) => h.village_id === village.id && h.active && effectiveConsent(h) === 'GRANTED',
    ).length,
    official: official
      ? {
          households: official.households,
          tap_connections: official.tap_connections,
          hgj_status: official.hgj_status,
          water_quality_note: officialAgeNote(official, now),
          source: official.source,
        }
      : null,
    sources: [
      "Families' answers by phone (JalSakshi): resident-reported, not a household census (demo)",
      'Government record: JJM IMIS / WQMIS public dashboard, as entered by the state (demo stand-in)',
    ],
    missed_call_number: '+918064260325',
  };
}
