import type { DayStatus, IsoDate } from '../api/types';
import { DAY_STATUSES } from '../api/types';
import { cx } from '../lib/cx';
import { shortDate, weekdayName } from '../lib/format';
import { STATUS } from '../lib/labels';
import { dateRange } from '../lib/time';
import { Bi } from './Bi';
import { StatusIcon } from './Icons';
import styles from './StatusStrip.module.css';

interface StripProps {
  days: DayStatus[];
  from: IsoDate;
  to: IsoDate;
  today: IsoDate;
  selected?: IsoDate | null;
  onSelect?: (date: IsoDate) => void;
}

interface CellProps {
  date: IsoDate;
  day: DayStatus | undefined;
  today: IsoDate;
  selected: boolean;
  onSelect?: (date: IsoDate) => void;
}

const WEEK_LABELS = [
  { hi: 'उससे पहले के 7 दिन', en: 'The 7 days before' },
  { hi: 'पिछले 7 दिन', en: 'Last 7 days' },
];

function cellLabel(date: IsoDate, day: DayStatus | undefined): string {
  const d = shortDate(date);
  if (!day) return `${d.hi} (${d.en}): कोई आँकड़ा नहीं, no data`;
  const s = STATUS[day.status];
  const c = day.counts;
  return (
    `${d.hi} (${d.en}): ${s.hi}, ${s.en}. ` +
    `${c.answered} answered, ${c.no} no, ${c.partial} partial, ${c.dirty} dirty.`
  );
}

function Cell({ date, day, today, selected, onSelect }: CellProps) {
  const isToday = date === today;
  return (
    <li>
      <button
        type="button"
        className={cx(
          styles.cell,
          day ? `st-${day.status}` : styles.empty,
          selected && styles.selected,
          isToday && styles.today,
        )}
        aria-label={cellLabel(date, day)}
        aria-pressed={onSelect && day ? selected : undefined}
        disabled={!onSelect || !day}
        onClick={() => onSelect?.(date)}
      >
        <span className={styles.when} lang="hi">
          {isToday ? 'आज' : weekdayName(date).hi}
        </span>
        <span className={styles.date}>{Number(date.slice(8, 10))}</span>
        {day ? <StatusIcon status={day.status} size={24} /> : <span aria-hidden="true">–</span>}
        <span className={styles.word} lang="hi">
          {day ? STATUS[day.status].short : 'कॉल नहीं'}
        </span>
      </button>
    </li>
  );
}

/** Fourteen days in two rows of seven; the bottom row is the last seven days. */
export function StatusStrip({ days, from, to, today, selected, onSelect }: StripProps) {
  const byDate = new Map(days.map((d) => [d.date, d]));
  const dates = dateRange(from, to);
  const weeks = [dates.slice(0, Math.max(0, dates.length - 7)), dates.slice(-7)].filter(
    (w) => w.length > 0,
  );
  return (
    <div className={styles.strip}>
      {weeks.map((week, i) => (
        <div className={styles.week} key={week[0]}>
          <Bi
            t={WEEK_LABELS[weeks.length === 1 ? 1 : i]}
            inline
            className={styles.weekLabel}
          />
          <ul className={styles.cells}>
            {week.map((date) => (
              <Cell
                key={date}
                date={date}
                day={byDate.get(date)}
                today={today}
                selected={selected === date}
                onSelect={onSelect}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** Legend: every status with its icon, words and meaning. */
export function StatusLegend() {
  return (
    <ul className={styles.legend} aria-label="Status legend">
      {DAY_STATUSES.map((s) => (
        <li key={s} className={`st-${s}`}>
          <StatusIcon status={s} size={20} />
          <Bi hi={STATUS[s].hi} en={`${STATUS[s].en}: ${STATUS[s].meaningEn.toLowerCase()}`} />
        </li>
      ))}
    </ul>
  );
}
