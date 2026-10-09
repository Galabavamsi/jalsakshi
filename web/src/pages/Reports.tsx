/** Reports: the weekly summary text and a printable Gram Sabha sheet (last 30 days). */

import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import type { DayStatus, Ticket } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { defineMessages, msgFn } from '../lib/text';
import { isSampleVillage } from '../lib/demo';
import { longDate, shortDate } from '../lib/format';
import { REASON } from '../lib/labels';
import { COMPLAINT_WORD, WATER_WORD, complaintNo, familyCounts, isClosed } from '../lib/summary';
import { addDays, istDate } from '../lib/time';
import { useVillage, villageName } from '../shell';
import { Button, ButtonLink, Card, ErrorBox, Loading, Note, PageTitle, SampleBanner } from '../ui';

const DAYS = 30;

const m = defineMessages({
  back: '← More',
  title: 'Reports',
  weekly: 'This week in short',
  weeklyNote: 'The sarpanch also gets this as a call every Monday.',
  month: 'Last 30 days',
  daysWater: msgFn<{ n: number; total: number }>(({ n, total }) => `Water came on ${n} of ${total} days with answers`),
  fixed: msgFn<{ n: number; open: number }>(({ n, open }) => `${n} complaints fixed and confirmed by families · ${open} still open`),
  print: 'Open the Gram Sabha sheet',
  source: "From families' phone answers",
  sheetTitle: 'Tap water record for the Gram Sabha',
  period: msgFn<{ from: string; to: string }>(({ from, to }) => `${from} to ${to}`),
  printNow: 'Print',
  backToReports: '← Back',
  families: msgFn<{ a: number; total: number }>(({ a, total }) => `Families answering calls: ${a} (of ${total} added)`),
  date: 'Date',
  water: 'Water',
  answered: 'Families answered',
  complaints: 'Complaints',
  problem: 'Problem',
  opened: 'Opened',
  status: 'Status',
  noComplaints: 'No complaints in this period.',
  method: 'Each day is decided from families’ keypad answers to the evening call. A complaint is closed only after families confirm water is back.',
  sign: 'Sarpanch: ____________________     Secretary: ____________________',
  sample: 'SAMPLE — example data',
});

function monthStats(days: DayStatus[], tickets: Ticket[], from: string) {
  const decided = days.filter((d) => d.status !== 'UNVERIFIED');
  const recent = tickets.filter((t) => istDate(new Date(t.opened_at)) >= from || !isClosed(t));
  return {
    water: decided.filter((d) => d.status === 'SUPPLIED').length,
    decided: decided.length,
    fixed: recent.filter(isClosed).length,
    open: recent.filter((t) => !isClosed(t)).length,
    recent,
  };
}

export function ReportsPage() {
  const api = useApi();
  const { vid } = useVillage();
  const today = istDate(new Date());
  const from = addDays(today, -(DAYS - 1));
  const summary = useAsync(() => api.getSummary(vid), `summary:${vid}`);
  const data = useAsync(
    () => Promise.all([api.getDays(vid, from, today), api.listTickets({ village_id: vid })]),
    `report:${vid}:${today}`,
  );
  const base = `/villages/${encodeURIComponent(vid)}`;
  const stats = data.data ? monthStats(data.data[0], data.data[1], from) : null;

  return (
    <div className="page">
      <Link className="back" to={`${base}/more`}>{m.back}</Link>
      <PageTitle title={m.title} />
      <Card title={m.weekly}>
        {summary.error && !summary.data ? (
          <ErrorBox error={summary.error} onRetry={summary.reload} />
        ) : !summary.data ? (
          <Loading />
        ) : (
          <pre className="summary">{summary.data.text_en}</pre>
        )}
        <Note>{m.weeklyNote}</Note>
      </Card>
      <Card title={m.month} footer={<ButtonLink to={`${base}/gram-sabha-sheet`} variant="primary">{m.print}</ButtonLink>}>
        {data.error && !data.data ? (
          <ErrorBox error={data.error} onRetry={data.reload} />
        ) : !stats ? (
          <Loading />
        ) : (
          <>
            <p className="big">{m.daysWater({ n: stats.water, total: stats.decided })}</p>
            <p>{m.fixed({ n: stats.fixed, open: stats.open })}</p>
          </>
        )}
        <Note>{m.source}</Note>
      </Card>
    </div>
  );
}

/** A plain printable page (no app chrome). */
export function GramSabhaSheet() {
  const api = useApi();
  const { vid = '' } = useParams();
  const today = istDate(new Date());
  const from = addDays(today, -(DAYS - 1));
  const data = useAsync(
    () => Promise.all([api.getVillage(vid), api.getDays(vid, from, today), api.listTickets({ village_id: vid })]),
    `sheet:${vid}:${today}`,
  );
  if (data.error && !data.data) return <div className="print-page"><ErrorBox error={data.error} onRetry={data.reload} /></div>;
  if (!data.data) return <Loading />;
  const [detail, days, tickets] = data.data;
  const stats = monthStats(days, tickets, from);
  const v = detail.village;
  const fam = familyCounts(detail.households);

  return (
    <div className="print-page">
      <div className="actions no-print">
        <Link className="btn" to={`/villages/${encodeURIComponent(vid)}/more/reports`}>{m.backToReports}</Link>
        <Button variant="primary" onClick={() => window.print()}>{m.printNow}</Button>
      </div>
      {isSampleVillage(vid) && <><SampleBanner /><p><b>{m.sample}</b></p></>}
      <h1>{m.sheetTitle}</h1>
      <p>
        <b>{villageName(v)}</b>
        {[v.gram_panchayat, v.block, v.district].filter((x) => x && x !== '-').map((x) => ` · ${x}`).join('')}
      </p>
      <p>{m.period({ from: longDate(from).en, to: longDate(today).en })}</p>
      <p className="big">{m.daysWater({ n: stats.water, total: stats.decided })}</p>
      <p>{m.fixed({ n: stats.fixed, open: stats.open })}</p>
      <p>{m.families({ a: fam.agreed, total: fam.total })}</p>

      <table>
        <thead>
          <tr><th>{m.date}</th><th>{m.water}</th><th>{m.answered}</th></tr>
        </thead>
        <tbody>
          {[...days].reverse().map((d) => (
            <tr key={d.date}>
              <td>{shortDate(d.date).en}</td>
              <td>{WATER_WORD[d.status].en}</td>
              <td>{d.counts.answered}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>{m.complaints}</h2>
      {stats.recent.length === 0 ? (
        <p>{m.noComplaints}</p>
      ) : (
        <table>
          <thead>
            <tr><th>#</th><th>{m.problem}</th><th>{m.opened}</th><th>{m.status}</th></tr>
          </thead>
          <tbody>
            {stats.recent.map((c) => (
              <tr key={c.id}>
                <td>{complaintNo(c)}</td>
                <td>{REASON[c.reason].en}</td>
                <td>{shortDate(istDate(new Date(c.opened_at))).en}</td>
                <td>{COMPLAINT_WORD[c.state].en}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Note>{m.method}</Note>
      <p style={{ marginTop: 48 }}>{m.sign}</p>
    </div>
  );
}
