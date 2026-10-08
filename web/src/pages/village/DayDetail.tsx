import { useApi } from '../../api/context';
import type { CheckInMasked, DayStatus, HouseholdMasked } from '../../api/types';
import { isMock } from '../../appConfig';
import { Bi } from '../../components/Bi';
import { IconMic } from '../../components/Icons';
import { ErrorNote, Loading } from '../../components/PageState';
import { SourceBadge } from '../../components/SourceBadge';
import { StatusChip } from '../../components/StatusChip';
import { useAsync } from '../../hooks/useAsync';
import { clockTime, longDate } from '../../lib/format';
import { CLEAN, OUTCOME, WATER } from '../../lib/labels';
import { checkinSource, fromSimulator } from '../../lib/sources';
import styles from './VillageDetail.module.css';

const COUNT_ROWS = [
  { key: 'answered', hi: 'जवाब दिया', en: 'Answered' },
  { key: 'yes', hi: 'पानी आया', en: 'Yes' },
  { key: 'partial', hi: 'थोड़ा', en: 'A little' },
  { key: 'no', hi: 'नहीं आया', en: 'No' },
  { key: 'dirty', hi: 'गंदा', en: 'Dirty' },
  { key: 'unreachable', hi: 'संपर्क नहीं', en: 'Unreachable' },
] as const;

function Answer({ c }: { c: CheckInMasked }) {
  if (c.outcome !== 'ANSWERED') return <Bi t={OUTCOME[c.outcome]} className={styles.answerMuted} />;
  if (!c.water) return <Bi hi="जवाब नहीं चुना" en="No answer given" className={styles.answerMuted} />;
  const parts = [WATER[c.water].hi];
  const partsEn = [WATER[c.water].en];
  if (c.hours !== null && c.hours !== undefined) {
    parts.push(`${c.hours} घंटे`);
    partsEn.push(`${c.hours} h`);
  }
  if (c.clean) {
    parts.push(CLEAN[c.clean].hi);
    partsEn.push(CLEAN[c.clean].en);
  }
  return <Bi hi={parts.join(', ')} en={partsEn.join(', ')} className={styles.answer} />;
}

function CheckinRow({ c, name }: { c: CheckInMasked; name: string }) {
  return (
    <li className={styles.checkin}>
      <div className={styles.who}>
        <span className={styles.whoName}>{name}</span>
        <span className={styles.phone}>{c.phone_masked ?? c.household_id}</span>
      </div>
      <Answer c={c} />
      <span className={styles.when}>
        {clockTime(c.captured_at)}
        {c.attempt > 1 && <span lang="en"> (attempt {c.attempt})</span>}
        {c.captured_via === 'SIMULATOR' && <span lang="en"> (simulator)</span>}
      </span>
      {c.note_transcript && (
        <p className={styles.note}>
          <IconMic size={18} />
          <span lang="hi">“{c.note_transcript}”</span>
          {c.note_issue && <span className={styles.issue}>{c.note_issue}</span>}
        </p>
      )}
    </li>
  );
}

/** Counts and individual answers for one day of the strip. */
export function DayDetail({
  villageId,
  day,
  households,
}: {
  villageId: string;
  day: DayStatus;
  households: HouseholdMasked[];
}) {
  const api = useApi();
  const checkins = useAsync(
    () => api.getCheckins(villageId, day.date, 'DAILY'),
    `${villageId}:${day.date}:${day.computed_at}`,
  );
  const names = new Map(households.map((h) => [h.id, h.display_name || h.id]));
  const date = longDate(day.date);
  return (
    <section className={styles.day} aria-labelledby="day-title">
      <div className={styles.dayHead}>
        <Bi as="h3" id="day-title" t={date} className={styles.dayTitle} />
        <StatusChip status={day.status} />
      </div>
      <dl className={styles.counts}>
        {COUNT_ROWS.map((row) => (
          <div key={row.key}>
            <Bi as="dt" hi={row.hi} en={row.en} />
            <dd className="num">{day.counts[row.key]}</dd>
          </div>
        ))}
      </dl>
      <p className={styles.rule}>
        <span lang="hi">नियम {day.rule_version} से तय, कोई AI नहीं।</span>{' '}
        <span lang="en">Decided by rule {day.rule_version}; no AI involved.</span>
      </p>
      <SourceBadge source={checkinSource(day.computed_at, isMock, fromSimulator(checkins.data))} />
      {checkins.loading && !checkins.data && <Loading />}
      {checkins.error ? <ErrorNote error={checkins.error} onRetry={checkins.reload} /> : null}
      {checkins.data && checkins.data.length > 0 && (
        <ul className={styles.checkins} aria-label="Answers from each household">
          {checkins.data.map((c) => (
            <CheckinRow key={`${c.household_id}-${c.attempt}`} c={c} name={names.get(c.household_id) ?? c.household_id} />
          ))}
        </ul>
      )}
    </section>
  );
}
