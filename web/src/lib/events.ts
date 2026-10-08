/** Turns ticket events into words: who did it and what the detail fields mean. */

import type { DayStatusValue, OperatorRole, TicketEvent, WaterAnswer } from '../api/types';
import { DAY_STATUSES } from '../api/types';
import type { Bilingual } from './format';
import { ROLE, STATUS, WATER } from './labels';

/** Display names for operator and household ids, built from the village detail. */
export type People = Record<string, Bilingual>;

const SYSTEM_ACTORS: Record<string, Bilingual> = {
  'system:reconcile': { hi: 'प्रणाली: दिन का हिसाब', en: 'System: day reconciler' },
  'system:ticket-flow': { hi: 'प्रणाली: शिकायत प्रवाह', en: 'System: ticket flow' },
  'system:verify': { hi: 'प्रणाली: घरों से पुष्टि', en: 'System: household verification' },
  'system:escalation': { hi: 'प्रणाली: PHED को भेजना (सिम्युलेटेड)', en: 'System: escalation (simulated)' },
};

/** "Who" for an event actor id. */
export function actorLabel(actor: string, people: People): Bilingual {
  const known = SYSTEM_ACTORS[actor] ?? people[actor];
  if (known) return known;
  if (actor.startsWith('operator:')) {
    const id = actor.slice('operator:'.length);
    return people[id] ?? { hi: `नल जल मित्र ${id}`, en: `Operator ${id}` };
  }
  if (actor.startsWith('console:')) {
    const who = actor.slice('console:'.length);
    return { hi: `कंसोल: ${who}`, en: `Console user ${who}` };
  }
  if (actor.startsWith('system:')) return { hi: 'प्रणाली', en: `System (${actor.slice(7)})` };
  return { hi: actor, en: actor };
}

export interface DetailEntry {
  label: Bilingual;
  value: string;
}

const COUNT_LABELS: Record<string, Bilingual> = {
  answered: { hi: 'जवाब', en: 'answered' },
  yes: { hi: 'हाँ', en: 'yes' },
  no: { hi: 'नहीं', en: 'no' },
  partial: { hi: 'थोड़ा', en: 'partial' },
  dirty: { hi: 'गंदा', en: 'dirty' },
  unreachable: { hi: 'संपर्क नहीं', en: 'unreachable' },
  households: { hi: 'घर', en: 'households' },
  verify_yes: { hi: 'पुष्टि में हाँ', en: 'confirmed yes' },
  verify_no: { hi: 'पुष्टि में ना', en: 'said no' },
  quorum: { hi: 'ज़रूरी पुष्टि', en: 'needed' },
};

const VIA: Record<string, Bilingual> = {
  DTMF: { hi: 'फ़ोन कीपैड से', en: 'phone keypad' },
  SPEECH: { hi: 'बोलकर', en: 'speech' },
  SIMULATOR: { hi: 'सिम्युलेटर से', en: 'simulator' },
  console: { hi: 'कंसोल से', en: 'console' },
};

/** `note` is already the event's label (see labels.eventKey). */
const HIDDEN = new Set(['call_id', 'note']);

function isRole(value: unknown): value is OperatorRole {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(ROLE, value);
}

function isWater(value: unknown): value is WaterAnswer {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(WATER, value);
}

function isStatus(value: unknown): value is DayStatusValue {
  return typeof value === 'string' && (DAY_STATUSES as readonly string[]).includes(value);
}

function entryFor(key: string, value: unknown, people: People): DetailEntry | null {
  if (value === null || value === undefined || HIDDEN.has(key)) return null;
  if (key === 'to' && isRole(value)) {
    return { label: { hi: 'किसे भेजी', en: 'sent to' }, value: `${ROLE[value].hi} (${ROLE[value].en})` };
  }
  if ((key === 'day_status' || key === 'status') && isStatus(value)) {
    return { label: { hi: 'दिन की स्थिति', en: 'day status' }, value: `${STATUS[value].hi} (${STATUS[value].en})` };
  }
  const count = COUNT_LABELS[key];
  if (count) return { label: count, value: String(value) };
  if (key === 'via') {
    const via = VIA[String(value)];
    return { label: { hi: 'कैसे', en: 'via' }, value: via ? `${via.hi} (${via.en})` : String(value) };
  }
  if (key === 'operator_id' || key === 'household_id') {
    const who = people[String(value)];
    return { label: { hi: 'किसे', en: 'who' }, value: who ? `${who.hi} (${who.en})` : String(value) };
  }
  if (key === 'digits') return { label: { hi: 'दबाया', en: 'pressed' }, value: String(value) };
  if (key === 'water') {
    const water = isWater(value) ? WATER[value] : null;
    return {
      label: { hi: 'जवाब', en: 'answer' },
      value: water ? `${water.hi} (${water.en})` : String(value),
    };
  }
  if (key === 'rule_version') return { label: { hi: 'नियम', en: 'rule' }, value: String(value) };
  if (key === 'policy_id') return { label: { hi: 'Cedar नियम', en: 'policy' }, value: String(value) };
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
  return { label: { hi: key, en: key.replace(/_/g, ' ') }, value: text };
}

/** The event's detail object as labelled rows, in a stable order. */
export function detailEntries(event: TicketEvent, people: People): DetailEntry[] {
  return Object.entries(event.detail ?? {})
    .map(([key, value]) => entryFor(key, value, people))
    .filter((e): e is DetailEntry => e !== null);
}

/** Events oldest first; the API does not promise an order. */
export function sortedEvents(events: TicketEvent[]): TicketEvent[] {
  return [...events].sort((a, b) => a.at.localeCompare(b.at));
}
