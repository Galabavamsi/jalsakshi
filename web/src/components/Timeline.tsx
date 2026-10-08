import type { TicketEvent } from '../api/types';
import { cx } from '../lib/cx';
import { actorLabel, detailEntries, sortedEvents, type People } from '../lib/events';
import { dateTime } from '../lib/format';
import { TICKET_STATE, eventKey, eventLabel } from '../lib/labels';
import { Bi } from './Bi';
import { IconCall, IconCheck, IconDrop, IconShield, IconTicket, IconWrench } from './Icons';
import styles from './Timeline.module.css';

const KIND_ICON: Record<string, typeof IconDrop> = {
  opened: IconTicket,
  notified: IconCall,
  operator_fixed: IconWrench,
  verify_started: IconCall,
  verify_answer: IconDrop,
  reopened: IconTicket,
  closed_verified: IconCheck,
  close_denied: IconShield,
  escalated: IconShield,
  day_still_bad: IconDrop,
};

function tone(event: TicketEvent, key: string): string | undefined {
  if (key === 'close_denied' || key === 'day_still_bad') return styles.bad;
  if (event.from_state !== 'REOPENED' && event.to_state === 'REOPENED') return styles.bad;
  if (event.to_state === 'CLOSED_VERIFIED') return styles.verified;
  return undefined;
}

function Item({ event, people }: { event: TicketEvent; people: People }) {
  const key = eventKey(event.kind, event.detail);
  const Icon = KIND_ICON[key] ?? IconDrop;
  const when = dateTime(event.at);
  const who = actorLabel(event.actor, people);
  const details = detailEntries(event, people);
  return (
    <li className={cx(styles.item, tone(event, key))}>
      <span className={styles.marker} aria-hidden="true">
        <Icon size={20} />
      </span>
      <div className={styles.content}>
        <Bi t={eventLabel(key, event.to_state)} as="p" className={styles.what} />
        <p className={styles.meta}>
          <time dateTime={event.at}>
            <span lang="hi">{when.hi}</span> <span lang="en">({when.en})</span>
          </time>
          <span className={styles.who}>
            <span lang="hi">{who.hi}</span>
            {who.en !== who.hi && <span lang="en"> ({who.en})</span>}
          </span>
        </p>
        {event.from_state && event.to_state && event.from_state !== event.to_state && (
          <p className={styles.transition}>
            <span className="visually-hidden">State changed from </span>
            <span lang="hi">{TICKET_STATE[event.from_state].hi}</span>
            <span aria-hidden="true"> → </span>
            <span className="visually-hidden"> to </span>
            <span lang="hi">{TICKET_STATE[event.to_state].hi}</span>
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

/** A ticket's history, oldest first: what happened, who did it, when. */
export function Timeline({ events, people }: { events: TicketEvent[]; people: People }) {
  return (
    <ol className={styles.timeline}>
      {sortedEvents(events).map((event, i) => (
        <Item key={`${event.at}-${event.kind}-${i}`} event={event} people={people} />
      ))}
    </ol>
  );
}
