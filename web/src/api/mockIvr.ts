/**
 * A small in-browser IVR for mock mode. It follows the same steps as voice/flow.py
 * (ARCHITECTURE.md §9): every question re-prompts once on timeout or invalid input, then moves on
 * with the answer stored as null, never guessed.
 */

import type { Action, CleanAnswer, PromptRef, Purpose, WaterAnswer } from './types';

/** Mirrors prompts/hi.yaml (version 1): the romanised Hindi that is rendered to audio. */
export const PROMPTS = {
  'household.greet':
    'Namaste. JalSakshi se bol rahe hain. Aapke gaon ke nal ke paani ke baare mein teen chhote sawaal hain.',
  'household.q_water':
    'Aaj nal mein paani aaya? Haan ke liye ek, nahi ke liye do, thoda sa aaya to teen dabaiye.',
  'household.q_hours': 'Kitne ghante paani aaya? Shunya se nau tak number dabaiye.',
  'household.q_clean': 'Paani saaf tha? Saaf ke liye ek, gandla ke liye do dabaiye.',
  'household.q_note':
    'Kuch aur batana ho to beep ke baad pandrah second bolein. Nahi to hash dabaiye.',
  'household.bye': 'Dhanyavaad. Aapka jawab gaon ki Gram Sabha tak pahunchega.',
  'household.invalid': 'Maaf kijiye, samajh nahi aaya. Phir se sunte hain.',
  'verify.greet':
    'Namaste. JalSakshi se bol rahe hain. Aapne bataya tha ki nal mein paani nahi aa raha tha.',
  'verify.q_water': 'Kya ab nal mein paani aa raha hai? Haan ke liye ek, nahi ke liye do dabaiye.',
  'verify.bye': 'Dhanyavaad. Aapki pushti ke bina shikayat band nahi hogi.',
  'operator.greet': 'Namaste. JalSakshi se Nal Jal Mitra ke liye soochna hai.',
  'operator.summary_no_supply': 'Aaj gaon ke {households} gharon ne bataya ki nal mein paani nahi aaya.',
  'operator.summary_dirty': 'Aaj gaon ke {households} gharon ne bataya ki paani gandla tha.',
  'operator.q_fixed': 'Agar samasya theek ho gayi hai to ek dabaiye. Abhi nahi to do dabaiye.',
  'operator.ack_fixed': 'Dhanyavaad. Hum gharon se pushti karenge, phir shikayat band hogi.',
  'operator.ack_pending': 'Theek hai. Marammat ho jaane par Panchayat ko batayein, phir gharon se pushti hogi.',
} as const;

export type PromptKey = keyof typeof PROMPTS;

type QuestionStep = 'Q_WATER' | 'Q_HOURS' | 'Q_CLEAN' | 'V_WATER' | 'OP_FIXED';
export type IvrStep = QuestionStep | 'Q_NOTE' | 'DONE';

export interface IvrAnswers {
  water: WaterAnswer | null;
  hours: number | null;
  clean: CleanAnswer | null;
  fixed: boolean | null;
}

export interface IvrSession {
  purpose: Purpose;
  step: IvrStep;
  retried: boolean;
  answers: IvrAnswers;
}

export interface IvrInput {
  digits?: string;
  timeout?: boolean;
}

export interface IvrTurn {
  session: IvrSession;
  actions: Action[];
  done: boolean;
}

export interface OperatorSummary {
  reason: 'NO_SUPPLY' | 'DIRTY';
  households: number;
}

const QUESTION: Record<QuestionStep, PromptKey> = {
  Q_WATER: 'household.q_water',
  Q_HOURS: 'household.q_hours',
  Q_CLEAN: 'household.q_clean',
  V_WATER: 'verify.q_water',
  OP_FIXED: 'operator.q_fixed',
};

const TIMEOUT_S = 8;

function ref(key: PromptKey, vars: Record<string, string | number> = {}): PromptRef {
  const text = PROMPTS[key].replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? ''));
  return { prompt_key: key, text_hi: text, audio_url: null };
}

function play(key: PromptKey, vars?: Record<string, string | number>): Action {
  return { type: 'play', ...ref(key, vars) };
}

function ask(step: QuestionStep): Action {
  return { type: 'get_digits', num_digits: 1, timeout_s: TIMEOUT_S, prompts: [ref(QUESTION[step])] };
}

function goodbye(key: PromptKey): Action[] {
  return [play(key), { type: 'hangup' }];
}

const NOTE_ACTIONS: Action[] = [play('household.q_note'), { type: 'record', max_s: 15 }];

const EMPTY_ANSWERS: IvrAnswers = { water: null, hours: null, clean: null, fixed: null };

/** Opens a call: greeting plus the first question. */
export function startIvr(purpose: Purpose, summary?: OperatorSummary): IvrTurn {
  const base = { purpose, retried: false, answers: { ...EMPTY_ANSWERS } };
  if (purpose === 'VERIFY') {
    return {
      session: { ...base, step: 'V_WATER' },
      actions: [play('verify.greet'), ask('V_WATER')],
      done: false,
    };
  }
  if (purpose === 'OPERATOR') {
    const actions: Action[] = [play('operator.greet')];
    if (summary) {
      const key = summary.reason === 'DIRTY' ? 'operator.summary_dirty' : 'operator.summary_no_supply';
      actions.push(play(key, { households: summary.households }));
    }
    actions.push(ask('OP_FIXED'));
    return { session: { ...base, step: 'OP_FIXED' }, actions, done: false };
  }
  return {
    session: { ...base, step: 'Q_WATER' },
    actions: [play('household.greet'), ask('Q_WATER')],
    done: false,
  };
}

const WATER_KEYS: Record<string, WaterAnswer> = { '1': 'YES', '2': 'NO', '3': 'PARTIAL' };
const YES_NO_WATER: Record<string, WaterAnswer> = { '1': 'YES', '2': 'NO' };
const CLEAN_KEYS: Record<string, CleanAnswer> = { '1': 'YES', '2': 'NO' };

/** Parses keypad digits for a question; undefined means "invalid, ask again". */
export function parseDigits(step: QuestionStep, digits: string | undefined): unknown {
  if (!digits) return undefined;
  switch (step) {
    case 'Q_WATER':
      return WATER_KEYS[digits];
    case 'V_WATER':
      return YES_NO_WATER[digits];
    case 'Q_CLEAN':
      return CLEAN_KEYS[digits];
    case 'Q_HOURS':
      return /^[0-9]$/.test(digits) ? Number(digits) : undefined;
    case 'OP_FIXED':
      return digits === '1' ? true : digits === '2' ? false : undefined;
  }
}

/** Advances the call by one keypad input or timeout. */
export function stepIvr(session: IvrSession, input: IvrInput): IvrTurn {
  if (session.step === 'DONE') return { session, actions: [{ type: 'hangup' }], done: true };
  if (session.step === 'Q_NOTE') {
    return { session: { ...session, step: 'DONE' }, actions: goodbye('household.bye'), done: true };
  }
  const step = session.step;
  const value = input.timeout ? undefined : parseDigits(step, input.digits);
  if (value === undefined && !session.retried) {
    return {
      session: { ...session, retried: true },
      actions: [play('household.invalid'), ask(step)],
      done: false,
    };
  }
  return advance({ ...session, retried: false }, step, value ?? null);
}

function advance(session: IvrSession, step: QuestionStep, value: unknown): IvrTurn {
  const answers = { ...session.answers };
  const next = (to: IvrStep, actions: Action[], done = false): IvrTurn => ({
    session: { ...session, answers, step: to },
    actions,
    done,
  });
  switch (step) {
    case 'Q_WATER':
      answers.water = value as WaterAnswer | null;
      return answers.water === 'YES' || answers.water === 'PARTIAL'
        ? next('Q_HOURS', [ask('Q_HOURS')])
        : next('Q_NOTE', NOTE_ACTIONS);
    case 'Q_HOURS':
      answers.hours = value as number | null;
      return next('Q_CLEAN', [ask('Q_CLEAN')]);
    case 'Q_CLEAN':
      answers.clean = value as CleanAnswer | null;
      return next('Q_NOTE', NOTE_ACTIONS);
    case 'V_WATER':
      answers.water = value as WaterAnswer | null;
      return next('DONE', goodbye('verify.bye'), true);
    case 'OP_FIXED':
      answers.fixed = value as boolean | null;
      return next(
        'DONE',
        goodbye(answers.fixed ? 'operator.ack_fixed' : 'operator.ack_pending'),
        true,
      );
  }
}
