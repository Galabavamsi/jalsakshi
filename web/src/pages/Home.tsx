/** Home: today's water, complaints, what to do now, and one button to call families. */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import { useAsync } from '../hooks/useAsync';
import { defineMessages, msgFn } from '../lib/text';
import { reporterAreaText } from '../lib/households';
import { REASON } from '../lib/labels';
import { MISSED_CALL } from '../lib/phones';
import {
  COMPLAINT_WORD,
  WATER_WORD,
  callTimeText,
  clockText,
  complaintCounts,
  complaintNo,
  familyCounts,
  howLong,
  isDayOne,
  openComplaints,
  todos,
  waterLines,
} from '../lib/summary';
import { addDays, istDate } from '../lib/time';
import { useVillage } from '../shell';
import { Button, ButtonLink, Card, ConfirmDialog, ErrorBox, Loading, Note, PageTitle, useErrorText } from '../ui';

const m = defineMessages({
  title: 'Home',
  water: "Today's water",
  village: 'Whole village',
  answered: msgFn<{ n: number; total: number }>(({ n, total }) => `${n} of ${total} families answered`),
  waterNote: msgFn<{ at: string }>(({ at }) => `From families' phone answers · updated ${at}`),
  waterNoteNone: "From families' phone answers · no answers yet today",
  complaints: 'Complaints',
  open: 'Open',
  fixing: 'Being fixed',
  closed: 'Closed this week',
  noOpen: 'No open complaints.',
  seeAll: 'See all',
  openFor: msgFn<{ d: string }>(({ d }) => `open ${d}`),
  complaintsNote: "From families' answers and the pump operator's calls",
  todo: 'What to do now',
  nothing: 'Nothing to do right now. JalSakshi keeps calling families every evening.',
  start: 'Getting started',
  startLine: msgFn<{
    agreed: number;
    total: number;
    time: string;
    num: string;
  }>(({ agreed, total, time, num }) =>
      `${agreed} of ${total} families agreed · first daily call tonight at ${time} · families can also give a missed call to ${num}.`),
  startEmpty: msgFn<{ num: string }>(({ num }) =>
      `No families added yet. Paste their mobile numbers, or put up the missed-call poster: families give a missed call to ${num} and join themselves.`),
  addFamilies: 'Add families',
  callNow: 'Call families now',
  callTitle: 'Call families now?',
  callBody: 'JalSakshi will call every family that agreed, now.',
  callHours: 'Each family gets one short call. Families who already answered today are not called again.',
  callYes: 'Call now',
  cancel: 'Cancel',
  callStarted: 'Calls started. Answers appear here as families press keys.',
});

export function HomePage() {
  const api = useApi();
  const errorText = useErrorText();
  const { vid, detail } = useVillage();
  const now = new Date();
  const today = istDate(now);
  const days = useAsync(() => api.getDays(vid, addDays(today, -6), today), `days:${vid}:${today}`);
  const tickets = useAsync(() => api.listTickets({ village_id: vid }), `tickets:${vid}`);
  const [asking, setAsking] = useState(false);
  const [calling, setCalling] = useState(false);
  const [callResult, setCallResult] = useState<{
    ok: boolean;
    text: string;
  } | null>(null);

  if (days.error && !days.data) return <ErrorBox error={days.error} onRetry={days.reload} />;
  if (tickets.error && !tickets.data) return <ErrorBox error={tickets.error} onRetry={tickets.reload} />;
  if (!days.data || !tickets.data) return <Loading />;

  const base = `/villages/${encodeURIComponent(vid)}`;
  const todayStatus = days.data.find((d) => d.date === today) ?? null;
  const fam = familyCounts(detail.households);
  const lines = waterLines(todayStatus, detail.water_points ?? []);
  const counts = complaintCounts(tickets.data, now);
  const open = openComplaints(tickets.data).slice(0, 5);
  const dayOne = isDayOne(days.data);
  // On day one the Getting started card already offers [Add families]; don't repeat it below.
  const list = todos({
    vid,
    households: detail.households,
    operators: detail.operators,
    tickets: tickets.data,
    now,
  }).filter((td) => !(dayOne && td.action.kind === 'link' && td.action.to.endsWith('/families?add=1')));

  async function callNow() {
    setCalling(true);
    try {
      await api.runCheckin(vid);
      setCallResult({ ok: true, text: m.callStarted });
    } catch (err) {
      setCallResult({ ok: false, text: errorText(err) });
    } finally {
      setCalling(false);
      setAsking(false);
    }
  }

  return (
    <div className="page">
      <PageTitle title={m.title} />

      {dayOne && (
        <Card
          title={m.start}
          footer={
            <ButtonLink to={`${base}/families?add=1`} variant="primary">
              {m.addFamilies}
            </ButtonLink>
          }
        >
          <p>
            {fam.total === 0
              ? m.startEmpty({ num: MISSED_CALL })
              : m.startLine({
                  agreed: fam.agreed,
                  total: fam.total,
                  time: callTimeText(detail.village.checkin_local_time).en,
                  num: MISSED_CALL,
                })}
          </p>
        </Card>
      )}

      {!(dayOne && fam.agreed === 0) && (
        <Card title={m.water}>
          <ul className="rows">
            {lines.map((line, i) => (
              <li key={i} className="row">
                <span>{line.name ? line.name.en : m.village}</span>
                <span className={`word word-${line.status}`}>{WATER_WORD[line.status].en}</span>
              </li>
            ))}
          </ul>
          <p className="muted">
            {m.answered({
              n: todayStatus?.counts.answered ?? 0,
              total: fam.agreed,
            })}
          </p>
          <Note>{todayStatus ? m.waterNote({ at: clockText(todayStatus.computed_at) }) : m.waterNoteNone}</Note>
        </Card>
      )}

      <Card title={m.complaints} footer={<Link to={`${base}/complaints`}>{m.seeAll}</Link>}>
        <div className="stats">
          <div className="stat">
            <b>{counts.open}</b>
            <span>{m.open}</span>
          </div>
          <div className="stat">
            <b>{counts.fixing}</b>
            <span>{m.fixing}</span>
          </div>
          <div className="stat">
            <b>{counts.closedThisWeek}</b>
            <span>{m.closed}</span>
          </div>
        </div>
        {open.length === 0 ? (
          <p className="muted">{m.noOpen}</p>
        ) : (
          <ul className="rows">
            {open.map((c) => {
              const point = detail.water_points?.find((p) => p.id === c.water_point_id);
              return (
                <li key={c.id}>
                  <Link className="row" to={`${base}/complaints/${encodeURIComponent(c.id)}`}>
                    <span className="row-main">
                      <span>
                        {complaintNo(c)} {REASON[c.reason].en}
                      </span>
                      <span className="row-sub">
                        {reporterAreaText(c.reporters, detail.households)} · {point ? `${point.name} · ` : ''}
                        {m.openFor({ d: howLong(c.opened_at, now).en })}
                      </span>
                    </span>
                    <span className="row-end">{COMPLAINT_WORD[c.state].en}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        <Note>{m.complaintsNote}</Note>
      </Card>

      <Card title={m.todo}>
        {list.length === 0 ? (
          <p className="muted">{m.nothing}</p>
        ) : (
          <div>
            {list.map((item, i) => (
              <div className="todo" key={i}>
                <p>{item.text.en}</p>
                {item.action.kind === 'link' ? (
                  <ButtonLink to={item.action.to}>{item.button.en}</ButtonLink>
                ) : (
                  <Button onClick={() => setAsking(true)}>{item.button.en}</Button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Button variant="primary" className="btn-wide" onClick={() => setAsking(true)}>
        {m.callNow}
      </Button>
      {callResult && (
        <p className={callResult.ok ? 'ok-box' : 'warn-box'} role="status">
          {callResult.text}
        </p>
      )}

      {asking && (
        <ConfirmDialog
          title={m.callTitle}
          confirm={m.callYes}
          cancel={m.cancel}
          busy={calling}
          onConfirm={() => void callNow()}
          onCancel={() => setAsking(false)}
        >
          <p>{m.callBody}</p>
          <p>{m.callHours}</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
