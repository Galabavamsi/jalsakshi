import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import type { DayStatus, HouseholdMasked, IsoDate } from '../api/types';
import { Bi } from '../components/Bi';
import { IconBack, IconDoc } from '../components/Icons';
import { ErrorNote, Loading } from '../components/PageState';
import { StatusLegend, StatusStrip } from '../components/StatusStrip';
import { useAsync, type AsyncState } from '../hooks/useAsync';
import { addDays, istDate } from '../lib/time';
import { ClaimSummary } from './village/ClaimSummary';
import { ContextPanel } from './village/ContextPanel';
import { DayDetail } from './village/DayDetail';
import { HouseholdList, OperatorList } from './village/People';
import { RunCheckin } from './village/RunCheckin';
import { TicketList } from './village/TicketList';
import styles from './village/VillageDetail.module.css';

const STRIP_DAYS = 14;

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
  const [picked, setPicked] = useState<IsoDate | null>(null);
  const list = days.data ?? [];
  const selectedDate = picked ?? list[list.length - 1]?.date ?? null;
  const selected = list.find((d) => d.date === selectedDate);
  return (
    <section className={styles.section} aria-labelledby="strip-title">
      <Bi as="h2" id="strip-title" hi="पिछले 14 दिन" en="Last 14 days" className="section-title" />
      <p className={styles.hint}>
        <Bi
          inline
          hi="किसी दिन को दबाएँ, उस दिन हर घर का जवाब दिखेगा।"
          en="Pick a day to see each household's answer."
        />
      </p>
      {days.loading && !days.data && <Loading />}
      {days.error ? <ErrorNote error={days.error} onRetry={days.reload} /> : null}
      {days.data && (
        <>
          <StatusStrip
            days={list}
            from={from}
            to={today}
            today={today}
            selected={selectedDate}
            onSelect={setPicked}
          />
          <StatusLegend />
          {selected && <DayDetail villageId={vid} day={selected} households={households} />}
        </>
      )}
    </section>
  );
}

/** One village: the 14-day record, tickets, context and who is on the roster. */
export function VillageDetailPage() {
  const { vid = '' } = useParams();
  const api = useApi();
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
  return (
    <div className="page">
      <Link to="/" className="backlink no-print">
        <IconBack />
        <Bi inline hi="सभी गाँव" en="All villages" />
      </Link>
      <header className={styles.header}>
        <h1 className="painted">{village.name}</h1>
        <Bi
          hi={`${village.block} विकासखंड, ${village.district} ज़िला। रोज़ ${village.checkin_local_time} बजे ${callable} घरों को कॉल। दिन तय करने के लिए कम से कम ${village.quorum} घरों का जवाब ज़रूरी।`}
          en={`${village.block} block, ${village.district} district. ${callable} households are called daily at ${village.checkin_local_time} IST. At least ${village.quorum} must answer for the day to count.`}
          className={styles.intro}
        />
        <ClaimSummary village={village} days={days.data} today={today} />
        <div className={styles.actions}>
          <RunCheckin villageId={village.id} households={callable} />
          <Link to={`/villages/${encodeURIComponent(village.id)}/brief`} className="btn btn-secondary">
            <IconDoc />
            <Bi hi="ग्राम सभा पत्र" en="Gram Sabha brief" />
          </Link>
        </div>
      </header>

      <div className={styles.columns}>
        <div className={styles.mainCol}>
          <StripSection
            vid={village.id}
            households={households}
            days={days}
            from={from}
            today={today}
          />
          <section className={styles.section} aria-labelledby="tickets-title">
            <Bi as="h2" id="tickets-title" hi="शिकायतें" en="Repair tickets" className="section-title" />
            {tickets.loading && !tickets.data && <Loading />}
            {tickets.error ? <ErrorNote error={tickets.error} onRetry={tickets.reload} /> : null}
            {tickets.data && <TicketList tickets={tickets.data} />}
          </section>
        </div>
        <aside className={styles.sideCol}>
          <section className={styles.section} aria-labelledby="context-title">
            <Bi as="h2" id="context-title" hi="संदर्भ" en="Context" className="section-title" />
            <ContextPanel context={context} />
          </section>
          <section className={styles.section} aria-labelledby="households-title">
            <Bi
              as="h2"
              id="households-title"
              hi={`पंजीकृत घर (${households.length})`}
              en={`Registered households (${households.length})`}
              className="section-title"
            />
            <HouseholdList households={households} />
          </section>
          <section className={styles.section} aria-labelledby="operators-title">
            <Bi as="h2" id="operators-title" hi="ज़िम्मेदार लोग" en="Operators" className="section-title" />
            <OperatorList operators={operators} />
          </section>
        </aside>
      </div>
    </div>
  );
}
