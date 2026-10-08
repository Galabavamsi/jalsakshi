/** English + Hindi labels for every enum the console shows. One place, so wording stays consistent. */

import type {
  CallOutcome,
  CleanAnswer,
  DayStatusValue,
  Freshness,
  OperatorRole,
  Purpose,
  TicketReason,
  TicketState,
  WaterAnswer,
} from '../api/types';
import type { Bilingual } from './format';

export interface StatusLabel extends Bilingual {
  /** One word for tight spaces such as the 14-day strip and the 7-day tally. */
  short: Bilingual;
  /** What the status means, for tooltips and legends. */
  meaning: Bilingual;
}

export const STATUS: Record<DayStatusValue, StatusLabel> = {
  SUPPLIED: {
    hi: 'पानी आया',
    en: 'Water came',
    short: { hi: 'आया', en: 'Came' },
    meaning: { hi: 'घरों ने बताया कि पानी आया', en: 'Households said water came' },
  },
  PARTIAL: {
    hi: 'थोड़ा पानी',
    en: 'Partial supply',
    short: { hi: 'थोड़ा', en: 'Part' },
    meaning: { hi: 'कुछ घरों में पानी कम आया या नहीं आया', en: 'Some households got little or no water' },
  },
  NO_SUPPLY: {
    hi: 'पानी नहीं आया',
    en: 'No water',
    short: { hi: 'नहीं', en: 'None' },
    meaning: { hi: 'ज़्यादातर घरों में पानी नहीं आया', en: 'Most households got no water' },
  },
  DIRTY: {
    hi: 'गंदा पानी',
    en: 'Dirty water',
    short: { hi: 'गंदा', en: 'Dirty' },
    meaning: { hi: 'घरों ने बताया कि पानी गंदा था', en: 'Households said the water was dirty' },
  },
  UNVERIFIED: {
    hi: 'पुष्टि नहीं',
    en: 'Not confirmed',
    short: { hi: 'अपुष्ट', en: 'Few' },
    meaning: { hi: 'बहुत कम घरों ने जवाब दिया', en: 'Too few households answered' },
  },
};

export const TICKET_STATE: Record<TicketState, Bilingual> = {
  OPEN: { hi: 'खुली', en: 'Open' },
  ASSIGNED: { hi: 'नल जल मित्र को सौंपी', en: 'Assigned to operator' },
  OPERATOR_REPORTED_FIXED: { hi: 'मित्र ने ठीक बताया', en: 'Operator says fixed' },
  VERIFYING: { hi: 'घरों से पुष्टि जारी', en: 'Checking with households' },
  CLOSED_VERIFIED: { hi: 'घरों ने पुष्टि की, बंद', en: 'Closed, confirmed by households' },
  REOPENED: { hi: 'फिर से खुली', en: 'Reopened' },
  ESCALATED: { hi: 'PHED को भेजी (सिम्युलेटेड)', en: 'Escalated to PHED (simulated)' },
};

export const REASON: Record<TicketReason, Bilingual> = {
  NO_SUPPLY: { hi: 'पानी नहीं आया', en: 'No water' },
  DIRTY: { hi: 'गंदा पानी', en: 'Dirty water' },
};

export const ROLE: Record<OperatorRole, Bilingual> = {
  NAL_JAL_MITRA: { hi: 'नल जल मित्र', en: 'Pump operator (Nal Jal Mitra)' },
  SARPANCH: { hi: 'सरपंच', en: 'Sarpanch' },
  PANCHAYAT_SECRETARY: { hi: 'पंचायत सचिव', en: 'Panchayat Secretary' },
  PHED_AE_SIM: { hi: 'PHED सहायक अभियंता (सिम्युलेटेड)', en: 'PHED Assistant Engineer (simulated)' },
  PHED_EE_SIM: { hi: 'PHED कार्यपालन अभियंता (सिम्युलेटेड)', en: 'PHED Executive Engineer (simulated)' },
};

export const FRESHNESS_LABEL: Record<Freshness, Bilingual> = {
  live: { hi: 'लाइव', en: 'live' },
  daily: { hi: 'दैनिक', en: 'daily' },
  annual: { hi: 'वार्षिक', en: 'annual' },
  model: { hi: 'मॉडल अनुमान', en: 'model estimate' },
  simulated: { hi: 'सिम्युलेटेड', en: 'simulated' },
  replay: { hi: 'रीप्ले', en: 'replay' },
};

export const PURPOSE: Record<Purpose, Bilingual> = {
  DAILY: { hi: 'रोज़ की जाँच', en: 'Daily check-in' },
  VERIFY: { hi: 'मरम्मत की पुष्टि', en: 'Repair check' },
  OPERATOR: { hi: 'नल जल मित्र को कॉल', en: 'Operator call' },
};

export const WATER: Record<WaterAnswer, Bilingual> = {
  YES: { hi: 'हाँ, आया', en: 'Yes' },
  NO: { hi: 'नहीं आया', en: 'No' },
  PARTIAL: { hi: 'थोड़ा आया', en: 'A little' },
};

export const CLEAN: Record<CleanAnswer, Bilingual> = {
  YES: { hi: 'साफ़', en: 'Clean' },
  NO: { hi: 'गंदा', en: 'Dirty' },
};

export const OUTCOME: Record<CallOutcome, Bilingual> = {
  ANSWERED: { hi: 'जवाब दिया', en: 'Answered' },
  UNREACHABLE: { hi: 'संपर्क नहीं हुआ', en: 'Unreachable' },
  DECLINED: { hi: 'मना किया', en: 'Declined' },
};

const EVENT_KIND: Record<string, Bilingual> = {
  opened: { hi: 'शिकायत खुली', en: 'Ticket opened' },
  notified: { hi: 'नल जल मित्र को कॉल किया', en: 'Operator called' },
  operator_fixed: { hi: 'मित्र ने कहा ठीक हो गया', en: 'Operator reported fixed' },
  verify_started: { hi: 'घरों को पुष्टि के लिए कॉल', en: 'Verification calls started' },
  verify_answer: { hi: 'एक घर ने जवाब दिया', en: 'A household answered' },
  reopened: { hi: 'घर ने कहा पानी अभी नहीं, फिर खुली', en: 'A household said no water, reopened' },
  closed_verified: { hi: 'घरों ने पुष्टि की, बंद', en: 'Closed after households confirmed' },
  close_denied: { hi: 'बंद करने की कोशिश, नियम ने रोका', en: 'Close attempted, held back by a rule' },
  escalated: { hi: 'PHED को भेजी (सिम्युलेटेड)', en: 'Escalated to PHED (simulated)' },
  day_still_bad: { hi: 'अगले दिन भी समस्या, नई शिकायत नहीं', en: 'Still failing; no duplicate ticket' },
  note: { hi: 'टिप्पणी', en: 'Note' },
};

/** Ticket event kinds written by the backend (core.tickets.TicketEventKind) → label keys. */
const CORE_KIND: Record<string, string> = {
  NOTIFIED: 'notified',
  OPERATOR_FIXED: 'operator_fixed',
  VERIFY_STARTED: 'verify_started',
  VERIFIED_OK: 'closed_verified',
  VERIFY_FAILED: 'reopened',
  ESCALATED: 'escalated',
};

/**
 * The console's key for an event kind. Backend kinds are UPPERCASE; a `NOTE` event carries its
 * meaning in `detail.note` (e.g. `close_denied`, `day_still_bad`). Mock kinds pass through.
 */
export function eventKey(kind: string, detail?: Record<string, unknown> | null): string {
  if (kind === 'NOTE') {
    const note = detail?.note;
    return typeof note === 'string' && note ? note : 'note';
  }
  return CORE_KIND[kind] ?? kind;
}

/** Label for a ticket event key: known kinds first, then the target state, then the raw kind. */
export function eventLabel(kind: string, toState?: TicketState | null): Bilingual {
  const known = EVENT_KIND[kind];
  if (known) return known;
  if (toState) return TICKET_STATE[toState];
  const words = kind.replace(/[_-]+/g, ' ').trim();
  return { hi: words, en: words.charAt(0).toUpperCase() + words.slice(1) };
}

/** True for every state that still needs work. */
export function isOpenState(state: TicketState): boolean {
  return state !== 'CLOSED_VERIFIED';
}
