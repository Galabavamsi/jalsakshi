/** Complaints: Open | Closed, simple rows. */

import { Link, useSearchParams } from 'react-router-dom';
import { useApi } from '../api/context';
import { useAsync } from '../hooks/useAsync';
import { defineMessages, msgFn } from '../lib/text';
import { REASON } from '../lib/labels';
import { COMPLAINT_WORD, complaintNo, howLong, isClosed, whenText } from '../lib/summary';
import { reporterAreaText } from '../lib/households';
import { useVillage } from '../shell';
import { ButtonLink, Card, ErrorBox, Loading, Note, PageTitle } from '../ui';

const m = defineMessages({
  title: 'Complaints',
  open: 'Open',
  closed: 'Closed',
  raise: 'Raise a complaint',
  noneOpen: 'No open complaints. When families say there was no water, a complaint opens here by itself.',
  noneClosed: 'No closed complaints yet.',
  openFor: msgFn<{ d: string }>(({ d }) => `open ${d}`),
  closedAt: msgFn<{ d: string }>(({ d }) => `closed ${d}`),
  note: 'A complaint closes only after families confirm on the phone that water is back.',
});

export function ComplaintsPage() {
  const api = useApi();
  const { vid, detail } = useVillage();
  const [params] = useSearchParams();
  const showClosed = params.get('show') === 'closed';
  const tickets = useAsync(() => api.listTickets({ village_id: vid }), `tickets:${vid}`);
  const base = `/villages/${encodeURIComponent(vid)}`;
  const now = new Date();

  const rows = (tickets.data ?? [])
    .filter((x) => isClosed(x) === showClosed)
    .sort((a, b) => (showClosed ? b.updated_at.localeCompare(a.updated_at) : a.opened_at.localeCompare(b.opened_at)));

  return (
    <div className="page">
      <PageTitle title={m.title}>
        <ButtonLink to={`${base}/complaints/new`} variant="primary">
          {m.raise}
        </ButtonLink>
      </PageTitle>
      <div className="seg" role="group">
        <Link to={`${base}/complaints`} className={showClosed ? '' : 'active'} aria-current={!showClosed || undefined}>
          {m.open}
        </Link>
        <Link to={`${base}/complaints?show=closed`} className={showClosed ? 'active' : ''} aria-current={showClosed || undefined}>
          {m.closed}
        </Link>
      </div>
      {tickets.error && !tickets.data ? (
        <ErrorBox error={tickets.error} onRetry={tickets.reload} />
      ) : !tickets.data ? (
        <Loading />
      ) : (
        <Card>
          {rows.length === 0 ? (
            <p className="muted">{showClosed ? m.noneClosed : m.noneOpen}</p>
          ) : (
            <ul className="rows">
              {rows.map((c) => {
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
                          {showClosed
                            ? m.closedAt({ d: whenText(c.updated_at, now).en })
                            : m.openFor({ d: howLong(c.opened_at, now).en })}
                        </span>
                      </span>
                      <span className="row-end">{COMPLAINT_WORD[c.state].en}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
          <Note>{m.note}</Note>
        </Card>
      )}
    </div>
  );
}
