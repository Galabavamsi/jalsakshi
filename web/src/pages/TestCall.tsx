/** Admin only: try the phone call in the browser, as a family would hear it. */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import type { Action } from '../api/types';
import { defineMessages } from '../lib/text';
import { shortMasked } from '../lib/phones';
import { familyStatus } from '../lib/summary';
import { useMe, useVillage } from '../shell';
import { Button, Card, Field, PageTitle, useErrorText } from '../ui';

const m = defineMessages({
  back: '← More',
  title: 'Test call',
  intro: 'Play the daily call here in the browser as one family. Answers you press are saved like a real call, marked as a test.',
  family: 'Family',
  start: 'Start call',
  noFamilies: 'No family has agreed yet, so there is nobody to call.',
  press: 'Press a key',
  silent: 'Stay silent',
  done: 'Call finished. The answer is saved.',
  again: 'Call again',
  adminOnly: 'Only admins can use test calls.',
});

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '#'];

function lines(actions: Action[]): string[] {
  const out: string[] = [];
  for (const a of actions) {
    if (a.type === 'play') out.push(a.text_hi);
    if (a.type === 'get_digits') out.push(...a.prompts.map((p) => p.text_hi));
  }
  return out;
}

export function TestCallPage() {
  const api = useApi();
  const errorText = useErrorText();
  const { me } = useMe();
  const { vid, detail } = useVillage();
  const families = detail.households.filter((h) => h.active && familyStatus(h) === 'AGREED');
  const [household, setHousehold] = useState(families[0]?.id ?? '');
  const [callId, setCallId] = useState<string | null>(null);
  const [heard, setHeard] = useState<string[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [finished, setFinished] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!me.is_admin) return <p className="page muted">{m.adminOnly}</p>;

  function show(actions: Action[]) {
    setHeard((h) => [...h, ...lines(actions)]);
    setWaiting(actions.some((a) => a.type === 'get_digits' || a.type === 'record'));
  }

  async function start() {
    setBusy(true);
    setError(null);
    setHeard([]);
    setFinished(false);
    try {
      const res = await api.simStartCall({ household_id: household, purpose: 'DAILY' });
      setCallId(res.call_id);
      show(res.actions);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function press(input: { digits?: string; timeout?: boolean }) {
    if (!callId) return;
    setBusy(true);
    setHeard((h) => [...h, `→ ${input.digits ?? '…'}`]);
    try {
      const res = await api.simInput(callId, input);
      show(res.actions);
      if (res.done) {
        setFinished(true);
        setCallId(null);
        setWaiting(false);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Link className="back" to={`/villages/${encodeURIComponent(vid)}/more`}>{m.back}</Link>
      <PageTitle title={m.title} />
      <p className="muted">{m.intro}</p>
      {families.length === 0 ? (
        <p className="warn-box">{m.noFamilies}</p>
      ) : (
        <Card>
          {!callId && (
            <div className="form">
              <Field label={m.family}>
                {(id) => (
                  <select id={id} value={household} onChange={(e) => setHousehold(e.target.value)}>
                    {families.map((h) => (
                      <option key={h.id} value={h.id}>
                        {[h.display_name, shortMasked(h.phone_masked)].filter(Boolean).join(' · ')}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <div className="actions">
                <Button variant="primary" busy={busy} onClick={() => void start()}>
                  {finished ? m.again : m.start}
                </Button>
              </div>
            </div>
          )}
          {heard.length > 0 && (
            <ol className="timeline" lang="hi">
              {heard.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ol>
          )}
          {callId && waiting && (
            <div>
              <p className="note">{m.press}</p>
              <div className="actions">
                {KEYS.map((k) => (
                  <Button key={k} disabled={busy} onClick={() => void press({ digits: k })}>
                    {k}
                  </Button>
                ))}
                <Button variant="link" disabled={busy} onClick={() => void press({ timeout: true })}>
                  {m.silent}
                </Button>
              </div>
            </div>
          )}
          {finished && <p className="ok-box">{m.done}</p>}
          {error && <p className="warn-box">{error}</p>}
        </Card>
      )}
    </div>
  );
}
