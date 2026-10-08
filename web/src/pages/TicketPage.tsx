import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import type { PolicyDenied, Ticket, TicketState, VillageDetail } from '../api/types';
import { Bi } from '../components/Bi';
import { IconBack, IconCheck, IconWrench } from '../components/Icons';
import { ErrorNote, Loading } from '../components/PageState';
import { PolicyDenial } from '../components/PolicyDenial';
import { Timeline } from '../components/Timeline';
import {
  Confirmations,
  TicketProgress,
  TicketStateBadge,
  VerifiedStamp,
} from '../components/TicketParts';
import { VillageName } from '../components/VillageName';
import { Wash, type WashTone } from '../components/Wash';
import { useAsync } from '../hooks/useAsync';
import { ticketMeta, ticketTitle } from '../i18n/messages';
import { useLocale, useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import type { People } from '../lib/events';
import { dateTime, relative } from '../lib/format';
import { REASON, ROLE } from '../lib/labels';
import { villageLabel } from '../lib/places';
import { istDate } from '../lib/time';
import { verifyDates, verifyStartedAt, verifyTally } from '../lib/verify';
import styles from './TicketPage.module.css';

const FIXABLE: TicketState[] = ['OPEN', 'ASSIGNED', 'REOPENED', 'ESCALATED'];

/** Names stay as written (usually Devanagari), beside the masked phone or the role. */
function peopleOf(detail: VillageDetail | undefined): People {
  const people: People = {};
  for (const h of detail?.households ?? []) {
    const name = h.display_name || h.id;
    people[h.id] = { en: `${name} (${h.phone_masked})`, hi: `${name} (${h.phone_masked})` };
  }
  for (const o of detail?.operators ?? []) {
    const name = o.display_name || o.id;
    people[o.id] = { en: `${name}, ${ROLE[o.role].en}`, hi: `${name}, ${ROLE[o.role].hi}` };
  }
  return people;
}

function washFor(state: TicketState): WashTone {
  if (state === 'CLOSED_VERIFIED') return 'supplied';
  if (state === 'OPERATOR_REPORTED_FIXED' || state === 'VERIFYING') return 'partial';
  return 'no';
}

type Busy = 'fixed' | 'close' | null;

interface Progress {
  yes: number;
  needed: number;
}

/**
 * While households are being asked, how many have confirmed water is back. Read from the
 * VERIFY check-ins of the current round, so it works the same against the API and the mock.
 */
function useVerifyProgress(ticket: Ticket | undefined, quorum: number | undefined): Progress | null {
  const api = useApi();
  const since = ticket ? verifyStartedAt(ticket.events) : null;
  const active = ticket?.state === 'VERIFYING' && since !== null && quorum !== undefined;
  const key = active && ticket ? `verify:${ticket.id}:${since}:${ticket.updated_at}` : 'verify:none';
  const tally = useAsync(async () => {
    if (!active || !ticket || !since) return null;
    const dates = verifyDates(since, istDate(new Date()));
    const lists = await Promise.all(
      dates.map((d) => api.getCheckins(ticket.village_id, d, 'VERIFY')),
    );
    return verifyTally(lists.flat(), since);
  }, key);
  if (!active || !tally.data || quorum === undefined) return null;
  return { yes: tally.data.yes, needed: quorum };
}

function Actions({ ticket, detail, progress, onTicket, onDenied }: {
  ticket: Ticket;
  detail: VillageDetail | undefined;
  progress: Progress | null;
  onTicket: (t: Ticket) => void;
  onDenied: (d: PolicyDenied) => void;
}) {
  const api = useApi();
  const t = useT();
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
    <div className={cx('board', styles.actions)}>
      {progress && (
        <div className={styles.verify}>
          <h2 className={styles.cardTitle}>
            {t({ en: 'Households confirming the repair', hi: 'मरम्मत की पुष्टि करते घर' })}
          </h2>
          <Confirmations yes={progress.yes} needed={progress.needed} />
        </div>
      )}
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
              en={busy === 'fixed' ? 'Saving' : 'Operator reports fixed'}
              hi={busy === 'fixed' ? 'दर्ज हो रहा है' : 'नल जल मित्र ने ठीक बताया'}
            />
          </button>
        )}
        <button type="button" className="btn btn-stamp" onClick={close} disabled={busy !== null}>
          <IconCheck />
          <Bi
            en={busy === 'close' ? 'Checking' : 'Close ticket'}
            hi={busy === 'close' ? 'जाँच हो रही है' : 'शिकायत बंद करें'}
          />
        </button>
      </div>
      <Bi
        as="p"
        en="A ticket closes only after households confirm by phone that water is back."
        hi="शिकायत तभी बंद होगी जब घर फ़ोन पर पानी आने की पुष्टि करें।"
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
  const { locale } = useLocale();
  const t = useT();
  const ticket = useAsync(() => api.getTicket(tid), `ticket:${tid}`);
  const vid = ticket.data?.village_id ?? '';
  const villageQ = useAsync(
    () => (vid ? api.getVillage(vid) : Promise.resolve(undefined)),
    `village:${vid}`,
  );
  const [denied, setDenied] = useState<PolicyDenied | null>(null);
  const people = useMemo(() => peopleOf(villageQ.data), [villageQ.data]);
  const progress = useVerifyProgress(ticket.data, villageQ.data?.village.quorum);

  if (!ticket.data) {
    return (
      <div className="page">
        {ticket.loading ? <Loading /> : <ErrorNote error={ticket.error} onRetry={ticket.reload} />}
      </div>
    );
  }

  const tk = ticket.data;
  const village = villageQ.data?.village;
  const name = village ? villageLabel(village, locale) : tk.village_id;
  const closedAt = [...tk.events].reverse().find((e) => e.to_state === 'CLOSED_VERIFIED')?.at;
  const updateTicket = (next: Ticket) => {
    ticket.setData(next);
    if (next.state === 'CLOSED_VERIFIED') setDenied(null);
  };

  return (
    <div className="page">
      <Link to={`/villages/${encodeURIComponent(tk.village_id)}`} className="backlink">
        <IconBack />
        {village ? <VillageName village={village} /> : <Bi en="Village record" hi="गाँव का हिसाब" />}
      </Link>
      <header className={styles.header}>
        <div className={cx(styles.titleBlock, 'has-wash')}>
          <Wash seed={`${tk.id}:head`} tone={washFor(tk.state)} bleed />
          <p className={styles.kicker}>
            {t({ en: 'Repair ticket', hi: 'मरम्मत की शिकायत' })} <span translate="no">{tk.id}</span>
          </p>
          <h1 className={styles.title}>{t(ticketTitle, { reason: t(REASON[tk.reason]), village: name })}</h1>
          <div className={styles.meta}>
            <TicketStateBadge state={tk.state} />
            <span>
              {t(ticketMeta, { opened: t(dateTime(tk.opened_at)), updated: t(relative(tk.updated_at)) })}
            </span>
          </div>
        </div>
        {closedAt && <VerifiedStamp at={closedAt} seed={tk.id} />}
      </header>

      <section className={styles.section} aria-label={t({ en: 'Repair progress', hi: 'मरम्मत कहाँ तक पहुँची' })}>
        <TicketProgress state={tk.state} />
      </section>

      {tk.state !== 'CLOSED_VERIFIED' && (
        <section className={styles.section} aria-label={t({ en: 'Actions', hi: 'कार्रवाई' })}>
          <Actions
            ticket={tk}
            detail={villageQ.data}
            progress={progress}
            onTicket={updateTicket}
            onDenied={setDenied}
          />
          {denied && (
            <PolicyDenial
              denied={denied}
              progress={denied.policy_id === 'verify-needs-quorum' ? progress : null}
              onDismiss={() => setDenied(null)}
            />
          )}
        </section>
      )}

      <section className={styles.section} aria-labelledby="history-title">
        <div className={styles.historyHead}>
          <Bi as="h2" id="history-title" en="What happened" hi="क्या हुआ, कब और किसने" className="section-title" />
          <Bi
            as="p"
            className="meta"
            en="Oldest first, times in IST. Household answers have round markers; system and rule decisions have square ones."
            hi="पुराने पहले, समय IST में। घरों के जवाब गोल निशान से; प्रणाली और नियम के फ़ैसले चौकोर निशान से।"
          />
        </div>
        <Timeline events={tk.events} people={people} />
      </section>
    </div>
  );
}
