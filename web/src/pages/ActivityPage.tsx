import { useCallback, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import type { ActivityItem } from '../api/types';
import { Bi } from '../components/Bi';
import {
  IconCall,
  IconDoc,
  IconDrop,
  IconPlay,
  IconPulse,
  IconShield,
  IconTicket,
} from '../components/Icons';
import { Empty, ErrorNote, Loading } from '../components/PageState';
import { useAsync } from '../hooks/useAsync';
import { usePolling } from '../hooks/usePolling';
import { mergeActivity, newestAt } from '../lib/activity';
import { cx } from '../lib/cx';
import { clockTime, shortDate } from '../lib/format';
import { istDate } from '../lib/time';
import styles from './ActivityPage.module.css';

const POLL_MS = 5000;

function iconFor(kind: string) {
  const k = kind.toLowerCase();
  if (k.includes('policy') || k.includes('denied')) return IconShield;
  if (k.includes('run')) return IconPlay;
  if (k.includes('call') || k.includes('checkin')) return IconCall;
  if (k.includes('ticket')) return IconTicket;
  if (k.includes('day') || k.includes('status')) return IconDrop;
  if (k.includes('brief') || k.includes('evidence')) return IconDoc;
  return IconPulse;
}

function toneFor(kind: string): string | undefined {
  const k = kind.toLowerCase();
  if (k.includes('policy') || k.includes('denied')) return styles.policy;
  if (k.includes('ticket')) return styles.ticket;
  return undefined;
}

function Entry({ item, name, fresh }: { item: ActivityItem; name?: string; fresh: boolean }) {
  const Icon = iconFor(item.kind);
  return (
    <li className={cx(styles.item, toneFor(item.kind), fresh && styles.fresh)}>
      <time className={styles.time} dateTime={item.at}>
        {clockTime(item.at)}
      </time>
      <span className={styles.icon} aria-hidden="true">
        <Icon size={20} />
      </span>
      <div className={styles.body}>
        <p className={styles.textHi} lang="hi">
          {item.text_hi}
        </p>
        <p className={styles.textEn} lang="en">
          {item.text_en}
        </p>
        {item.village_id && (
          <Link to={`/villages/${encodeURIComponent(item.village_id)}`} className={styles.village}>
            {name ?? item.village_id}
          </Link>
        )}
      </div>
    </li>
  );
}

function groupByDay(items: ActivityItem[]): Array<[string, ActivityItem[]]> {
  const groups = new Map<string, ActivityItem[]>();
  for (const item of items) {
    const day = istDate(new Date(item.at));
    groups.set(day, [...(groups.get(day) ?? []), item]);
  }
  return [...groups.entries()];
}

/** Live feed of calls, statuses, tickets and policy decisions, polled every few seconds. */
export function ActivityPage() {
  const api = useApi();
  const villages = useAsync(() => api.listVillages(), 'villages');
  const names = new Map(villages.data?.map((v) => [v.village.id, v.village.name]) ?? []);
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [paused, setPaused] = useState(false);
  const baseline = useRef<number | null>(null);
  const inFlight = useRef(false);
  const cursor = useRef<string | undefined>(undefined);

  const poll = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    api
      .getActivity(cursor.current)
      .then((incoming) => {
        const previous = cursor.current ? [{ at: cursor.current }] : [];
        const newest = newestAt([...incoming, ...previous]);
        cursor.current = newest;
        if (baseline.current === null) baseline.current = newest ? Date.parse(newest) : 0;
        setItems((current) => mergeActivity(current, incoming));
        setError(null);
        setLoaded(true);
      })
      .catch((e: unknown) => setError(e))
      .finally(() => {
        inFlight.current = false;
      });
  }, [api]);

  usePolling(poll, POLL_MS, !paused);
  const isFresh = (item: ActivityItem) =>
    baseline.current !== null && Date.parse(item.at) > baseline.current;
  const today = istDate(new Date());

  return (
    <div className="page">
      <header className={styles.header}>
        <Bi as="h1" hi="गतिविधि" en="Activity" className={styles.title} />
        <div className={styles.liveRow}>
          <p className={cx(styles.live, paused && styles.paused)} role="status">
            <span className={styles.dot} aria-hidden="true" />
            <Bi
              inline
              hi={paused ? 'रुका हुआ' : `हर ${POLL_MS / 1000} सेकंड में नई जानकारी`}
              en={paused ? 'Paused' : `Updates every ${POLL_MS / 1000} seconds`}
            />
          </p>
          <button type="button" className="btn btn-quiet" onClick={() => setPaused(!paused)}>
            <Bi hi={paused ? 'फिर चालू करें' : 'रोकें'} en={paused ? 'Resume' : 'Pause'} />
          </button>
        </div>
      </header>
      {!loaded && !error && <Loading />}
      {error ? <ErrorNote error={error} onRetry={poll} /> : null}
      {loaded && items.length === 0 && (
        <Empty
          text={{
            hi: 'अभी कोई गतिविधि नहीं। जाँच कॉल चलने पर यहाँ दिखेगी।',
            en: 'Nothing yet. Calls, statuses and tickets appear here as they happen.',
          }}
        />
      )}
      {groupByDay(items).map(([day, dayItems]) => {
        const d = shortDate(day);
        return (
          <section key={day} className={styles.day} aria-label={d.en}>
            <Bi as="h2" hi={day === today ? 'आज' : d.hi} en={day === today ? 'Today' : d.en} className={styles.dayTitle} />
            <ol className={styles.list} role={day === today ? 'log' : undefined}>
              {dayItems.map((item) => (
                <Entry
                  key={`${item.at}|${item.kind}|${item.text_en}`}
                  item={item}
                  name={item.village_id ? names.get(item.village_id) : undefined}
                  fresh={isFresh(item)}
                />
              ))}
            </ol>
          </section>
        );
      })}
    </div>
  );
}
