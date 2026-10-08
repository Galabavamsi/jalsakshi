import { useCallback, useEffect, useReducer, useRef, useState, type RefObject } from 'react';
import { PolicyDeniedError } from '../../api/client';
import { useApi } from '../../api/context';
import type { SimInputRequest, SimStartRequest } from '../../api/types';
import { describeError } from '../../components/PageState';
import {
  initialSimState,
  keyPress,
  simReducer,
  timerRunning,
  type SimState,
} from '../../lib/simSession';

export interface SimCall {
  state: SimState;
  start: (request: SimStartRequest) => Promise<void>;
  press: (key: string) => void;
  hangup: () => void;
  reset: () => void;
  /** Last pressed key, for a short visual flash. */
  flashKey: string | null;
  /** Bind to an <audio> element that plays prompt audio_url values in order. */
  audioProps: {
    ref: RefObject<HTMLAudioElement>;
    onEnded: () => void;
    onError: () => void;
  };
}

const KEY_PATTERN = /^[0-9*#]$/;

/** Drives one simulated call through /sim/calls, including timeouts and prompt audio. */
export function useSimCall(): SimCall {
  const api = useApi();
  const [state, dispatch] = useReducer(simReducer, initialSimState);
  const [flashKey, setFlashKey] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const audioToken = useRef(0);

  const fail = useCallback((error: unknown) => {
    dispatch({
      type: 'failed',
      message: describeError(error).en,
      denied: error instanceof PolicyDeniedError ? error.denied : null,
    });
  }, []);

  const send = useCallback(
    async (callId: string, input: SimInputRequest) => {
      dispatch({ type: 'sending', input });
      try {
        const res = await api.simInput(callId, input);
        dispatch({ type: 'received', actions: res.actions, done: res.done });
      } catch (error) {
        fail(error);
      }
    },
    [api, fail],
  );

  const start = useCallback(
    async (request: SimStartRequest) => {
      dispatch({ type: 'dial' });
      try {
        const res = await api.simStartCall(request);
        dispatch({ type: 'connected', callId: res.call_id, actions: res.actions });
      } catch (error) {
        fail(error);
      }
    },
    [api, fail],
  );

  const press = (key: string) => {
    setFlashKey(key);
    const { buffer, submit } = keyPress(state, key);
    dispatch({ type: 'buffer', buffer });
    if (submit && state.callId) void send(state.callId, submit);
  };
  const pressRef = useRef(press);
  pressRef.current = press;

  // Physical keyboard: digits, * and # work while a call is live.
  const live = state.phase === 'live';
  useEffect(() => {
    if (!live) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return;
      if (KEY_PATTERN.test(e.key)) pressRef.current(e.key);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [live]);

  useEffect(() => {
    if (!flashKey) return;
    const t = window.setTimeout(() => setFlashKey(null), 160);
    return () => window.clearTimeout(t);
  }, [flashKey]);

  // No answer within the prompt's timeout: tell the IVR, which re-prompts once then moves on.
  const running = timerRunning(state);
  const waitSeq = state.waiting?.seq;
  const waitSeconds = state.waiting?.timeoutS ?? 0;
  const callId = state.callId;
  useEffect(() => {
    if (!running || !callId || waitSeq === undefined) return;
    const t = window.setTimeout(() => void send(callId, { timeout: true }), waitSeconds * 1000);
    return () => window.clearTimeout(t);
  }, [running, waitSeq, waitSeconds, callId, send]);

  // Prompt audio plays in order; a failed or missing file is skipped, never blocks the call.
  // Each started clip gets a token, and a clip can finish only once (ended, error or rejected play).
  const finishedToken = useRef(-1);
  const finishAudio = useCallback(() => {
    if (finishedToken.current === audioToken.current) return;
    finishedToken.current = audioToken.current;
    dispatch({ type: 'audio_done' });
  }, []);

  const currentAudio = state.audio[0];
  const queued = state.audio.length;
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    if (!currentAudio) {
      el.pause();
      return;
    }
    audioToken.current += 1;
    const token = audioToken.current;
    el.src = currentAudio;
    el.play().catch(() => {
      if (token === audioToken.current) finishAudio();
    });
  }, [currentAudio, queued, finishAudio]);

  return {
    state,
    start,
    press,
    hangup: () => dispatch({ type: 'hangup' }),
    reset: () => dispatch({ type: 'reset' }),
    flashKey,
    audioProps: { ref: audioRef, onEnded: finishAudio, onError: finishAudio },
  };
}
