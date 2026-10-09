/** One complaint in plain words, and the form to raise one from the Panchayat office. */

import { useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import { TICKET_REASONS, type PolicyDenied, type TicketReason } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { defineMessages, msgFn } from '../lib/text';
import { areaOf, reporterAreaText } from '../lib/households';
import { REASON } from '../lib/labels';
import { shortMasked } from '../lib/phones';
import { COMPLAINT_WORD, complaintNo, familyStatus, howLong, isClosed, reporterCount, timelineLines, whenText } from '../lib/summary';
import { useVillage, villageName } from '../shell';
import { Button, Card, ErrorBox, Field, Loading, Note, PageTitle, useErrorText } from '../ui';

const m = defineMessages({
  area: 'Area',
  back: '← All complaints',
  title: msgFn<{ no: string }>(({ no }) => `Complaint ${no}`),
  problem: 'Problem',
  place: 'Place',
  wholeVillage: 'Whole village',
  reported: 'Reported by',
  families: msgFn<{ n: number }>(({ n }) => (n === 1 ? '1 family' : `${n} families`)),
  status: 'Status',
  open: msgFn<{ d: string }>(({ d }) => `Open for ${d}`),
  what: 'What happened',
  fixed: "Pump operator says it's fixed",
  close: 'Close complaint',
  closeNote: 'Closing works only after families confirm on the phone that water is back.',
  fixedNote: 'JalSakshi will then call the families who complained and ask if water is back.',
  noOperator: 'Add the pump operator in More → Team first.',
  closedOk: 'Complaint closed. Families confirmed water is back.',
  notYet: 'Not closed yet:',
  source: "From families' phone answers and the pump operator's calls",
  raiseTitle: 'Raise a complaint',
  raiseIntro: 'For a family who came to the Panchayat office. The pump operator gets a call.',
  family: 'Family',
  choose: 'Choose a family',
  submit: 'Raise complaint',
  noFamilies: 'No families yet. Add families first.',
});

function DeniedText({ denied }: { denied: PolicyDenied }) {
  return <>{denied.reason_en}</>;
}

export function ComplaintDetailPage() {
  const api = useApi();
  const errorText = useErrorText();
  const { tid = '' } = useParams();
  const { vid, detail } = useVillage();
  const ticket = useAsync(() => api.getTicket(tid), `ticket:${tid}`);
  const [busy, setBusy] = useState<'fixed' | 'close' | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; node: ReactNode } | null>(null);
  const base = `/villages/${encodeURIComponent(vid)}`;
  const now = new Date();

  if (ticket.error && !ticket.data) return <div className="page"><ErrorBox error={ticket.error} onRetry={ticket.reload} /></div>;
  if (!ticket.data) return <Loading />;
  const c = ticket.data;
  const point = detail.water_points?.find((p) => p.id === c.water_point_id);
  const operator = detail.operators.find((o) => o.role === 'NAL_JAL_MITRA');
  const closed = isClosed(c);
  const canFix = ['OPEN', 'ASSIGNED', 'REOPENED', 'ESCALATED'].includes(c.state);

  async function markFixed() {
    if (!operator) return;
    setBusy('fixed');
    setMessage(null);
    try {
      ticket.setData(await api.operatorFixed(c.id, operator.id));
    } catch (err) {
      setMessage({ ok: false, node: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  async function close() {
    setBusy('close');
    setMessage(null);
    try {
      const result = await api.closeTicket(c.id);
      if (result.ok) {
        ticket.setData(result.ticket);
        setMessage({ ok: true, node: m.closedOk });
      } else {
        setMessage({ ok: false, node: <><b>{m.notYet}</b> <DeniedText denied={result.denied} /></> });
        ticket.reload();
      }
    } catch (err) {
      setMessage({ ok: false, node: errorText(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page">
      <Link className="back" to={`${base}/complaints`}>{m.back}</Link>
      <PageTitle title={m.title({ no: complaintNo(c) })} />
      <Card>
        <ul className="rows">
          <li className="row"><span className="muted">{m.problem}</span><b>{REASON[c.reason].en}</b></li>
          <li className="row">
            <span className="muted">{m.place}</span>
            <span>{point ? (point.name) : m.wholeVillage}</span>
          </li>
          <li className="row">
            <span className="muted">{m.area}</span>
            <span>{reporterAreaText(c.reporters, detail.households)}</span>
          </li>
          <li className="row"><span className="muted">{m.reported}</span><span>{m.families({ n: reporterCount(c) })}</span></li>
          <li className="row">
            <span className="muted">{m.status}</span>
            <span className={`word ${closed ? 'word-good' : 'word-warn'}`}>{COMPLAINT_WORD[c.state].en}</span>
          </li>
        </ul>
        {!closed && <p className="muted">{m.open({ d: howLong(c.opened_at, now).en })}</p>}
      </Card>

      <Card title={m.what}>
        <ol className="timeline">
          {timelineLines(c).map((line, i) => (
            <li key={i}>
              <time dateTime={line.at}>{whenText(line.at, now).en}</time>
              {line.text.en}
            </li>
          ))}
        </ol>
        <Note>{m.source}</Note>
      </Card>

      {!closed && (
        <Card>
          <div className="actions">
            {canFix && (
              <Button variant="primary" busy={busy === 'fixed'} disabled={!operator} onClick={() => void markFixed()}>
                {m.fixed}
              </Button>
            )}
            <Button busy={busy === 'close'} onClick={() => void close()}>
              {m.close}
            </Button>
          </div>
          {canFix && <Note>{operator ? m.fixedNote : m.noOperator}</Note>}
          <Note>{m.closeNote}</Note>
          {message && <p className={message.ok ? 'ok-box' : 'warn-box'} role="status">{message.node}</p>}
        </Card>
      )}
      {closed && message && <p className="ok-box" role="status">{message.node}</p>}
    </div>
  );
}

export function RaiseComplaintPage() {
  const api = useApi();
  const errorText = useErrorText();
  const navigate = useNavigate();
  const { vid, detail } = useVillage();
  const [household, setHousehold] = useState('');
  const [reason, setReason] = useState<TicketReason>('NO_SUPPLY');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/villages/${encodeURIComponent(vid)}`;
  const families = detail.households.filter((h) => h.active && familyStatus(h) !== 'SAID_NO');

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!household) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.raiseTicket(vid, { household_id: household, reason });
      navigate(`${base}/complaints/${encodeURIComponent(created.id)}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <Link className="back" to={`${base}/complaints`}>{m.back}</Link>
      <PageTitle title={m.raiseTitle} />
      <p className="muted">{m.raiseIntro}</p>
      {families.length === 0 ? (
        <p className="warn-box">{m.noFamilies}</p>
      ) : (
        <form className="form card" onSubmit={(e) => void submit(e)}>
          <Field label={m.family}>
            {(id) => (
              <select id={id} value={household} onChange={(e) => setHousehold(e.target.value)} required>
                <option value="">{m.choose}</option>
                {families.map((h) => (
                  <option key={h.id} value={h.id}>
                    {[h.display_name, shortMasked(h.phone_masked), areaOf(h)].filter(Boolean).join(' · ')}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={m.problem}>
            {(id) => (
              <select id={id} value={reason} onChange={(e) => setReason(e.target.value as TicketReason)}>
                {TICKET_REASONS.map((r) => (
                  <option key={r} value={r}>{REASON[r].en}</option>
                ))}
              </select>
            )}
          </Field>
          {error && <p className="warn-box" role="alert">{error}</p>}
          <div className="actions">
            <Button type="submit" variant="primary" busy={busy} disabled={!household}>
              {m.submit}
            </Button>
          </div>
          <Note>{villageName(detail.village)}</Note>
        </form>
      )}
    </div>
  );
}
