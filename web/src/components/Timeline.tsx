import { useRef } from 'react';
import type { IsoDate, TicketEvent } from '../api/types';
import { useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { actorLabel, detailEntries, sortedEvents, viaLabel, type People } from '../lib/events';
import { clockTime, dateTime, longDate, weekdayName } from '../lib/format';
import { TICKET_STATE, eventKey, eventLabel } from '../lib/labels';
import { istDate } from '../lib/time';
import { IconCall, IconCheck, IconDrop, IconNoSupply, IconRule, IconTicket, IconWrench } from './Icons';
import { LangRuns } from './LangRuns';
import styles from './Timeline.module.css';

const KIND_ICON: Record<string, typeof IconDrop> = {
  opened: IconTicket,
  notified: IconCall,
  operator_fixed: IconWrench,
  verify_started: IconCall,
  verify_answer: IconCheck,
  reopened: IconNoSupply,
  closed_verified: IconCheck,
  close_denied: IconRule,
  escalated: IconRule,
  day_still_bad: IconDrop,
};

type Tone = 'heardYes' | 'heardNo' | 'rule' | 'bad' | 'system';

/** Paint means people: household answers are painted; system and Cedar events are printed. */
function toneOf(event: TicketEvent, key: string): Tone {
  if (key === 'close_denied') return 'rule';
  if (key === 'verify_answer') return event.detail?.water === 'NO' ? 'heardNo' : 'heardYes';
  if (key === 'closed_verified' || event.to_state === 'CLOSED_VERIFIED') return 'heardYes';
  if (key === 'reopened') return 'heardNo';
  if (key === 'day_still_bad' || key === 'escalated') return 'bad';
  return 'system';
}

const eventId = (e: TicketEvent, i: number) => `${e.at}|${e.kind}|${i}`;

function Item({ event, people, fresh }: { event: TicketEvent; people: People; fresh: boolean }) {
  const t = useT();
  const key = eventKey(event.kind, event.detail);
  const tone = toneOf(event, key);
  const Icon = KIND_ICON[key] ?? IconDrop;
  const who = t(actorLabel(event.actor, people));
  const via = viaLabel(event);
  const details = detailEntries(event, people);
  const moved = event.from_state && event.to_state && event.from_state !== event.to_state;
  const painted = tone === 'heardYes' || tone === 'heardNo';
  return (
    <li className={cx(styles.item, styles[tone], painted && styles.painted, fresh && 'enter')}>
      <time className={styles.time} dateTime={event.at} title={t(dateTime(event.at))}>
        {clockTime(event.at)}
      </time>
      <span className={cx(styles.marker, painted ? styles.markerPaint : styles.markerPrint)} aria-hidden="true">
        <Icon size={18} strokeWidth={2.25} />
      </span>
      <div className={styles.content}>
        <p className={styles.what}>{t(eventLabel(key, event.to_state))}</p>
        <p className={styles.who}>
          <LangRuns text={who} />
          {via && <>, {t(via)}</>}
        </p>
        {moved && event.from_state && event.to_state && (
          <p className={styles.transition}>
            <span className="visually-hidden">{t({ en: 'State changed from ', hi: 'स्थिति बदली: ' })}</span>
            <span className={styles.from}>{t(TICKET_STATE[event.from_state])}</span>
            <span className={styles.arrow} aria-hidden="true">
              →
            </span>
            <span className="visually-hidden">{t({ en: ' to ', hi: ' से ' })}</span>
            <span className={styles.to}>{t(TICKET_STATE[event.to_state])}</span>
          </p>
        )}
        {details.length > 0 && (
          <dl className={styles.details}>
            {details.map((d) => (
              <div key={d.label.en}>
                <dt>{t(d.label)}</dt>
                <dd>
                  <LangRuns text={t(d.value)} />
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </li>
  );
}

function byDay(events: TicketEvent[]): Array<[IsoDate, Array<{ event: TicketEvent; id: string }>]> {
  const days = new Map<IsoDate, Array<{ event: TicketEvent; id: string }>>();
  sortedEvents(events).forEach((event, i) => {
    const day = istDate(new Date(event.at));
    days.set(day, [...(days.get(day) ?? []), { event, id: eventId(event, i) }]);
  });
  return [...days.entries()];
}

/** A ticket's history, oldest first and grouped by day: what happened, who did it, when (IST). */
export function Timeline({ events, people }: { events: TicketEvent[]; people: People }) {
  const t = useT();
  const groups = byDay(events);
  // Rows already on screen when the page opened do not animate; rows added later fade in.
  const seen = useRef<Set<string> | null>(null);
  if (seen.current === null) seen.current = new Set(groups.flatMap(([, list]) => list.map((x) => x.id)));
  const initial = seen.current;
  return (
    <ol className={styles.days}>
      {groups.map(([day, list]) => (
        <li key={day} className={styles.day}>
          <h3 className={styles.dayTitle}>
            {t(weekdayName(day))}, {t(longDate(day))}
          </h3>
          <ol className={styles.timeline}>
            {list.map(({ event, id }) => (
              <Item key={id} event={event} people={people} fresh={!initial.has(id)} />
            ))}
          </ol>
        </li>
      ))}
    </ol>
  );
}
