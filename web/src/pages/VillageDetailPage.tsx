import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import type { DayStatus, HouseholdMasked, IsoDate } from '../api/types';
import { Bi } from '../components/Bi';
import { IconBack, IconDoc } from '../components/Icons';
import { ErrorNote, Loading } from '../components/PageState';
import { StatusLegend, StatusStrip, StatusTable } from '../components/StatusStrip';
import { VillageName } from '../components/VillageName';
import { Wash, toneFor } from '../components/Wash';
import { useAsync, type AsyncState } from '../hooks/useAsync';
import { householdsTitle, villageIntro } from '../i18n/messages';
import { useLocale, useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { placeLine } from '../lib/places';
import { addDays, istDate } from '../lib/time';
import { ClaimSummary } from './village/ClaimSummary';
import { ContextPanel } from './village/ContextPanel';
import { DayDetail } from './village/DayDetail';
import { HouseholdList, OperatorList } from './village/People';
import { RunCheckin } from './village/RunCheckin';
import { TicketList } from './village/TicketList';
import styles from './village/VillageDetail.module.css';

const STRIP_DAYS = 14;

type View = 'strip' | 'table';

function StripSection({
  vid,
  households,
  days,
  from,
  today,
}: {
  vid: string;
  households: HouseholdMasked[];
  days: AsyncState<DayStatus[]>;
  from: IsoDate;
  today: IsoDate;
}) {
  const t = useT();
  const [picked, setPicked] = useState<IsoDate | null>(null);
  const [view, setView] = useState<View>('strip');
  const list = days.data ?? [];
  const selectedDate = picked ?? list[list.length - 1]?.date ?? null;
  const selected = list.find((d) => d.date === selectedDate);
  const views: Array<{ id: View; label: { en: string; hi: string } }> = [
    { id: 'strip', label: { en: 'Strip', hi: 'पट्टी' } },
    { id: 'table', label: { en: 'Table', hi: 'तालिका' } },
  ];
  return (
    <section className={cx('board', styles.stripBoard)} aria-labelledby="strip-title">
      <div className={styles.sectionHead}>
        <Bi as="h2" id="strip-title" en="Last 14 days" hi="पिछले 14 दिन" className="section-title" />
        <div className="seg" role="group" aria-label={t({ en: 'Show the days as', hi: 'दिन ऐसे दिखाएँ' })}>
          {views.map((v) => (
            <button
              key={v.id}
              type="button"
              className="seg-opt"
              aria-pressed={view === v.id}
              onClick={() => setView(v.id)}
            >
              {t(v.label)}
            </button>
          ))}
        </div>
      </div>
      {view === 'strip' && (
        <Bi
          as="p"
          className={styles.hint}
          en="Pick a day to see each household's answer."
          hi="किसी दिन को दबाएँ, उस दिन हर घर का जवाब दिखेगा।"
        />
      )}
      {days.loading && !days.data && <Loading />}
      {days.error ? <ErrorNote error={days.error} onRetry={days.reload} /> : null}
      {days.data && (
        <>
          {view === 'strip' ? (
            <StatusStrip
              days={list}
              from={from}
              to={today}
              today={today}
              selected={selectedDate}
              onSelect={setPicked}
            />
          ) : (
            <StatusTable days={list} from={from} to={today} today={today} />
          )}
          <StatusLegend />
          {view === 'strip' && selected && <DayDetail villageId={vid} day={selected} households={households} />}
        </>
      )}
    </section>
  );
}

/** One village: the 14-day record, tickets, context and who is on the roster. */
export function VillageDetailPage() {
  const { vid = '' } = useParams();
  const api = useApi();
  const { locale } = useLocale();
  const t = useT();
  const detail = useAsync(() => api.getVillage(vid), `village:${vid}`);
  const tickets = useAsync(() => api.listTickets({ village_id: vid }), `tickets:${vid}`);
  const today = istDate(new Date());
  const from = addDays(today, -(STRIP_DAYS - 1));
  const days = useAsync(() => api.getDays(vid, from, today), `days:${vid}:${from}:${today}`);

  if (detail.loading && !detail.data) {
    return (
      <div className="page">
        <Loading />
      </div>
    );
  }
  if (!detail.data) {
    return (
      <div className="page">
        <ErrorNote error={detail.error} onRetry={detail.reload} />
      </div>
    );
  }

  const { village, households, operators, context } = detail.data;
  const callable = households.filter((h) => h.active && h.consent).length;
  const todayStatus = days.data?.find((d) => d.date === today)?.status;
  return (
    <div className="page">
      <Link to="/" className="backlink no-print">
        <IconBack />
        <Bi en="All villages" hi="सभी गाँव" />
      </Link>
      <header className={styles.header}>
        <div className={cx(styles.titleBand, 'has-wash')}>
          <Wash seed={`${village.id}:page`} tone={todayStatus ? toneFor(todayStatus) : 'jal'} bleed />
          <h1 className={styles.title}>
            <VillageName village={village} />
          </h1>
          <p className={styles.intro}>
            {t(villageIntro, {
              place: placeLine(village, locale),
              callable,
              time: village.checkin_local_time,
              quorum: village.quorum,
            })}
          </p>
        </div>
        <ClaimSummary village={village} days={days.data} today={today} />
        <div className={styles.actions}>
          <RunCheckin villageId={village.id} households={callable} />
          <Link to={`/villages/${encodeURIComponent(village.id)}/brief`} className="btn btn-secondary">
            <IconDoc />
            <Bi en="Gram Sabha brief" hi="ग्राम सभा पत्र" />
          </Link>
        </div>
      </header>

      <div className={styles.columns}>
        <div className={styles.mainCol}>
          <StripSection vid={village.id} households={households} days={days} from={from} today={today} />
          <section className={styles.section} aria-labelledby="tickets-title">
            <Bi as="h2" id="tickets-title" en="Repair tickets" hi="मरम्मत की शिकायतें" className="section-title" />
            {tickets.loading && !tickets.data && <Loading />}
            {tickets.error ? <ErrorNote error={tickets.error} onRetry={tickets.reload} /> : null}
            {tickets.data && <TicketList tickets={tickets.data} />}
          </section>
        </div>
        <aside className={styles.sideCol}>
          <section className={styles.section} aria-labelledby="context-title">
            <Bi as="h2" id="context-title" en="Context" hi="संदर्भ" className="section-title" />
            <ContextPanel context={context} />
          </section>
          <section className={styles.section} aria-labelledby="households-title">
            <h2 id="households-title" className="section-title">
              {t(householdsTitle, { n: households.length })}
            </h2>
            <HouseholdList households={households} />
          </section>
          <section className={styles.section} aria-labelledby="operators-title">
            <Bi as="h2" id="operators-title" en="Operators" hi="ज़िम्मेदार लोग" className="section-title" />
            <OperatorList operators={operators} />
          </section>
        </aside>
      </div>
    </div>
  );
}
