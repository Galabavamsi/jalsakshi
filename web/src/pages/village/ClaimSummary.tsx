import type { DayStatus, IsoDate, Village } from '../../api/types';
import { isMock } from '../../appConfig';
import { Bi } from '../../components/Bi';
import { SourceBadge } from '../../components/SourceBadge';
import { StatusChip } from '../../components/StatusChip';
import type { Bilingual } from '../../lib/format';
import { WINDOW_DAYS } from '../../lib/reliability';
import { checkinSource } from '../../lib/sources';
import { addDays } from '../../lib/time';
import styles from './VillageDetail.module.css';

function yesNo(value: boolean | null | undefined): Bilingual {
  if (value === true) return { hi: 'हाँ', en: 'Yes' };
  if (value === false) return { hi: 'नहीं', en: 'No' };
  return { hi: 'पता नहीं', en: 'Unknown' };
}

/**
 * The village's story in one row: what the state record claims, what households said over the
 * last seven days, and today's status.
 */
export function ClaimSummary({
  village,
  days,
  today,
}: {
  village: Village;
  /** Day statuses for at least the last seven days; undefined while loading. */
  days: DayStatus[] | undefined;
  today: IsoDate;
}) {
  const declared = yesNo(village.claimed_hgj);
  const certified = yesNo(village.hgj_certified);
  const from = addDays(today, -(WINDOW_DAYS - 1));
  const week = (days ?? []).filter((d) => d.date >= from && d.date <= today);
  const supplied = week.filter((d) => d.status === 'SUPPLIED').length;
  const todayStatus = (days ?? []).find((d) => d.date === today);
  const latest = week.reduce<DayStatus | undefined>(
    (best, d) => (!best || d.computed_at > best.computed_at ? d : best),
    undefined,
  );
  return (
    <div className={styles.summary}>
      <section className={styles.summaryClaim} aria-label="State record">
        <Bi as="h2" hi="सरकारी रिकॉर्ड में" en="In the state record" className={styles.summaryLabel} />
        <p className={styles.summaryValue}>
          <span lang="hi">
            हर घर जल: <strong className={styles.painted}>{declared.hi}</strong>
          </span>
          <span lang="en" className={styles.summaryEn}>
            Declared Har Ghar Jal (tap water in every home): {declared.en}
          </span>
        </p>
        <p className={styles.summaryCert}>
          <span lang="hi">
            ग्राम सभा का प्रमाणपत्र: <strong>{certified.hi}</strong>
          </span>{' '}
          <span lang="en">(Certified by the Gram Sabha: {certified.en})</span>
        </p>
        {village.claimed_source && <SourceBadge source={village.claimed_source} />}
      </section>
      <section className={styles.summaryWitness} aria-label="Household answers">
        <Bi
          as="h2"
          hi="घरों ने फ़ोन पर बताया, पिछले 7 दिन"
          en="What households said by phone, last 7 days"
          className={styles.summaryLabel}
        />
        {days ? (
          <>
            <p className={styles.summaryValue}>
              <span lang="hi">
                {WINDOW_DAYS} में से <strong className={styles.stamped}>{supplied}</strong> दिन पूरा
                पानी
              </span>
              <span lang="en" className={styles.summaryEn}>
                Full supply on {supplied} of {WINDOW_DAYS} days
              </span>
            </p>
            {latest && <SourceBadge source={checkinSource(latest.computed_at, isMock)} />}
          </>
        ) : (
          <p className={styles.summaryEn}>
            <Bi inline hi="आँकड़े आ रहे हैं" en="Loading" />
          </p>
        )}
      </section>
      <section className={styles.summaryToday} aria-label="Today">
        <Bi as="h2" hi="आज" en="Today" className={styles.summaryLabel} />
        {todayStatus ? (
          <StatusChip status={todayStatus.status} size="l" />
        ) : (
          <Bi
            hi={`कॉल ${village.checkin_local_time} बजे`}
            en={`Calls at ${village.checkin_local_time} IST`}
            className={styles.summaryPending}
          />
        )}
      </section>
    </div>
  );
}
