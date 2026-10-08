import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import type { VillageSummary } from '../api/types';
import { isMock } from '../appConfig';
import { Bi } from '../components/Bi';
import { IconForward, IconTicket } from '../components/Icons';
import { Empty, ErrorNote, Loading } from '../components/PageState';
import { RegisterSlip } from '../components/RegisterSlip';
import { SourceBadge } from '../components/SourceBadge';
import { StatusChip } from '../components/StatusChip';
import { TallyTiles } from '../components/TallyTiles';
import { TicketStateBadge } from '../components/TicketParts';
import { Verdict } from '../components/Verdict';
import { VillageName } from '../components/VillageName';
import { Wash, toneFor } from '../components/Wash';
import { useAsync } from '../hooks/useAsync';
import { openTicketLine, villagesLede } from '../i18n/messages';
import { useLocale, useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { relative } from '../lib/format';
import { REASON } from '../lib/labels';
import { placeLine } from '../lib/places';
import { WINDOW_DAYS } from '../lib/reliability';
import { checkinSource } from '../lib/sources';
import { dominantStatus, sortByVerdict, verdictOf } from '../lib/verdict';
import styles from './VillagesPage.module.css';

/** Washes per page are capped at 8: the hero plus up to seven boards. */
const MAX_BOARD_WASHES = 7;

function HouseholdsSaid({ summary, painted }: { summary: VillageSummary; painted: boolean }) {
  const { locale } = useLocale();
  const t = useT();
  const o = summary.observed_7d;
  const tone = toneFor(dominantStatus(o));
  const n = <strong className={cx(styles.numeral, 'num')}>{o.supplied}</strong>;
  return (
    <div className={cx(styles.witness, 'has-wash')}>
      {painted && <Wash seed={summary.village.id} tone={tone} bleed className={styles.panelWash} />}
      <h3 className={styles.sideTitle}>
        {t({ en: 'Households said, last 7 days', hi: 'घरों ने बताया, पिछले 7 दिन' })}
      </h3>
      <p className={styles.big}>
        {locale === 'hi' ? (
          <>
            {WINDOW_DAYS} में से {n} दिन पानी आया
          </>
        ) : (
          <>
            Water came on {n} of {WINDOW_DAYS} days
          </>
        )}
      </p>
      <TallyTiles observed={o} />
      <SourceBadge source={o.source ?? checkinSource(summary.today?.computed_at, isMock)} />
    </div>
  );
}

function OpenTicket({ summary }: { summary: VillageSummary }) {
  const t = useT();
  const ticket = summary.open_ticket;
  if (!ticket) {
    return <Bi as="p" en="No repair ticket open." hi="कोई मरम्मत की शिकायत खुली नहीं।" className={styles.noTicket} />;
  }
  return (
    <Link to={`/tickets/${encodeURIComponent(ticket.id)}`} className={styles.ticket}>
      <IconTicket size={24} className={styles.ticketIcon} />
      <span className={styles.ticketText}>
        {t(openTicketLine, { reason: t(REASON[ticket.reason]), since: t(relative(ticket.opened_at)) })}
      </span>
      <TicketStateBadge state={ticket.state} />
      <IconForward size={20} className={styles.chev} />
    </Link>
  );
}

function VillageBoard({ summary, painted }: { summary: VillageSummary; painted: boolean }) {
  const { locale } = useLocale();
  const t = useT();
  const { village, today } = summary;
  const href = `/villages/${encodeURIComponent(village.id)}`;
  const verdict = verdictOf(village, summary.observed_7d);
  return (
    <li className={cx('board', styles.board)}>
      <div className={styles.head}>
        <div className={styles.name}>
          <h2>
            <Link to={href}>
              <VillageName village={village} />
            </Link>
          </h2>
          <p className={styles.place}>{placeLine(village, locale)}</p>
        </div>
        <div className={styles.today}>
          <span className={styles.todayLabel}>{t({ en: 'Today', hi: 'आज' })}</span>
          {today ? (
            <StatusChip status={today.status} />
          ) : (
            <span className={styles.pending}>
              {t({
                en: `Calls at ${village.checkin_local_time} IST`,
                hi: `कॉल ${village.checkin_local_time} बजे`,
              })}
            </span>
          )}
        </div>
      </div>

      <div className={styles.verdict}>
        <Verdict verdict={verdict} checkinTime={village.checkin_local_time} />
      </div>

      <div className={styles.compare}>
        <RegisterSlip village={village} />
        <HouseholdsSaid summary={summary} painted={painted} />
      </div>

      <div className={styles.foot}>
        <OpenTicket summary={summary} />
        <Link to={href} className="btn btn-secondary">
          <Bi en="Open village record" hi="गाँव का पूरा हिसाब" />
          <IconForward />
        </Link>
      </div>
    </li>
  );
}

/** Home: every village's household answers next to what the state record claims. */
export function VillagesPage() {
  const api = useApi();
  const t = useT();
  const { data, error, loading, reload } = useAsync(() => api.listVillages(), 'villages');
  const boards = data ? sortByVerdict(data) : [];
  const claimed = boards.filter((s) => s.village.claimed_hgj === true).length;
  const gap = boards.filter((s) => verdictOf(s.village, s.observed_7d).kind === 'gap').length;
  return (
    <div className="page">
      <header className={styles.hero}>
        <div className={cx(styles.band, 'has-wash')}>
          <Wash seed="villages:hero" tone="jal" bleed className={styles.heroWash} />
          <h1 className="wall-lettering">{t({ en: 'Did tap water come today?', hi: 'आज नल में पानी आया?' })}</h1>
        </div>
        {data && claimed > 0 && <p className={cx('lede', styles.lede)}>{t(villagesLede, { gap, claimed })}</p>}
        <Bi
          as="p"
          className={styles.how}
          en="Each morning, households answer one phone call. What they said sits beside the state record, so the two can be compared."
          hi="हर सुबह घर एक फ़ोन कॉल का जवाब देते हैं। उन्होंने जो बताया, वह सरकारी रिकॉर्ड के साथ रखा है, ताकि दोनों की तुलना हो सके।"
        />
      </header>
      {loading && !data && <Loading />}
      {error ? <ErrorNote error={error} onRetry={reload} /> : null}
      {data && data.length === 0 && (
        <Empty
          text={{
            en: 'No villages yet. A village appears here once it is registered and its households have given consent.',
            hi: 'अभी कोई गाँव नहीं जुड़ा है। गाँव पंजीकृत होने और घरों की सहमति के बाद यहाँ दिखेगा।',
          }}
        />
      )}
      {boards.length > 0 && (
        <ul className={styles.boards}>
          {boards.map((s, i) => (
            <VillageBoard key={s.village.id} summary={s} painted={i < MAX_BOARD_WASHES} />
          ))}
        </ul>
      )}
    </div>
  );
}
