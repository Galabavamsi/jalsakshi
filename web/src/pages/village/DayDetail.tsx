import { useApi } from '../../api/context';
import type { CheckInMasked, DayStatus, DayStatusValue, HouseholdMasked, WaterAnswer } from '../../api/types';
import { isMock } from '../../appConfig';
import { IconMic, StatusIcon } from '../../components/Icons';
import { ErrorNote, Loading } from '../../components/PageState';
import { SourceBadge } from '../../components/SourceBadge';
import { useAsync } from '../../hooks/useAsync';
import { dayHeadline } from '../../i18n/messages';
import { useT } from '../../i18n/locale';
import { cx } from '../../lib/cx';
import { viaName } from '../../lib/events';
import { clockTime, shortDate, weekdayName } from '../../lib/format';
import { CLEAN, OUTCOME, STATUS, WATER } from '../../lib/labels';
import { checkinSource, fromSimulator } from '../../lib/sources';
import styles from './VillageDetail.module.css';

const ANSWER_STATUS: Record<WaterAnswer, DayStatusValue> = {
  YES: 'SUPPLIED',
  NO: 'NO_SUPPLY',
  PARTIAL: 'PARTIAL',
};

/** One household's answer as a small painted chip (icon + word), then hours and cleanliness. */
function Answer({ c }: { c: CheckInMasked }) {
  const t = useT();
  if (c.outcome !== 'ANSWERED') return <span className={styles.answerMuted}>{t(OUTCOME[c.outcome])}</span>;
  if (!c.water) return <span className={styles.answerMuted}>{t({ en: 'No answer given', hi: 'जवाब नहीं चुना' })}</span>;
  const status = c.clean === 'NO' ? 'DIRTY' : ANSWER_STATUS[c.water];
  const extra: string[] = [];
  if (c.hours !== null && c.hours !== undefined) extra.push(t({ en: `${c.hours} h`, hi: `${c.hours} घंटे` }));
  if (c.clean) extra.push(t(CLEAN[c.clean]));
  return (
    <span className={styles.answer}>
      <span className={cx(styles.answerChip, 'paint paint-flat', `st-${status}`)}>
        <StatusIcon status={status} size={16} />
        {t(WATER[c.water])}
      </span>
      {extra.length > 0 && <span className={styles.answerExtra}>{extra.join(', ')}</span>}
    </span>
  );
}

function CheckinRow({ c, name }: { c: CheckInMasked; name: string }) {
  const t = useT();
  return (
    <li className={styles.checkin}>
      <div className={styles.who}>
        <span className={styles.whoName} lang="hi">
          {name}
        </span>
        <span className={styles.phone}>{c.phone_masked ?? c.household_id}</span>
      </div>
      <Answer c={c} />
      <span className={styles.when}>
        {t(viaName(c.captured_via))}, <span className="num">{clockTime(c.captured_at)}</span>
        {c.attempt > 1 && t({ en: ` (attempt ${c.attempt})`, hi: ` (प्रयास ${c.attempt})` })}
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
  const t = useT();
  const checkins = useAsync(
    () => api.getCheckins(villageId, day.date, 'DAILY'),
    `${villageId}:${day.date}:${day.computed_at}`,
  );
  const names = new Map(households.map((h) => [h.id, h.display_name || h.id]));
  const date = `${t(weekdayName(day.date))} ${t(shortDate(day.date))}`;
  return (
    <section className={cx(styles.day, `st-${day.status}`)} aria-labelledby="day-title">
      <h3 id="day-title" className={styles.dayTitle}>
        <StatusIcon status={day.status} size={22} className={styles.dayIcon} />
        <span>
          {t(dayHeadline, {
            date,
            status: t(STATUS[day.status]),
            answered: day.counts.answered,
            yes: day.counts.yes,
            no: day.counts.no,
          })}
        </span>
      </h3>
      {checkins.loading && !checkins.data && <Loading />}
      {checkins.error ? <ErrorNote error={checkins.error} onRetry={checkins.reload} /> : null}
      {checkins.data && checkins.data.length > 0 && (
        <ul className={styles.checkins} aria-label={t({ en: 'Answers from each household', hi: 'हर घर का जवाब' })}>
          {checkins.data.map((c) => (
            <CheckinRow
              key={`${c.household_id}-${c.attempt}`}
              c={c}
              name={names.get(c.household_id) ?? c.household_id}
            />
          ))}
        </ul>
      )}
      <div className={styles.dayFoot}>
        <p className={styles.rule}>
          {t({
            en: `Decided by rule ${day.rule_version}. No AI involved.`,
            hi: `नियम ${day.rule_version} से तय। कोई AI नहीं।`,
          })}
        </p>
        <SourceBadge source={checkinSource(day.computed_at, isMock, fromSimulator(checkins.data))} />
      </div>
    </section>
  );
}
