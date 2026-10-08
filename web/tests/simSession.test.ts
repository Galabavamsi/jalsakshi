import { describe, expect, it } from 'vitest';
import type { Action } from '../src/api/types';
import {
  initialSimState,
  keyPress,
  simReducer,
  timerRunning,
  type SimState,
} from '../src/lib/simSession';

const greet: Action = { type: 'play', prompt_key: 'household.greet', text_hi: 'Namaste', audio_url: '/a/greet.mp3' };
const askWater: Action = {
  type: 'get_digits',
  num_digits: 1,
  timeout_s: 8,
  prompts: [{ prompt_key: 'household.q_water', text_hi: 'Paani aaya?', audio_url: '/a/q.mp3' }],
};

function connected(actions: Action[] = [greet, askWater]): SimState {
  const dialing = simReducer(initialSimState, { type: 'dial' });
  return simReducer(dialing, { type: 'connected', callId: 'c1', actions });
}

describe('simulator state', () => {
  it('shows prompts, queues their audio and waits for digits', () => {
    const s = connected();
    expect(s.phase).toBe('live');
    expect(s.screen?.key).toBe('household.q_water');
    expect(s.audio).toEqual(['/a/greet.mp3', '/a/q.mp3']);
    expect(s.waiting).toMatchObject({ kind: 'digits', numDigits: 1, timeoutS: 8 });
    expect(s.log.map((e) => e.who)).toEqual(['ivr', 'ivr']);
  });

  it('starts the answer timer only after prompt audio has played', () => {
    let s = connected();
    expect(timerRunning(s)).toBe(false);
    s = simReducer(s, { type: 'audio_done' });
    s = simReducer(s, { type: 'audio_done' });
    expect(timerRunning(s)).toBe(true);
  });

  it('sends a single digit at once for a one-digit question', () => {
    expect(keyPress(connected(), '2')).toEqual({ buffer: '', submit: { digits: '2' } });
  });

  it('collects multi-digit answers until full or #', () => {
    const s = connected([{ ...askWater, num_digits: 2 } as Action]);
    const first = keyPress(s, '1');
    expect(first).toEqual({ buffer: '1', submit: null });
    const withBuffer = simReducer(s, { type: 'buffer', buffer: '1' });
    expect(keyPress(withBuffer, '#')).toEqual({ buffer: '', submit: { digits: '1' } });
    expect(keyPress(withBuffer, '2')).toEqual({ buffer: '', submit: { digits: '12' } });
  });

  it('ignores keys when no answer is expected', () => {
    const playing = connected([greet]);
    expect(keyPress(playing, '1').submit).toBeNull();
    expect(keyPress(initialSimState, '1').submit).toBeNull();
  });

  it('lets # skip a recording', () => {
    const s = connected([{ type: 'record', max_s: 15 }]);
    expect(keyPress(s, '5').submit).toBeNull();
    expect(keyPress(s, '#').submit).toEqual({ digits: '#' });
  });

  it('drops queued audio when the caller presses a key (barge-in)', () => {
    const s = simReducer(connected(), { type: 'sending', input: { digits: '1' } });
    expect(s.audio).toEqual([]);
    expect(s.phase).toBe('sending');
    expect(s.log.at(-1)).toMatchObject({ who: 'caller', en: 'Pressed 1' });
  });

  it('ends the call on hangup or done', () => {
    const sent = simReducer(connected(), { type: 'sending', input: { timeout: true } });
    const ended = simReducer(sent, {
      type: 'received',
      actions: [{ type: 'play', prompt_key: 'household.bye', text_hi: 'Dhanyavaad' }, { type: 'hangup' }],
      done: true,
    });
    expect(ended.phase).toBe('ended');
    expect(ended.waiting).toBeNull();
    expect(ended.log.filter((e) => e.en === 'Call ended')).toHaveLength(1);
  });

  it('keeps a policy deny for display', () => {
    const denied = { denied: true as const, policy_id: 'consent-required', reason_hi: 'नहीं', reason_en: 'No consent' };
    const s = simReducer(initialSimState, { type: 'failed', message: 'No consent', denied });
    expect(s.phase).toBe('failed');
    expect(s.denied).toEqual(denied);
  });
});
