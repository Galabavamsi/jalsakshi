/** Announcements: write → sarpanch approves → send to families (at most 2 a week). */

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import { BROADCAST_KINDS, type ActionResult, type Broadcast, type BroadcastKind } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { defineMessages, msgFn } from '../lib/text';
import { BROADCAST_KIND } from '../lib/labels';
import { whenText } from '../lib/summary';
import { useMe, useVillage } from '../shell';
import { Button, Card, ErrorBox, Field, Loading, PageTitle, useErrorText } from '../ui';

const m = defineMessages({
  back: '← More',
  title: 'Announcements',
  how: 'Write a short message in Hindi. The sarpanch approves it, then JalSakshi calls every family that agreed and reads it out.',
  week: msgFn<{ n: number; max: number }>(({ n, max }) => `Sent this week: ${n} of ${max}`),
  write: 'Write an announcement',
  kind: 'About',
  text: 'Message (Hindi)',
  draft: 'Save for the sarpanch',
  none: 'No announcements yet.',
  approve: 'Approve',
  send: 'Send to families',
  cancel: 'Cancel',
  DRAFT: 'Waiting for the sarpanch',
  APPROVED: 'Approved, not sent yet',
  SENT: 'Sent',
  CANCELLED: 'Cancelled',
  heard: msgFn<{ heard: number; total: number }>(({ heard, total }) => `${heard} of ${total} families heard it`),
});

export function AnnouncementsPage() {
  const api = useApi();
  const errorText = useErrorText();
  const { me } = useMe();
  const { vid } = useVillage();
  const list = useAsync(() => api.listBroadcasts(vid), `broadcasts:${vid}`);
  const [kind, setKind] = useState<BroadcastKind>('SUPPLY_CHANGE');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const now = new Date();

  async function act(id: string, fn: () => Promise<ActionResult<unknown> | Broadcast>) {
    setBusy(id);
    setMsg(null);
    try {
      const res = await fn();
      if ('ok' in res && !res.ok) setMsg(res.denied.reason_en);
      list.reload();
    } catch (err) {
      setMsg(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    await act('new', () => api.draftBroadcast(vid, { kind, text_hi: text.trim() }));
    setText('');
  }

  return (
    <div className="page">
      <Link className="back" to={`/villages/${encodeURIComponent(vid)}/more`}>{m.back}</Link>
      <PageTitle title={m.title} />
      <p className="muted">{m.how}</p>
      {msg && <p className="warn-box" role="alert">{msg}</p>}
      {list.error && !list.data ? (
        <ErrorBox error={list.error} onRetry={list.reload} />
      ) : !list.data ? (
        <Loading />
      ) : (
        <>
          <p className="big">{m.week({ n: list.data.sent_last_7_days, max: list.data.weekly_limit })}</p>
          <Card>
            {list.data.broadcasts.length === 0 ? (
              <p className="muted">{m.none}</p>
            ) : (
              <ul className="rows">
                {[...list.data.broadcasts].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((b) => (
                  <li key={b.id} style={{ padding: '12px 0' }}>
                    <div className="row-main">
                      <span className="row-sub">
                        {BROADCAST_KIND[b.kind].en} · {whenText(b.sent_at ?? b.created_at, now).en} · <b>{m[b.state]}</b>
                      </span>
                      <span lang="hi">{b.text_hi}</span>
                      {b.state === 'SENT' && <span className="row-sub">{m.heard({ heard: b.heard, total: b.recipients })}</span>}
                    </div>
                    {(b.state === 'DRAFT' || b.state === 'APPROVED') && (
                      <div className="actions" style={{ marginTop: 8 }}>
                        {b.state === 'DRAFT' && me.can_approve_announcements && (
                          <Button variant="primary" busy={busy === b.id} onClick={() => void act(b.id, () => api.approveBroadcast(vid, b.id))}>
                            {m.approve}
                          </Button>
                        )}
                        {b.state === 'APPROVED' && (
                          <Button variant="primary" busy={busy === b.id} onClick={() => void act(b.id, () => api.sendBroadcast(vid, b.id))}>
                            {m.send}
                          </Button>
                        )}
                        <Button onClick={() => void act(b.id, () => api.cancelBroadcast(vid, b.id))}>{m.cancel}</Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
      <Card title={m.write}>
        <form className="form" onSubmit={(e) => void submit(e)}>
          <Field label={m.kind}>
            {(id) => (
              <select id={id} value={kind} onChange={(e) => setKind(e.target.value as BroadcastKind)}>
                {BROADCAST_KINDS.map((k) => (
                  <option key={k} value={k}>{BROADCAST_KIND[k].en}</option>
                ))}
              </select>
            )}
          </Field>
          <Field label={m.text}>
            {(id) => <textarea id={id} lang="hi" value={text} maxLength={300} style={{ fontFamily: 'inherit', minHeight: 100 }} onChange={(e) => setText(e.target.value)} />}
          </Field>
          <div className="actions">
            <Button type="submit" variant="primary" busy={busy === 'new'} disabled={!text.trim()}>{m.draft}</Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
