import type { IsoDate, TicketEvent } from '../api/types';
import { cx } from '../lib/cx';
import { actorLabel, detailEntries, sortedEvents, type People } from '../lib/events';
import { clockTime, dateTime, longDate, weekdayName } from '../lib/format';
import { TICKET_STATE, eventKey, eventLabel } from '../lib/labels';
import { istDate } from '../lib/time';
import { Bi } from './Bi';
import { IconCall, IconCheck, IconDrop, IconRule, IconTicket, IconWrench } from './Icons';
import styles from './Timeline.module.css';

const KIND_ICON: Record<string, typeof IconDrop> = {
  opened: IconTicket,
  notified: IconCall,
  operator_fixed: IconWrench,
  verify_started: IconCall,
  verify_answer: IconDrop,
  reopened: IconTicket,
  closed_verified: IconCheck,
  close_denied: IconRule,
  escalated: IconRule,
  day_still_bad: IconDrop,
};

function tone(event: TicketEvent, key: string): string | undefined {
  if (key === 'close_denied') return styles.rule;
  if (key === 'day_still_bad') return styles.bad;
  if (event.from_state !== 'REOPENED' && event.to_state === 'REOPENED') return styles.bad;
  if (event.to_state === 'CLOSED_VERIFIED' || key === 'verify_answer') return styles.verified;
  return undefined;
}

function Item({ event, people }: { event: TicketEvent; people: People }) {
  const key = eventKey(event.kind, event.detail);
  const Icon = KIND_ICON[key] ?? IconDrop;
  const who = actorLabel(event.actor, people);
  const details = detailEntries(event, people);
  const moved = event.from_state && event.to_state && event.from_state !== event.to_state;
  return (
    <li className={cx(styles.item, tone(event, key))}>
      <time className={styles.time} dateTime={event.at} title={dateTime(event.at).en}>
        {clockTime(event.at)}
      </time>
      <span className={styles.marker} aria-hidden="true">
        <Icon size={20} />
      </span>
      <div className={styles.content}>
        <Bi t={eventLabel(key, event.to_state)} as="p" className={styles.what} />
        <p className={styles.who}>
          <span lang="hi">{who.hi}</span>
          {who.en !== who.hi && <span lang="en"> ({who.en})</span>}
        </p>
        {moved && event.from_state && event.to_state && (
          <p className={styles.transition}>
            <span className="visually-hidden">State changed from </span>
            <span className={styles.from} lang="hi">
              {TICKET_STATE[event.from_state].hi}
            </span>
            <span className={styles.arrow} aria-hidden="true">
              →
            </span>
            <span className="visually-hidden"> to </span>
            <span className={styles.to}>
              <Bi t={TICKET_STATE[event.to_state]} inline />
            </span>
          </p>
        )}
        {details.length > 0 && (
          <dl className={styles.details}>
            {details.map((d) => (
              <div key={d.label.en}>
                <dt>
                  <span lang="hi">{d.label.hi}</span>
                  {d.label.en !== d.label.hi && <span lang="en"> ({d.label.en})</span>}
                </dt>
                <dd>{d.value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </li>
  );
}

function byDay(events: TicketEvent[]): Array<[IsoDate, TicketEvent[]]> {
  const days = new Map<IsoDate, TicketEvent[]>();
  for (const e of sortedEvents(events)) {
    const day = istDate(new Date(e.at));
    days.set(day, [...(days.get(day) ?? []), e]);
  }
  return [...days.entries()];
}

/** A ticket's history, oldest first and grouped by day: what happened, who did it, when (IST). */
export function Timeline({ events, people }: { events: TicketEvent[]; people: People }) {
  return (
    <ol className={styles.days}>
      {byDay(events).map(([day, list]) => {
        const d = longDate(day);
        const w = weekdayName(day);
        return (
          <li key={day} className={styles.day}>
            <h3 className={styles.dayTitle}>
              <span lang="hi">
                {w.hi}, {d.hi}
              </span>{' '}
              <span lang="en">
                ({w.en}, {d.en})
              </span>
            </h3>
            <ol className={styles.timeline}>
              {list.map((event, i) => (
                <Item key={`${event.at}-${event.kind}-${i}`} event={event} people={people} />
              ))}
            </ol>
          </li>
        );
      })}
    </ol>
  );
}
