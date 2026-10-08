import { describe, expect, it } from 'vitest';
import { PROMPTS, startIvr, stepIvr, type IvrSession } from '../src/api/mockIvr';
import type { Action } from '../src/api/types';

const keys = (actions: Action[]) =>
  actions.map((a) =>
    a.type === 'play' ? a.prompt_key : a.type === 'get_digits' ? `ask:${a.prompts[0]?.prompt_key}` : a.type,
  );

function run(session: IvrSession, inputs: Array<string | null>) {
  let s = session;
  const trail: string[][] = [];
  let done = false;
  for (const input of inputs) {
    const turn = stepIvr(s, input === null ? { timeout: true } : { digits: input });
    s = turn.session;
    trail.push(keys(turn.actions));
    done = turn.done;
  }
  return { session: s, trail, done };
}

describe('mock IVR (mirrors voice/flow.py)', () => {
  it('asks hours and cleanliness only when water came', () => {
    const start = startIvr('DAILY');
    expect(keys(start.actions)).toEqual(['household.greet', 'ask:household.q_water']);
    const { session, trail, done } = run(start.session, ['1', '3', '2', '#']);
    expect(trail).toEqual([
      ['ask:household.q_hours'],
      ['ask:household.q_clean'],
      ['household.q_note', 'record'],
      ['household.bye', 'hangup'],
    ]);
    expect(done).toBe(true);
    expect(session.answers).toEqual({ water: 'YES', hours: 3, clean: 'NO', fixed: null });
  });

  it('skips hours and cleanliness when there was no water', () => {
    const { session, trail } = run(startIvr('DAILY').session, ['2', null]);
    expect(trail[0]).toEqual(['household.q_note', 'record']);
    expect(session.answers.water).toBe('NO');
    expect(session.answers.hours).toBeNull();
  });

  it('re-prompts once on bad input, then stores null instead of guessing', () => {
    const { session, trail } = run(startIvr('DAILY').session, ['7', null]);
    expect(trail[0]).toEqual(['household.invalid', 'ask:household.q_water']);
    expect(trail[1]).toEqual(['household.q_note', 'record']);
    expect(session.answers.water).toBeNull();
  });

  it('runs the verification call', () => {
    const start = startIvr('VERIFY');
    expect(keys(start.actions)).toEqual(['verify.greet', 'ask:verify.q_water']);
    const { session, done } = run(start.session, ['1']);
    expect(done).toBe(true);
    expect(session.answers.water).toBe('YES');
  });

  it('reads the operator summary with the household count', () => {
    const start = startIvr('OPERATOR', { reason: 'NO_SUPPLY', households: 3 });
    const summary = start.actions[1];
    expect(summary?.type === 'play' && summary.text_hi).toBe(
      PROMPTS['operator.summary_no_supply'].replace('{households}', '3'),
    );
    const fixed = run(start.session, ['1']);
    expect(fixed.trail[0]).toEqual(['operator.ack_fixed', 'hangup']);
    expect(fixed.session.answers.fixed).toBe(true);
    const pending = run(startIvr('OPERATOR').session, ['2']);
    expect(pending.trail[0]).toEqual(['operator.ack_pending', 'hangup']);
  });
});
