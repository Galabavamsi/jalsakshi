/**
 * State for the web-phone simulator: a pure reducer over IVR actions and keypad presses.
 * The page owns the network calls and timers; this module decides what the phone shows
 * and when a keypress should be sent.
 */

import type { Action, PolicyDenied, PromptRef, SimInputRequest } from '../api/types';

export type Phase = 'idle' | 'dialing' | 'live' | 'sending' | 'ended' | 'failed';

export interface PromptView {
  key: string;
  text: string;
  audioUrl: string | null;
}

export interface LogEntry {
  id: number;
  who: 'ivr' | 'caller' | 'system';
  hi: string;
  en?: string;
  key?: string;
}

export interface Waiting {
  /** Digits to collect before sending (get_digits) or 0 for a recording. */
  numDigits: number;
  timeoutS: number;
  kind: 'digits' | 'record';
  /** Changes for every new wait, so timers restart. */
  seq: number;
}

export interface SimState {
  phase: Phase;
  callId: string | null;
  screen: PromptView | null;
  waiting: Waiting | null;
  buffer: string;
  /** Audio URLs still to play, in order. */
  audio: string[];
  log: LogEntry[];
  nextId: number;
  error: string | null;
  denied: PolicyDenied | null;
}

export type SimEvent =
  | { type: 'dial' }
  | { type: 'connected'; callId: string; actions: Action[] }
  | { type: 'sending'; input: SimInputRequest }
  | { type: 'received'; actions: Action[]; done: boolean }
  | { type: 'buffer'; buffer: string }
  | { type: 'audio_done' }
  | { type: 'hangup' }
  | { type: 'failed'; message: string; denied?: PolicyDenied | null }
  | { type: 'reset' };

export const initialSimState: SimState = {
  phase: 'idle',
  callId: null,
  screen: null,
  waiting: null,
  buffer: '',
  audio: [],
  log: [],
  nextId: 1,
  error: null,
  denied: null,
};

function addLog(state: SimState, entry: Omit<LogEntry, 'id'>): SimState {
  return { ...state, log: [...state.log, { ...entry, id: state.nextId }], nextId: state.nextId + 1 };
}

/** Accepts a prompt object or a bare prompt key, since §13 leaves the shape loose. */
function toPrompt(p: PromptRef | string): PromptView {
  if (typeof p === 'string') return { key: p, text: p, audioUrl: null };
  return { key: p.prompt_key, text: p.text_hi, audioUrl: p.audio_url ?? null };
}

function speak(state: SimState, prompt: PromptView): SimState {
  const next = addLog(state, { who: 'ivr', hi: prompt.text, key: prompt.key });
  return {
    ...next,
    screen: prompt,
    audio: prompt.audioUrl ? [...next.audio, prompt.audioUrl] : next.audio,
  };
}

function applyAction(state: SimState, action: Action): SimState {
  switch (action.type) {
    case 'play':
      return speak(state, toPrompt(action));
    case 'get_digits': {
      const spoken = (action.prompts ?? []).map(toPrompt).reduce(speak, state);
      return {
        ...spoken,
        waiting: {
          kind: 'digits',
          numDigits: Math.max(1, action.num_digits),
          timeoutS: action.timeout_s,
          seq: spoken.nextId,
        },
      };
    }
    case 'record': {
      const logged = addLog(state, {
        who: 'system',
        hi: 'बीप के बाद बोलने का समय। सिम्युलेटर आवाज़ रिकॉर्ड नहीं करता, # दबाकर आगे बढ़ें।',
        en: 'Time to speak after the beep. The simulator does not record; press # to continue.',
      });
      return {
        ...logged,
        waiting: { kind: 'record', numDigits: 0, timeoutS: action.max_s, seq: logged.nextId },
      };
    }
    case 'hangup':
      return endCall(state);
  }
}

function endCall(state: SimState): SimState {
  if (state.phase === 'ended') return state;
  const logged = addLog(state, { who: 'system', hi: 'कॉल समाप्त', en: 'Call ended' });
  return { ...logged, phase: 'ended', waiting: null, buffer: '' };
}

/** Applies a batch of IVR actions in order. */
export function applyActions(state: SimState, actions: Action[]): SimState {
  const cleared: SimState = { ...state, waiting: null, buffer: '' };
  return actions.reduce(applyAction, cleared);
}

function inputLog(input: SimInputRequest): Omit<LogEntry, 'id'> {
  if (input.timeout) {
    return { who: 'caller', hi: 'कोई बटन नहीं दबाया (समय समाप्त)', en: 'No key pressed (timed out)' };
  }
  return { who: 'caller', hi: `दबाया: ${input.digits ?? ''}`, en: `Pressed ${input.digits ?? ''}` };
}

export function simReducer(state: SimState, event: SimEvent): SimState {
  switch (event.type) {
    case 'dial':
      return { ...initialSimState, phase: 'dialing' };
    case 'connected': {
      const live = { ...state, phase: 'live' as const, callId: event.callId };
      return applyActions(live, event.actions);
    }
    case 'sending': {
      // Pressing a key interrupts the prompt (barge-in), so queued audio is dropped.
      const logged = addLog(state, inputLog(event.input));
      return { ...logged, phase: 'sending', waiting: null, buffer: '', audio: [] };
    }
    case 'received': {
      const next = applyActions({ ...state, phase: 'live' }, event.actions);
      return event.done ? endCall(next) : next;
    }
    case 'buffer':
      return { ...state, buffer: event.buffer };
    case 'audio_done':
      return { ...state, audio: state.audio.slice(1) };
    case 'hangup':
      return { ...endCall(state), audio: [] };
    case 'failed':
      return {
        ...state,
        phase: 'failed',
        waiting: null,
        audio: [],
        error: event.message,
        denied: event.denied ?? null,
      };
    case 'reset':
      return initialSimState;
  }
}

/**
 * What a keypress does: the new digit buffer, and the input to send if the press completes
 * an answer. `#` ends a multi-digit answer early, or skips a recording.
 */
export function keyPress(
  state: SimState,
  key: string,
): { buffer: string; submit: SimInputRequest | null } {
  const waiting = state.waiting;
  if (state.phase !== 'live' || !waiting) return { buffer: state.buffer, submit: null };
  if (waiting.kind === 'record') {
    return { buffer: '', submit: key === '#' ? { digits: '#' } : null };
  }
  if (key === '#') return { buffer: '', submit: { digits: state.buffer || '#' } };
  const buffer = state.buffer + key;
  if (buffer.length >= waiting.numDigits) return { buffer: '', submit: { digits: buffer } };
  return { buffer, submit: null };
}

/** True when the caller is expected to act and no prompt audio is still playing. */
export function timerRunning(state: SimState): boolean {
  return state.phase === 'live' && state.waiting !== null && state.audio.length === 0;
}
