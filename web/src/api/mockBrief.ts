/**
 * Template Gram Sabha brief for mock mode. Same shape as GET /api/villages/{vid}/brief with
 * generated_by "template"; every number in the text comes from `numbers`.
 */

import { longDate, shortDate } from '../lib/format';
import { istDate } from '../lib/time';
import { REASON, STATUS, TICKET_STATE } from '../lib/labels';
import { demoSource } from './mockSeed';
import type { Brief, DayStatus, DayStatusValue, IsoDate, Ticket, Village } from './types';

export interface BriefInput {
  village: Village;
  days: DayStatus[];
  tickets: Ticket[];
  households: number;
  from: IsoDate;
  to: IsoDate;
  now: Date;
}

function countStatuses(days: DayStatus[]): Record<DayStatusValue, number> {
  const out: Record<DayStatusValue, number> = {
    SUPPLIED: 0,
    PARTIAL: 0,
    NO_SUPPLY: 0,
    DIRTY: 0,
    UNVERIFIED: 0,
  };
  for (const d of days) out[d.status] += 1;
  return out;
}

const yesNo = (v: boolean | null | undefined): string =>
  v === true ? 'हाँ' : v === false ? 'नहीं' : 'जानकारी नहीं';

function ticketLine(t: Ticket): string {
  const opened = shortDate(istDate(new Date(t.opened_at))).hi;
  return `- ${REASON[t.reason].hi}: ${opened} को खुली। अभी की स्थिति: ${TICKET_STATE[t.state].hi}।`;
}

function proposals(village: Village, supplied: number, total: number, open: Ticket[]): string[] {
  const out: string[] = [];
  if (open.length > 0) {
    out.push('खुली शिकायत बंद होने और घरों की पुष्टि मिलने तक योजना का हस्तांतरण टालें।');
  }
  if (village.claimed_hgj && supplied < total) {
    out.push('हर घर जल प्रमाणपत्र पर निर्णय से पहले इन दिनों की कमियों की सूची नल जल मित्र से लें।');
  }
  out.push('जिन घरों ने जवाब नहीं दिया, उनसे सहमति और सही फ़ोन नंबर की पुष्टि करें।');
  return out;
}

/** Builds the Hindi markdown sheet and its numbers. */
export function buildMockBrief(input: BriefInput): Brief {
  const { village, days, tickets, from, to, now } = input;
  const counts = countStatuses(days);
  const open = tickets.filter((t) => t.state !== 'CLOSED_VERIFIED');
  const closed = tickets.length - open.length;
  const numbers = {
    days: days.length,
    supplied: counts.SUPPLIED,
    partial: counts.PARTIAL,
    no_supply: counts.NO_SUPPLY,
    dirty: counts.DIRTY,
    unverified: counts.UNVERIFIED,
    households: input.households,
    tickets_opened: tickets.length,
    tickets_closed_verified: closed,
  };
  const rows = (Object.keys(counts) as DayStatusValue[])
    .map((s) => `| ${STATUS[s].hi} | ${counts[s]} |`)
    .join('\n');
  const markdown = [
    `# ग्राम सभा साक्ष्य पत्र: ${village.name}`,
    '',
    `${village.block} विकासखंड, ${village.district} ज़िला  `,
    `अवधि: ${longDate(from).hi} से ${longDate(to).hi} (${numbers.days} दिन)`,
    '',
    '> यह डेमो डेटा है। इस पत्र के सभी आँकड़े नमूना हैं।',
    '',
    '## राज्य का दावा',
    '',
    `- हर घर जल घोषित: ${yesNo(village.claimed_hgj)}`,
    `- हर घर जल प्रमाणित: ${yesNo(village.hgj_certified)}`,
    '',
    '## घरों की गवाही',
    '',
    `रोज़ ${numbers.households} पंजीकृत घरों से फ़ोन पर पूछा गया: "आज नल में पानी आया?"`,
    '',
    '| दिन की स्थिति | दिन |',
    '|---|---|',
    rows,
    '',
    `${numbers.days} में से ${numbers.supplied} दिन घरों ने पूरा पानी आने की बात कही।`,
    '',
    '## शिकायतें',
    '',
    tickets.length ? tickets.map(ticketLine).join('\n') : 'इस अवधि में कोई शिकायत नहीं खुली।',
    '',
    `कुल ${numbers.tickets_opened} शिकायतें, जिनमें से ${numbers.tickets_closed_verified} घरों की पुष्टि के बाद बंद हुईं।`,
    '',
    '## ग्राम सभा के लिए प्रस्ताव',
    '',
    ...proposals(village, numbers.supplied, numbers.days, open).map((p, i) => `${i + 1}. ${p}`),
  ].join('\n');
  return {
    markdown_hi: markdown,
    numbers,
    generated_by: 'template',
    sources: [
      demoSource('JalSakshi household check-ins', now, now),
      village.claimed_source ?? demoSource('JJM IMIS Har Ghar Jal report', now),
    ],
    generated_at: now.toISOString(),
  };
}
