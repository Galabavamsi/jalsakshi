import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import type { PolicyDenied, Ticket, TicketState, VillageDetail } from '../api/types';
import { Bi } from '../components/Bi';
import { IconBack, IconCheck, IconWrench } from '../components/Icons';
import { ErrorNote, Loading } from '../components/PageState';
import { PolicyDenial } from '../components/PolicyDenial';
import { Timeline } from '../components/Timeline';
import { TicketProgress, TicketStateBadge, VerifiedStamp } from '../components/TicketParts';
import { useAsync } from '../hooks/useAsync';
import type { People } from '../lib/events';
import { dateTime, relative } from '../lib/format';
import { REASON, ROLE } from '../lib/labels';
import styles from './TicketPage.module.css';

const FIXABLE: TicketState[] = ['OPEN', 'ASSIGNED', 'REOPENED', 'ESCALATED'];

function peopleOf(detail: VillageDetail | undefined): People {
  const people: People = {};
  for (const h of detail?.households ?? []) {
    const name = h.display_name || h.id;
    people[h.id] = { hi: `घर: ${name}`, en: `household ${h.phone_masked}` };
  }
  for (const o of detail?.operators ?? []) {
    const name = o.display_name || o.id;
    people[o.id] = { hi: `${name}, ${ROLE[o.role].hi}`, en: ROLE[o.role].en };
  }
  return people;
}

type Busy = 'fixed' | 'close' | null;

function Actions({ ticket, detail, onTicket, onDenied }: {
  ticket: Ticket;
  detail: VillageDetail | undefined;
  onTicket: (t: Ticket) => void;
  onDenied: (d: PolicyDenied) => void;
}) {
  const api = useApi();
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<unknown>(null);
  const operator = detail?.operators.find((o) => o.role === 'NAL_JAL_MITRA');
  const canReportFixed = FIXABLE.includes(ticket.state) && Boolean(operator);

  async function act(kind: Exclude<Busy, null>, work: () => Promise<void>) {
    setBusy(kind);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  const reportFixed = () =>
    act('fixed', async () => {
      if (operator) onTicket(await api.operatorFixed(ticket.id, operator.id));
    });

  const close = () =>
    act('close', async () => {
      const result = await api.closeTicket(ticket.id);
      if (result.ok) onTicket(result.ticket);
      else {
        onDenied(result.denied);
        onTicket(await api.getTicket(ticket.id));
      }
    });

  return (
    <div className={styles.actions}>
      <div className={styles.buttons}>
        {FIXABLE.includes(ticket.state) && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={reportFixed}
            disabled={!canReportFixed || busy !== null}
          >
            <IconWrench />
            <Bi
              hi={busy === 'fixed' ? 'दर्ज हो रहा है' : 'नल जल मित्र ने ठीक बताया'}
              en={busy === 'fixed' ? 'Saving' : 'Operator reports fixed'}
            />
          </button>
        )}
        <button type="button" className="btn btn-stamp" onClick={close} disabled={busy !== null}>
          <IconCheck />
          <Bi
            hi={busy === 'close' ? 'जाँच हो रही है' : 'शिकायत बंद करें'}
            en={busy === 'close' ? 'Checking' : 'Close ticket'}
          />
        </button>
      </div>
      <Bi
        hi="शिकायत तभी बंद होगी जब घर फ़ोन पर पानी आने की पुष्टि करें।"
        en="A ticket closes only after households confirm by phone that water is back."
        className={styles.rule}
      />
      {error ? <ErrorNote error={error} /> : null}
    </div>
  );
}

/** One repair ticket: progress, the Cedar-guarded close, and its full history. */
export function TicketPage() {
  const { tid = '' } = useParams();
  const api = useApi();
  const ticket = useAsync(() => api.getTicket(tid), `ticket:${tid}`);
  const vid = ticket.data?.village_id ?? '';
  const village = useAsync(
    () => (vid ? api.getVillage(vid) : Promise.resolve(undefined)),
    `village:${vid}`,
  );
  const [denied, setDenied] = useState<PolicyDenied | null>(null);
  const people = useMemo(() => peopleOf(village.data), [village.data]);

  if (!ticket.data) {
    return (
      <div className="page">
        {ticket.loading ? <Loading /> : <ErrorNote error={ticket.error} onRetry={ticket.reload} />}
      </div>
    );
  }

  const t = ticket.data;
  const name = village.data?.village.name ?? t.village_id;
  const opened = dateTime(t.opened_at);
  const updated = relative(t.updated_at);
  const closedAt = [...t.events].reverse().find((e) => e.to_state === 'CLOSED_VERIFIED')?.at;
  const updateTicket = (next: Ticket) => {
    ticket.setData(next);
    if (next.state === 'CLOSED_VERIFIED') setDenied(null);
  };

  return (
    <div className="page">
      <Link to={`/villages/${encodeURIComponent(t.village_id)}`} className="backlink">
        <IconBack />
        <Bi inline hi={name} en="Village record" />
      </Link>
      <header className={styles.header}>
        <div className={styles.titleBlock}>
          <p className={styles.kicker}>
            <span lang="hi">शिकायत</span> <span lang="en">(ticket)</span> {t.id}
          </p>
          <h1 className={styles.title}>
            <span lang="hi">
              {name}: {REASON[t.reason].hi}
            </span>
            <span lang="en" className={styles.titleEn}>
              {REASON[t.reason].en} in {name}
            </span>
          </h1>
          <div className={styles.meta}>
            <TicketStateBadge state={t.state} />
            <span>
              <span lang="hi">{opened.hi} को खुली, {updated.hi} बदली</span>{' '}
              <span lang="en">(opened {opened.en}, updated {updated.en})</span>
            </span>
          </div>
        </div>
        {closedAt && (
          <div className={styles.stampWrap}>
            <VerifiedStamp at={closedAt} />
          </div>
        )}
      </header>

      <section className={styles.section} aria-label="Repair progress">
        <TicketProgress state={t.state} />
      </section>

      {t.state !== 'CLOSED_VERIFIED' && (
        <section className={styles.section} aria-label="Actions">
          <Actions ticket={t} detail={village.data} onTicket={updateTicket} onDenied={setDenied} />
          {denied && <PolicyDenial denied={denied} onDismiss={() => setDenied(null)} />}
        </section>
      )}

      <section className={styles.section} aria-labelledby="history-title">
        <Bi
          as="h2"
          id="history-title"
          hi="क्या हुआ, कब और किसने"
          en="What happened, when, and who did it"
          className="section-title"
        />
        <Timeline events={t.events} people={people} />
      </section>
    </div>
  );
}
