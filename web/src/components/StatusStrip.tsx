import type { DayStatus, IsoDate } from '../api/types';
import { DAY_STATUSES } from '../api/types';
import { stripCellLabel } from '../i18n/messages';
import { useT } from '../i18n/locale';
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
  { en: 'The 7 days before', hi: 'उससे पहले के 7 दिन' },
  { en: 'Last 7 days', hi: 'पिछले 7 दिन' },
];

function Cell({ date, day, today, selected, onSelect }: CellProps) {
  const t = useT();
  const isToday = date === today;
  const label = t(stripCellLabel, {
    date: t(shortDate(date)),
    status: day ? t(STATUS[day.status]) : null,
    answered: day?.counts.answered ?? 0,
    no: day?.counts.no ?? 0,
    partial: day?.counts.partial ?? 0,
    dirty: day?.counts.dirty ?? 0,
    today: isToday,
  });
  return (
    <li className={styles.slot}>
      <button
        type="button"
        className={cx(
          styles.cell,
          day ? `paint st-${day.status}` : cx('dry', styles.empty),
          selected && styles.selected,
          isToday && styles.today,
        )}
        aria-label={label}
        aria-pressed={onSelect && day ? selected : undefined}
        disabled={!onSelect || !day}
        onClick={() => onSelect?.(date)}
      >
        <span className={styles.when}>{isToday ? t({ en: 'Today', hi: 'आज' }) : t(weekdayName(date))}</span>
        <span className={styles.date}>{Number(date.slice(8, 10))}</span>
        {day ? <StatusIcon status={day.status} size={24} /> : <span className={styles.dash} aria-hidden="true" />}
        <span className={styles.word}>{day ? t(STATUS[day.status].short) : t({ en: 'No calls', hi: 'कॉल नहीं' })}</span>
      </button>
    </li>
  );
}

/** Fourteen days in two rows of seven; the bottom row is the last seven days. */
export function StatusStrip({ days, from, to, today, selected, onSelect }: StripProps) {
  const byDate = new Map(days.map((d) => [d.date, d]));
  const dates = dateRange(from, to);
  const weeks = [dates.slice(0, Math.max(0, dates.length - 7)), dates.slice(-7)].filter((w) => w.length > 0);
  return (
    <div className={styles.strip}>
      {weeks.map((week, i) => (
        <div className={styles.week} key={week[0]}>
          <Bi t={WEEK_LABELS[weeks.length === 1 ? 1 : i]} as="p" className={styles.weekLabel} />
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

/** The same fourteen days as a table: the screen-reader route and the precise view. */
export function StatusTable({ days, from, to, today }: Pick<StripProps, 'days' | 'from' | 'to' | 'today'>) {
  const t = useT();
  const byDate = new Map(days.map((d) => [d.date, d]));
  const dates = dateRange(from, to);
  return (
    <div className={styles.tableWrap}>
      <table className="data-table">
        <caption>
          {t({
            en: 'Day status and household answers, oldest first. Decided by rule, not by AI.',
            hi: 'दिन की स्थिति और घरों के जवाब, पुराने पहले। फ़ैसला नियम से, AI से नहीं।',
          })}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t({ en: 'Date', hi: 'तारीख़' })}</th>
            <th scope="col">{t({ en: 'Status', hi: 'स्थिति' })}</th>
            <th scope="col" className="n">
              {t({ en: 'Answered', hi: 'जवाब' })}
            </th>
            <th scope="col" className="n">
              {t({ en: 'Yes', hi: 'हाँ' })}
            </th>
            <th scope="col" className="n">
              {t({ en: 'No', hi: 'नहीं' })}
            </th>
            <th scope="col" className="n">
              {t({ en: 'Partial', hi: 'थोड़ा' })}
            </th>
            <th scope="col" className="n">
              {t({ en: 'Dirty', hi: 'गंदा' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {dates.map((date) => {
            const d = byDate.get(date);
            const when = `${t(weekdayName(date))} ${t(shortDate(date))}`;
            return (
              <tr key={date}>
                <th scope="row" className={styles.rowDate}>
                  {date === today ? `${t({ en: 'Today', hi: 'आज' })}, ${t(shortDate(date))}` : when}
                </th>
                <td>
                  {d ? (
                    <span className={cx(styles.tableStatus, `st-${d.status}`)}>
                      <StatusIcon status={d.status} size={18} />
                      {t(STATUS[d.status])}
                    </span>
                  ) : (
                    <span className={styles.tableNone}>{t({ en: 'No calls', hi: 'कॉल नहीं' })}</span>
                  )}
                </td>
                <td className="n">{d?.counts.answered ?? '–'}</td>
                <td className="n">{d?.counts.yes ?? '–'}</td>
                <td className="n">{d?.counts.no ?? '–'}</td>
                <td className="n">{d?.counts.partial ?? '–'}</td>
                <td className="n">{d?.counts.dirty ?? '–'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Legend: every status with its icon, word and meaning. */
export function StatusLegend() {
  const t = useT();
  return (
    <ul className={styles.legend} aria-label={t({ en: 'Status legend', hi: 'स्थिति का मतलब' })}>
      {DAY_STATUSES.map((s) => (
        <li key={s} className={`st-${s}`}>
          <span className={cx(styles.legendSwatch, 'paint', `st-${s}`)} aria-hidden="true">
            <StatusIcon status={s} size={16} />
          </span>
          <span>
            <strong className={styles.legendWord}>{t(STATUS[s])}</strong>
            <span className={styles.legendMeaning}>{t(STATUS[s].meaning)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
