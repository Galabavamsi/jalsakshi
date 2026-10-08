import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import type { VillageSummary } from '../api/types';
import { isMock } from '../appConfig';
import { Bi } from '../components/Bi';
import { IconForward, IconTicket } from '../components/Icons';
import { Empty, ErrorNote, Loading } from '../components/PageState';
import { SourceBadge } from '../components/SourceBadge';
import { StatusChip } from '../components/StatusChip';
import { TallyTiles } from '../components/TallyTiles';
import { TicketStateBadge } from '../components/TicketParts';
import { useAsync } from '../hooks/useAsync';
import { cx } from '../lib/cx';
import { relative, type Bilingual } from '../lib/format';
import { REASON } from '../lib/labels';
import { WINDOW_DAYS } from '../lib/reliability';
import { checkinSource } from '../lib/sources';
import styles from './VillagesPage.module.css';

function yesNo(value: boolean | null | undefined): Bilingual {
  if (value === true) return { hi: 'हाँ', en: 'Yes' };
  if (value === false) return { hi: 'नहीं', en: 'No' };
  return { hi: 'पता नहीं', en: 'Unknown' };
}

function Claim({ summary }: { summary: VillageSummary }) {
  const { village } = summary;
  return (
    <section className={styles.claim} aria-label="State claim">
      <Bi as="h3" hi="राज्य का दावा" en="What the state reports" className={styles.sideTitle} />
      <dl className={styles.facts}>
        <div>
          <Bi as="dt" hi="हर घर जल घोषित" en="Declared Har Ghar Jal" />
          <Bi as="dd" t={yesNo(village.claimed_hgj)} />
        </div>
        <div>
          <Bi as="dt" hi="ग्राम सभा से प्रमाणित" en="Certified by Gram Sabha" />
          <Bi as="dd" t={yesNo(village.hgj_certified)} />
        </div>
      </dl>
      {village.claimed_source && <SourceBadge source={village.claimed_source} />}
    </section>
  );
}

function Witness({ summary }: { summary: VillageSummary }) {
  const o = summary.observed_7d;
  return (
    <section className={styles.witness} aria-label="Household answers">
      <Bi
        as="h3"
        hi="घरों की गवाही, पिछले 7 दिन"
        en="What households said, last 7 days"
        className={styles.sideTitle}
      />
      <p className={styles.big}>
        <span lang="hi">
          {WINDOW_DAYS} में से <strong className="num">{o.supplied}</strong> दिन पानी आया
        </span>
        <span lang="en" className={styles.bigEn}>
          Water came on {o.supplied} of {WINDOW_DAYS} days
        </span>
      </p>
      <TallyTiles observed={o} />
      <SourceBadge source={o.source ?? checkinSource(summary.today?.computed_at, isMock)} />
    </section>
  );
}

function OpenTicket({ summary }: { summary: VillageSummary }) {
  const t = summary.open_ticket;
  if (!t) {
    return (
      <p className={styles.noTicket}>
        <Bi inline hi="कोई खुली शिकायत नहीं" en="No open ticket" />
      </p>
    );
  }
  const since = relative(t.opened_at);
  return (
    <Link to={`/tickets/${encodeURIComponent(t.id)}`} className={styles.ticket}>
      <IconTicket size={26} />
      <span className={styles.ticketText}>
        <Bi hi={`खुली शिकायत: ${REASON[t.reason].hi}`} en={`Open ticket: ${REASON[t.reason].en}`} />
        <span className={styles.ticketWhen}>
          <span lang="hi">{since.hi} खुली</span> <span lang="en">(opened {since.en})</span>
        </span>
      </span>
      <TicketStateBadge state={t.state} />
      <IconForward size={22} className={styles.chev} />
    </Link>
  );
}

function VillageBoard({ summary }: { summary: VillageSummary }) {
  const { village, today } = summary;
  const href = `/villages/${encodeURIComponent(village.id)}`;
  return (
    <li className={cx(styles.board, today ? `st-${today.status}` : styles.noToday)}>
      <div className={styles.head}>
        <div className={styles.name}>
          <h2>
            <Link to={href}>{village.name}</Link>
          </h2>
          <Bi
            hi={`${village.block} विकासखंड, ${village.district} ज़िला`}
            en={`${village.block} block, ${village.district} district`}
            className={styles.place}
          />
        </div>
        <div className={styles.today}>
          <Bi hi="आज" en="Today" className={styles.todayLabel} />
          {today ? (
            <StatusChip status={today.status} size="l" />
          ) : (
            <Bi
              hi={`आज के कॉल ${village.checkin_local_time} बजे होंगे`}
              en={`Today's calls at ${village.checkin_local_time} IST`}
              className={styles.pending}
            />
          )}
        </div>
      </div>
      <div className={styles.compare}>
        <Claim summary={summary} />
        <span className={styles.versus} aria-hidden="true">
          <span lang="hi">बनाम</span>
          <span lang="en">vs</span>
        </span>
        <Witness summary={summary} />
      </div>
      <div className={styles.foot}>
        <OpenTicket summary={summary} />
        <Link to={href} className="btn btn-secondary">
          <Bi hi="गाँव का पूरा हिसाब" en="Open village record" />
          <IconForward />
        </Link>
      </div>
    </li>
  );
}

/** Home: every village's household answers next to what the state reports. */
export function VillagesPage() {
  const api = useApi();
  const { data, error, loading, reload } = useAsync(() => api.listVillages(), 'villages');
  return (
    <div className="page">
      <header className={styles.hero}>
        <h1 className="painted" lang="hi">
          आज नल में पानी आया?
        </h1>
        <p className={styles.lede} lang="hi">
          गाँव के घर रोज़ फ़ोन पर यही बताते हैं। यहाँ उनकी गवाही है, राज्य के दावे के साथ।
        </p>
        <p className={styles.ledeEn} lang="en">
          Did tap water come today? Households answer this by phone every day. Here is what they
          said, next to what the state reports.
        </p>
      </header>
      {loading && !data && <Loading />}
      {error ? <ErrorNote error={error} onRetry={reload} /> : null}
      {data && data.length === 0 && (
        <Empty
          text={{
            hi: 'अभी कोई गाँव नहीं जुड़ा है।',
            en: 'No villages yet. Villages appear here once they are registered.',
          }}
        />
      )}
      {data && data.length > 0 && (
        <ul className={styles.boards}>
          {data.map((s) => (
            <VillageBoard key={s.village.id} summary={s} />
          ))}
        </ul>
      )}
    </div>
  );
}
