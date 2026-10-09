/**
 * English + Hindi words for every enum the console shows (DESIGN.md §8). One place, so wording
 * stays the same on every screen. Plain words only: "complaint", "families", "water source";
 * never the enum name, "ticket", "household" or "quorum".
 */

import type {
  AccessKind,
  BlockerCode,
  BroadcastKind,
  BroadcastState,
  CallOutcome,
  CleanAnswer,
  ConsentAction,
  ConsentStatus,
  DayStatusValue,
  Fallback,
  Freshness,
  HgjStatus,
  OperatorRole,
  Purpose,
  QualityMethod,
  QualityResult,
  TicketOrigin,
  TicketReason,
  TicketState,
  WaterAnswer,
  WaterPointKind,
} from '../api/types';
import type { Bilingual } from './format';

export interface StatusLabel extends Bilingual {
  /** One word for tight spaces (older screens). */
  short: Bilingual;
  /** What the status means, for popovers and legends. */
  meaning: Bilingual;
}

/** A day's water status, always shown with an icon and a colour too (StatusPill). */
export const STATUS: Record<DayStatusValue, StatusLabel> = {
  SUPPLIED: {
    en: 'Water came',
    hi: 'पानी आया',
    short: { en: 'Came', hi: 'आया' },
    meaning: { en: 'Families said water came', hi: 'परिवारों ने बताया कि पानी आया' },
  },
  PARTIAL: {
    en: 'Some water',
    hi: 'थोड़ा पानी',
    short: { en: 'Some', hi: 'थोड़ा' },
    meaning: { en: 'Some families got little or no water', hi: 'कुछ परिवारों को कम या बिल्कुल पानी नहीं मिला' },
  },
  NO_SUPPLY: {
    en: 'No water',
    hi: 'पानी नहीं आया',
    short: { en: 'None', hi: 'नहीं' },
    meaning: { en: 'Most families got no water', hi: 'ज़्यादातर परिवारों को पानी नहीं मिला' },
  },
  DIRTY: {
    en: 'Dirty water',
    hi: 'गंदा पानी',
    short: { en: 'Dirty', hi: 'गंदा' },
    meaning: { en: 'Families said the water was dirty', hi: 'परिवारों ने बताया कि पानी गंदा था' },
  },
  UNVERIFIED: {
    en: 'Not enough answers',
    hi: 'पूरे जवाब नहीं',
    short: { en: 'Too few', hi: 'कम जवाब' },
    meaning: {
      en: 'Too few families answered to decide the day',
      hi: 'दिन तय करने के लिए बहुत कम परिवारों ने जवाब दिया',
    },
  },
};

/** A day with no calls at all (no DayStatus). */
export const NO_CALL: Bilingual = { en: 'No call', hi: 'कॉल नहीं हुई' };

/** Order of concern, worst first: used to pick the one status a summary leads with. */
export const DAY_STATUS_SEVERITY: Record<DayStatusValue, number> = {
  NO_SUPPLY: 4,
  DIRTY: 3,
  PARTIAL: 2,
  UNVERIFIED: 1,
  SUPPLIED: 0,
};

/** The worst status in a list, or null for an empty list. */
export function worstStatus(values: ReadonlyArray<DayStatusValue>): DayStatusValue | null {
  let worst: DayStatusValue | null = null;
  for (const v of values) {
    if (worst === null || DAY_STATUS_SEVERITY[v] > DAY_STATUS_SEVERITY[worst]) worst = v;
  }
  return worst;
}

/** Complaint states (TicketStatePill). */
export const TICKET_STATE: Record<TicketState, Bilingual> = {
  OPEN: { en: 'New', hi: 'नई' },
  ASSIGNED: { en: 'With operator', hi: 'ऑपरेटर के पास' },
  OPERATOR_REPORTED_FIXED: { en: 'Operator says fixed', hi: 'ऑपरेटर के अनुसार ठीक' },
  VERIFYING: { en: 'Checking with families', hi: 'परिवारों से पूछ रहे हैं' },
  CLOSED_VERIFIED: { en: 'Fixed · confirmed', hi: 'ठीक हुई · पुष्टि हुई' },
  REOPENED: { en: 'Reopened', hi: 'फिर से खुली' },
  ESCALATED: { en: 'Needs PHED help', hi: 'PHED की मदद चाहिए' },
};

/** What the complaint is about. */
export const REASON: Record<TicketReason, Bilingual> = {
  NO_SUPPLY: { en: 'No water', hi: 'पानी नहीं आया' },
  DIRTY: { en: 'Dirty water', hi: 'गंदा पानी' },
  LOW_PRESSURE: { en: 'Low pressure', hi: 'पानी का दबाव कम' },
  LEAK: { en: 'Leak', hi: 'रिसाव' },
  BROKEN: { en: 'Broken pump', hi: 'पंप ख़राब' },
  OTHER: { en: 'Other problem', hi: 'दूसरी समस्या' },
};

export const ROLE: Record<OperatorRole, Bilingual> = {
  NAL_JAL_MITRA: { en: 'Pump operator (Nal Jal Mitra)', hi: 'पंप ऑपरेटर (नल जल मित्र)' },
  SARPANCH: { en: 'Sarpanch', hi: 'सरपंच' },
  PANCHAYAT_SECRETARY: { en: 'Panchayat secretary', hi: 'पंचायत सचिव' },
  PHED_AE_SIM: { en: 'PHED assistant engineer (simulated)', hi: 'PHED सहायक अभियंता (सिम्युलेटेड)' },
  PHED_EE_SIM: { en: 'PHED executive engineer (simulated)', hi: 'PHED कार्यपालन अभियंता (सिम्युलेटेड)' },
  HANDPUMP_MECHANIC: { en: 'Handpump mechanic', hi: 'हैंडपंप मिस्त्री' },
};

/** Short role words for tight places ("Ramesh, pump operator"). */
export const ROLE_SHORT: Record<OperatorRole, Bilingual> = {
  NAL_JAL_MITRA: { en: 'pump operator', hi: 'पंप ऑपरेटर' },
  SARPANCH: { en: 'sarpanch', hi: 'सरपंच' },
  PANCHAYAT_SECRETARY: { en: 'Panchayat secretary', hi: 'पंचायत सचिव' },
  PHED_AE_SIM: { en: 'PHED engineer (simulated)', hi: 'PHED अभियंता (सिम्युलेटेड)' },
  PHED_EE_SIM: { en: 'PHED engineer (simulated)', hi: 'PHED अभियंता (सिम्युलेटेड)' },
  HANDPUMP_MECHANIC: { en: 'handpump mechanic', hi: 'हैंडपंप मिस्त्री' },
};

/** A role from GET /api/me (a plain string there), with a readable fallback. */
export function roleLabel(role: string | null | undefined): Bilingual | null {
  if (!role) return null;
  return ROLE[role as OperatorRole] ?? { en: role, hi: role };
}

/** Kind of water source. */
export const WATER_POINT_KIND: Record<WaterPointKind, Bilingual> = {
  PIPED: { en: 'Tap supply', hi: 'नल जल' },
  HANDPUMP: { en: 'Handpump', hi: 'हैंडपंप' },
  BOREWELL: { en: 'Borewell or well', hi: 'बोरवेल या कुआँ' },
  TANKER: { en: 'Tanker', hi: 'टैंकर' },
  OTHER: { en: 'Other source', hi: 'दूसरा स्रोत' },
};

/** How a family draws its water (Household.access). */
export const ACCESS: Record<AccessKind, Bilingual> = {
  HOUSE_TAP: { en: 'House tap', hi: 'घर का नल' },
  STANDPOST: { en: 'Public tap', hi: 'सार्वजनिक नल' },
  HANDPUMP: { en: 'Handpump', hi: 'हैंडपंप' },
  BOREWELL: { en: 'Borewell or well', hi: 'बोरवेल या कुआँ' },
  TANKER: { en: 'Tanker', hi: 'टैंकर' },
  OTHER: { en: 'Other', hi: 'दूसरा' },
};

/** A family's agreement to calls (ConsentPill). */
export const CONSENT_STATUS: Record<ConsentStatus, Bilingual> = {
  NONE: { en: 'Waiting for their call', hi: 'कॉल का इंतज़ार' },
  GRANTED: { en: 'Agreed', hi: 'सहमत' },
  DECLINED: { en: 'Said no', hi: 'मना किया' },
  WITHDRAWN: { en: 'Stopped calls', hi: 'कॉल बंद करवाए' },
};

/** Everything ConsentPill can show: the consent states plus a call in progress and under 18. */
export type ConsentPillValue = ConsentStatus | 'CALLING' | 'MINOR';

export const CONSENT_PILL: Record<ConsentPillValue, Bilingual> = {
  ...CONSENT_STATUS,
  CALLING: { en: 'Calling…', hi: 'कॉल जा रही है…' },
  MINOR: { en: 'Under 18', hi: '18 से कम उम्र' },
};

/** One entry of the consent record. */
export const CONSENT_ACTION: Record<ConsentAction, Bilingual> = {
  GRANTED: { en: 'Agreed', hi: 'सहमत' },
  DECLINED: { en: 'Said no', hi: 'मना किया' },
  WITHDRAWN: { en: 'Stopped calls', hi: 'कॉल बंद करवाए' },
  MINOR: { en: 'Under 18', hi: '18 से कम उम्र' },
};

export const CONSENT_CHANNEL: Record<string, Bilingual> = {
  ivr_keypad: { en: 'Phone keypad', hi: 'फ़ोन कीपैड' },
  in_person: { en: 'In person', hi: 'आमने-सामने' },
  console: { en: 'Office', hi: 'दफ़्तर' },
  voice: { en: 'By phone', hi: 'फ़ोन पर' },
};

/** How a family joined. */
export const REGISTERED_VIA: Record<'seed' | 'ivr' | 'console', Bilingual> = {
  seed: { en: 'First list', hi: 'पहली सूची' },
  ivr: { en: 'Missed call', hi: 'मिस्ड कॉल' },
  console: { en: 'Panchayat office', hi: 'पंचायत दफ़्तर' },
};

/** How a complaint came in. */
export const ORIGIN: Record<TicketOrigin, Bilingual> = {
  reconcile: { en: 'Daily call', hi: 'रोज़ की कॉल' },
  report: { en: 'Missed call', hi: 'मिस्ड कॉल' },
  voice_note: { en: 'Voice message', hi: 'आवाज़ संदेश' },
  console: { en: 'Panchayat office', hi: 'पंचायत दफ़्तर' },
};

/** Why the operator says it is not fixed yet (operator keys 2-5). */
export const BLOCKER: Record<BlockerCode, Bilingual> = {
  PARTS_NEEDED: { en: 'Parts needed', hi: 'पुर्ज़े चाहिए' },
  NO_POWER: { en: 'No electricity', hi: 'बिजली नहीं' },
  PIPE_BROKEN: { en: 'Pipe broken or leaking', hi: 'पाइप टूटा या रिस रहा' },
  NOT_MINE: { en: 'Not their source', hi: 'उनका स्रोत नहीं' },
};

/** A blocker code from analytics (a plain string there), with a readable fallback. */
export function blockerLabel(code: string): Bilingual {
  return BLOCKER[code as BlockerCode] ?? { en: code, hi: code };
}

/** A reason code from analytics (a plain string there), with a readable fallback. */
export function reasonLabel(code: string): Bilingual {
  return REASON[code as TicketReason] ?? { en: code, hi: code };
}

export const BROADCAST_KIND: Record<BroadcastKind, Bilingual> = {
  SUPPLY_CHANGE: { en: 'Supply time change', hi: 'पानी के समय में बदलाव' },
  BOIL_WATER: { en: 'Boil water', hi: 'पानी उबालकर पिएँ' },
  REPAIR_DONE: { en: 'Repair done', hi: 'मरम्मत पूरी' },
  MEETING: { en: 'Meeting', hi: 'बैठक' },
  CUSTOM: { en: 'Other', hi: 'दूसरी घोषणा' },
};

/** Announcement states (AnnouncementPill). */
export const BROADCAST_STATE: Record<BroadcastState, Bilingual> = {
  DRAFT: { en: 'Waiting for sarpanch', hi: 'सरपंच की मंज़ूरी बाकी' },
  APPROVED: { en: 'Ready to send', hi: 'भेजने के लिए तैयार' },
  SENT: { en: 'Sent', hi: 'भेजी गई' },
  CANCELLED: { en: 'Cancelled', hi: 'रद्द' },
};

export const QUALITY_METHOD: Record<QualityMethod, Bilingual> = {
  FTK: { en: 'Test kit', hi: 'टेस्ट किट' },
  LAB: { en: 'Lab', hi: 'लैब' },
};

/** A person's test result, worded to the parameters tested (never "the water is safe"). */
export const QUALITY_RESULT: Record<QualityResult, Bilingual> = {
  SAFE: { en: 'Within limits for the parameters tested', hi: 'जाँचे गए मानकों में ठीक' },
  UNSAFE: { en: 'Problem found in the test', hi: 'जाँच में गड़बड़ी मिली' },
};

/** QualityPill: a test result, or a test that is needed. */
export type QualityPillValue = QualityResult | 'NEEDED';

export const QUALITY_PILL: Record<QualityPillValue, Bilingual> = {
  SAFE: { en: 'Safe', hi: 'ठीक' },
  UNSAFE: { en: 'Unsafe', hi: 'ख़राब' },
  NEEDED: { en: 'Test needed', hi: 'जाँच ज़रूरी' },
};

export const FALLBACK: Record<Fallback, Bilingual> = {
  OTHER_SOURCE: { en: 'From another tap or handpump', hi: 'दूसरे नल या हैंडपंप से' },
  BOUGHT: { en: 'Bought water', hi: 'पानी ख़रीदा' },
  NONE: { en: 'Got no water', hi: 'पानी नहीं मिला' },
};

export const HGJ_STATUS: Record<HgjStatus, Bilingual> = {
  IN_PROGRESS: { en: 'Work in progress', hi: 'काम जारी' },
  REPORTED: { en: 'Reported Har Ghar Jal', hi: 'हर घर जल घोषित' },
  CERTIFIED: { en: 'Certified Har Ghar Jal', hi: 'हर घर जल प्रमाणित' },
};

export const FRESHNESS_LABEL: Record<Freshness, Bilingual> = {
  live: { en: 'live', hi: 'लाइव' },
  daily: { en: 'daily', hi: 'दैनिक' },
  annual: { en: 'yearly', hi: 'सालाना' },
  model: { en: 'estimate', hi: 'अनुमान' },
  simulated: { en: 'simulated', hi: 'सिम्युलेटेड' },
  replay: { en: 'replay', hi: 'रीप्ले' },
};

/** Kinds of phone call. */
export const PURPOSE: Record<Purpose, Bilingual> = {
  DAILY: { en: 'Daily question', hi: 'रोज़ का सवाल' },
  VERIFY: { en: 'Confirm a repair', hi: 'मरम्मत की पुष्टि' },
  OPERATOR: { en: 'Operator call', hi: 'ऑपरेटर को कॉल' },
  REGISTER: { en: 'Consent call', hi: 'सहमति कॉल' },
  REPORT: { en: 'Report a problem', hi: 'समस्या बताना' },
  BROADCAST: { en: 'Announcement call', hi: 'घोषणा कॉल' },
  SUMMARY: { en: 'Weekly summary call', hi: 'हफ़्ते का सारांश कॉल' },
};

export const WATER: Record<WaterAnswer, Bilingual> = {
  YES: { en: 'Yes', hi: 'हाँ, आया' },
  NO: { en: 'No', hi: 'नहीं आया' },
  PARTIAL: { en: 'A little', hi: 'थोड़ा आया' },
};

export const CLEAN: Record<CleanAnswer, Bilingual> = {
  YES: { en: 'Clean', hi: 'साफ़' },
  NO: { en: 'Dirty', hi: 'गंदा' },
};

export const OUTCOME: Record<CallOutcome, Bilingual> = {
  ANSWERED: { en: 'Answered', hi: 'जवाब दिया' },
  UNREACHABLE: { en: 'No answer', hi: 'जवाब नहीं मिला' },
  DECLINED: { en: 'Said no', hi: 'मना किया' },
};

const EVENT_KIND: Record<string, Bilingual> = {
  opened: { en: 'Complaint opened', hi: 'शिकायत दर्ज हुई' },
  notified: { en: 'Operator called', hi: 'ऑपरेटर को कॉल किया' },
  operator_fixed: { en: 'Operator said it is fixed', hi: 'ऑपरेटर ने ठीक बताया' },
  verify_started: { en: 'Families asked to confirm', hi: 'परिवारों से पुष्टि पूछी' },
  verify_answer: { en: 'A family answered', hi: 'एक परिवार ने जवाब दिया' },
  reopened: { en: 'A family said no water, reopened', hi: 'परिवार ने कहा पानी नहीं, फिर से खुली' },
  closed_verified: { en: 'Closed after families confirmed', hi: 'परिवारों की पुष्टि के बाद बंद' },
  close_denied: { en: 'Close tried, held back by the rule', hi: 'बंद करने की कोशिश, नियम ने रोका' },
  escalated: { en: 'Needs PHED help', hi: 'PHED की मदद चाहिए' },
  day_still_bad: {
    en: 'Still a problem the next day, kept in this complaint',
    hi: 'अगले दिन भी समस्या, इसी शिकायत में जोड़ा',
  },
  another_report: { en: 'Another family reported the same problem', hi: 'एक और परिवार ने यही समस्या बताई' },
  operator_reason: { en: 'Operator said why it is not fixed', hi: 'ऑपरेटर ने बताया क्यों ठीक नहीं हुआ' },
  quality_test: { en: 'Water test recorded', hi: 'पानी की जाँच दर्ज हुई' },
  voice_note: { en: 'Voice message added', hi: 'आवाज़ संदेश जुड़ा' },
  note: { en: 'Note', hi: 'टिप्पणी' },
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

/** Label for a complaint event key: known kinds first, then the target state, then the raw kind. */
export function eventLabel(kind: string, toState?: TicketState | null): Bilingual {
  const known = EVENT_KIND[kind];
  if (known) return known;
  if (toState) return TICKET_STATE[toState];
  const words = kind.replace(/[_-]+/g, ' ').trim();
  return { en: words.charAt(0).toUpperCase() + words.slice(1), hi: words };
}

/** True for every state that still needs work. */
export function isOpenState(state: TicketState): boolean {
  return state !== 'CLOSED_VERIFIED';
}

/** Open complaints the operator has not reported fixed yet. */
export const WAITING_FOR_FIX: ReadonlyArray<TicketState> = ['OPEN', 'ASSIGNED', 'REOPENED', 'ESCALATED'];

/** Complaints the operator says are fixed, while families are asked. */
export const BEING_CHECKED: ReadonlyArray<TicketState> = ['OPERATOR_REPORTED_FIXED', 'VERIFYING'];
