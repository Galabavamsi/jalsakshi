/**
 * Pure helpers behind Home, Complaints and Families: plain counts and plain sentences.
 * Every decision (day status, ticket state) comes from the API; this only summarises it.
 */

import type {
  DayStatus,
  DayStatusValue,
  HouseholdMasked,
  IsoDateTime,
  Operator,
  Ticket,
  TicketState,
  WaterPoint,
} from '../api/types';
import type { Bilingual } from './format';
import { effectiveConsent } from './households';
import { IST, ageMs, istDate } from './time';

// ------------------------------------------------------------------ families

export type FamilyStatus = 'AGREED' | 'WAITING' | 'SAID_NO';

export function familyStatus(h: HouseholdMasked): FamilyStatus {
  const c = effectiveConsent(h);
  if (c === 'GRANTED') return 'AGREED';
  if (c === 'NONE') return 'WAITING';
  return 'SAID_NO';
}

export const FAMILY_STATUS: Record<FamilyStatus, Bilingual> = {
  AGREED: { en: 'Agreed', hi: 'सहमत' },
  WAITING: { en: 'Waiting for their call', hi: 'कॉल का इंतज़ार' },
  SAID_NO: { en: 'Said no', hi: 'मना किया' },
};

export interface FamilyCounts {
  agreed: number;
  waiting: number;
  saidNo: number;
  total: number;
}

export function familyCounts(households: ReadonlyArray<HouseholdMasked>): FamilyCounts {
  const out: FamilyCounts = { agreed: 0, waiting: 0, saidNo: 0, total: 0 };
  for (const h of households) {
    if (!h.active) continue;
    out.total += 1;
    const s = familyStatus(h);
    if (s === 'AGREED') out.agreed += 1;
    else if (s === 'WAITING') out.waiting += 1;
    else out.saidNo += 1;
  }
  return out;
}

// ------------------------------------------------------------------ today's water

export type WaterWord = DayStatusValue | 'NONE';

export const WATER_WORD: Record<WaterWord, Bilingual> = {
  SUPPLIED: { en: 'Water came', hi: 'पानी आया' },
  NO_SUPPLY: { en: 'No water', hi: 'पानी नहीं आया' },
  PARTIAL: { en: 'Some water', hi: 'थोड़ा पानी' },
  DIRTY: { en: 'Dirty water', hi: 'गंदा पानी' },
  UNVERIFIED: { en: 'Not enough answers yet', hi: 'अभी पूरे जवाब नहीं' },
  NONE: { en: 'Not enough answers yet', hi: 'अभी पूरे जवाब नहीं' },
};

export interface WaterLine {
  /** Water source name, or null for the whole village. */
  name: Bilingual | null;
  status: WaterWord;
}

/** One line per active water source (or one for the village when it has none). */
export function waterLines(today: DayStatus | null | undefined, points: ReadonlyArray<WaterPoint>): WaterLine[] {
  const active = points.filter((p) => p.active);
  if (active.length === 0) return [{ name: null, status: today?.status ?? 'NONE' }];
  return active.map((p) => {
    const found = today?.points?.find((s) => s.water_point_id === p.id);
    const status: WaterWord = found?.status ?? (active.length === 1 && today ? today.status : 'NONE');
    return { name: { en: p.name, hi: p.name_hi || p.name }, status };
  });
}

// ------------------------------------------------------------------ complaints

const FIXING_STATES: ReadonlyArray<TicketState> = ['ASSIGNED', 'OPERATOR_REPORTED_FIXED', 'VERIFYING'];

export function isClosed(t: Pick<Ticket, 'state'>): boolean {
  return t.state === 'CLOSED_VERIFIED';
}

/** The status word shown on a complaint row. */
export const COMPLAINT_WORD: Record<TicketState, Bilingual> = {
  OPEN: { en: 'New', hi: 'नई' },
  REOPENED: { en: 'Still not fixed', hi: 'अब भी ठीक नहीं' },
  ESCALATED: { en: 'Needs PHED help', hi: 'PHED की मदद चाहिए' },
  ASSIGNED: { en: 'Pump operator told', hi: 'पंप ऑपरेटर को बताया' },
  OPERATOR_REPORTED_FIXED: { en: 'Operator says fixed', hi: 'ऑपरेटर कहता है ठीक' },
  VERIFYING: { en: 'Asking families', hi: 'परिवारों से पूछ रहे हैं' },
  CLOSED_VERIFIED: { en: 'Fixed, families confirmed', hi: 'ठीक हुआ, परिवारों ने पुष्टि की' },
};

export interface ComplaintCounts {
  open: number;
  fixing: number;
  closedThisWeek: number;
}

export function complaintCounts(tickets: ReadonlyArray<Ticket>, now: Date): ComplaintCounts {
  const weekAgo = now.getTime() - 7 * 86_400_000;
  return {
    open: tickets.filter((t) => !isClosed(t)).length,
    fixing: tickets.filter((t) => FIXING_STATES.includes(t.state)).length,
    closedThisWeek: tickets.filter((t) => isClosed(t) && new Date(t.updated_at).getTime() >= weekAgo).length,
  };
}

/** Open complaints, oldest first. */
export function openComplaints(tickets: ReadonlyArray<Ticket>): Ticket[] {
  return tickets.filter((t) => !isClosed(t)).sort((a, b) => a.opened_at.localeCompare(b.opened_at));
}

/** "#4" or a short id. */
export function complaintNo(t: Pick<Ticket, 'number' | 'id'>): string {
  return t.number != null ? `#${t.number}` : `#${t.id.slice(-4)}`;
}

/** "5 hours" / "3 days". */
export function howLong(at: IsoDateTime, now: Date): Bilingual {
  const hours = Math.max(0, Math.floor(ageMs(at, now) / 3_600_000));
  if (hours < 1) return { en: 'less than an hour', hi: 'एक घंटे से कम' };
  if (hours < 24) return { en: `${hours} ${hours === 1 ? 'hour' : 'hours'}`, hi: `${hours} घंटे` };
  const days = Math.floor(hours / 24);
  return { en: `${days} ${days === 1 ? 'day' : 'days'}`, hi: `${days} दिन` };
}

const clock = new Intl.DateTimeFormat('en-IN', { timeZone: IST, hour: 'numeric', minute: '2-digit', hour12: true });
const dayEn = new Intl.DateTimeFormat('en-IN', { timeZone: IST, day: 'numeric', month: 'short' });
const dayHi = new Intl.DateTimeFormat('hi-IN', { timeZone: IST, day: 'numeric', month: 'short' });

/** "7:10 pm" in IST. */
export function clockText(at: IsoDateTime): string {
  return clock.format(new Date(at)).replace(/\s?([ap])\.?m\.?/i, (_, x: string) => ` ${x.toLowerCase()}m`);
}

/** "Today 7:10 pm" / "Yesterday 6:02 pm" / "3 Oct, 7:10 pm". */
export function whenText(at: IsoDateTime, now: Date): Bilingual {
  const d = new Date(at);
  const t = clockText(at);
  const day = istDate(d);
  const today = istDate(now);
  const yesterday = istDate(new Date(now.getTime() - 86_400_000));
  if (day === today) return { en: `Today ${t}`, hi: `आज ${t}` };
  if (day === yesterday) return { en: `Yesterday ${t}`, hi: `कल ${t}` };
  return { en: `${dayEn.format(d)}, ${t}`, hi: `${dayHi.format(d)}, ${t}` };
}

const REASON_SAID: Record<string, Bilingual> = {
  NO_SUPPLY: { en: 'said no water', hi: 'ने कहा पानी नहीं आया' },
  DIRTY: { en: 'said the water was dirty', hi: 'ने कहा पानी गंदा था' },
  LOW_PRESSURE: { en: 'said the water was too little', hi: 'ने कहा पानी बहुत कम था' },
  LEAK: { en: 'reported a leak', hi: 'ने रिसाव बताया' },
  BROKEN: { en: 'reported a broken pump', hi: 'ने पंप ख़राब बताया' },
  OTHER: { en: 'reported a problem', hi: 'ने समस्या बताई' },
};

function families(n: number): Bilingual {
  return { en: n === 1 ? '1 family' : `${n} families`, hi: n === 1 ? '1 परिवार' : `${n} परिवारों` };
}

const KIND_KEYS: Record<string, string> = {
  NOTIFIED: 'notified',
  OPERATOR_FIXED: 'operator_fixed',
  VERIFY_STARTED: 'verify_started',
  VERIFIED_OK: 'closed_verified',
  VERIFY_FAILED: 'reopened',
  ESCALATED: 'escalated',
  OPENED: 'opened',
};

const EVENT_TEXT: Record<string, Bilingual> = {
  notified: { en: 'Pump operator was called', hi: 'पंप ऑपरेटर को कॉल किया गया' },
  operator_fixed: { en: 'Pump operator said it is fixed', hi: 'पंप ऑपरेटर ने कहा ठीक हो गया' },
  verify_started: { en: 'Families were asked if water is back', hi: 'परिवारों से पूछा गया कि पानी आया या नहीं' },
  verify_answer: { en: 'A family answered', hi: 'एक परिवार ने जवाब दिया' },
  reopened: { en: 'Families said water is still not back', hi: 'परिवारों ने कहा पानी अब भी नहीं आया' },
  closed_verified: { en: 'Closed: families confirmed water is back', hi: 'बंद: परिवारों ने पुष्टि की कि पानी आ गया' },
  close_denied: { en: 'Someone tried to close it; families had not confirmed yet', hi: 'बंद करने की कोशिश हुई; परिवारों ने अभी पुष्टि नहीं की थी' },
  escalated: { en: 'Marked as needing PHED help', hi: 'PHED की मदद के लिए चिह्नित' },
  day_still_bad: { en: 'Still a problem the next day', hi: 'अगले दिन भी समस्या' },
  another_report: { en: 'Another family reported the same problem', hi: 'एक और परिवार ने यही समस्या बताई' },
  operator_reason: { en: 'Pump operator said why it is not fixed yet', hi: 'पंप ऑपरेटर ने बताया अभी क्यों ठीक नहीं हुआ' },
  voice_note: { en: 'A family left a voice message', hi: 'एक परिवार ने आवाज़ संदेश छोड़ा' },
};

/** How many families reported it: the larger of the reporter list and the "no" answers that opened it. */
export function reporterCount(ticket: Ticket): number {
  const opened = ticket.events.find((e) => e.kind.toUpperCase() === 'OPENED' || e.detail.note === 'OPENED');
  const no = typeof opened?.detail.no === 'number' ? opened.detail.no : 0;
  return Math.max(1, ticket.reporters?.length ?? 0, no);
}

export interface TimelineLine {
  at: IsoDateTime;
  text: Bilingual;
}

/** The complaint's events as short plain sentences, oldest first. */
export function timelineLines(ticket: Ticket): TimelineLine[] {
  return ticket.events.map((e) => {
    const raw = e.kind === 'NOTE' && typeof e.detail.note === 'string' ? e.detail.note : e.kind;
    const key = KIND_KEYS[raw] ?? raw;
    if (key === 'opened') {
      const who = families(reporterCount(ticket));
      const said = REASON_SAID[ticket.reason] ?? (REASON_SAID.OTHER as Bilingual);
      return { at: e.at, text: { en: `${who.en} ${said.en}`, hi: `${who.hi} ${said.hi}` } };
    }
    const known = EVENT_TEXT[key];
    if (known) return { at: e.at, text: known };
    if (e.to_state) return { at: e.at, text: COMPLAINT_WORD[e.to_state] };
    const words = key.replace(/[_-]+/g, ' ').toLowerCase();
    return { at: e.at, text: { en: words.charAt(0).toUpperCase() + words.slice(1), hi: words } };
  });
}

// ------------------------------------------------------------------ what to do now

export type TodoAction = { kind: 'link'; to: string } | { kind: 'call' };

export interface Todo {
  text: Bilingual;
  button: Bilingual;
  action: TodoAction;
}

export interface TodoInput {
  vid: string;
  households: ReadonlyArray<HouseholdMasked>;
  operators: ReadonlyArray<Operator>;
  tickets: ReadonlyArray<Ticket>;
  now: Date;
}

/** At most three plain sentences, most urgent first, each with one button. */
export function todos({ vid, households, operators, tickets, now }: TodoInput): Todo[] {
  const base = `/villages/${encodeURIComponent(vid)}`;
  const out: Todo[] = [];
  if (!operators.some((o) => o.role === 'NAL_JAL_MITRA')) {
    out.push({
      text: { en: "Add the pump operator's number so complaints reach someone.", hi: 'पंप ऑपरेटर का नंबर जोड़ें ताकि शिकायतें किसी तक पहुँचें।' },
      button: { en: 'Add number', hi: 'नंबर जोड़ें' },
      action: { kind: 'link', to: `${base}/more/team` },
    });
  }
  const fam = familyCounts(households);
  if (fam.total === 0) {
    out.push({
      text: { en: "Add families' mobile numbers so JalSakshi can start calling.", hi: 'परिवारों के मोबाइल नंबर जोड़ें ताकि जल साक्षी कॉल शुरू कर सके।' },
      button: { en: 'Add families', hi: 'परिवार जोड़ें' },
      action: { kind: 'link', to: `${base}/families?add=1` },
    });
  }
  for (const t of openComplaints(tickets)) {
    if (out.length >= 3) break;
    const days = Math.floor(ageMs(t.opened_at, now) / 86_400_000);
    const no = complaintNo(t);
    if (t.state === 'OPERATOR_REPORTED_FIXED' || t.state === 'VERIFYING') {
      out.push({
        text: { en: `Complaint ${no}: the pump operator says it is fixed. Families are being asked to confirm.`, hi: `शिकायत ${no}: पंप ऑपरेटर कहता है ठीक हो गया। परिवारों से पुष्टि पूछी जा रही है।` },
        button: { en: 'See complaint', hi: 'शिकायत देखें' },
        action: { kind: 'link', to: `${base}/complaints/${encodeURIComponent(t.id)}` },
      });
    } else if (days >= 2) {
      out.push({
        text: { en: `Complaint ${no} is ${days} days old. Call the pump operator.`, hi: `शिकायत ${no} ${days} दिन पुरानी है। पंप ऑपरेटर को फ़ोन करें।` },
        button: { en: 'See complaint', hi: 'शिकायत देखें' },
        action: { kind: 'link', to: `${base}/complaints/${encodeURIComponent(t.id)}` },
      });
    }
  }
  if (fam.waiting > 0 && out.length < 3) {
    const n = fam.waiting;
    out.push({
      text: {
        en: `${n === 1 ? '1 family has' : `${n} families have`} not agreed yet. They get their call today.`,
        hi: `${n} परिवारों ने अभी सहमति नहीं दी है। उन्हें आज कॉल जाएगी।`,
      },
      button: { en: 'See families', hi: 'परिवार देखें' },
      action: { kind: 'link', to: `${base}/families` },
    });
  }
  return out.slice(0, 3);
}

/** True while the village has no daily answers at all yet (its first days on JalSakshi). */
export function isDayOne(days: ReadonlyArray<DayStatus>): boolean {
  return !days.some((d) => d.counts.answered > 0);
}

/** "7 pm" from "19:00". */
export function callTimeText(hhmm: string | null | undefined): Bilingual {
  const [h = 19, m = 0] = (hhmm || '19:00').split(':').map(Number);
  const suffix = h >= 12 ? 'pm' : 'am';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  const en = m ? `${h12}:${String(m).padStart(2, '0')} ${suffix}` : `${h12} ${suffix}`;
  const hiPart = h >= 17 ? 'शाम' : h >= 12 ? 'दोपहर' : 'सुबह';
  return { en, hi: `${hiPart} ${h12}${m ? `:${String(m).padStart(2, '0')}` : ''} बजे` };
}
