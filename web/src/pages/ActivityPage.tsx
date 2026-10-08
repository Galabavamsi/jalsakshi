import { useCallback, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../api/context';
import type { ActivityItem, Village } from '../api/types';
import { Bi } from '../components/Bi';
import { IconCall, IconDoc, IconDrop, IconPlay, IconPulse, IconRule, IconTicket, StatusIcon } from '../components/Icons';
import { Empty, ErrorNote, Loading } from '../components/PageState';
import { useAsync } from '../hooks/useAsync';
import { usePolling } from '../hooks/usePolling';
import { refreshEvery } from '../i18n/messages';
import { pickField, useLocale, useT } from '../i18n/locale';
import { activityPolicyId, activityStatus, isPolicyItem, mergeActivity, newestAt } from '../lib/activity';
import { cx } from '../lib/cx';
import { clockTime, shortDate, weekdayName } from '../lib/format';
import { villageLabel } from '../lib/places';
import { istDate } from '../lib/time';
import styles from './ActivityPage.module.css';

const POLL_MS = 5000;

function iconFor(kind: string) {
  const k = kind.toLowerCase();
  if (k.includes('policy') || k.includes('denied')) return IconRule;
  if (k.includes('run')) return IconPlay;
  if (k.includes('call') || k.includes('checkin')) return IconCall;
  if (k.includes('ticket')) return IconTicket;
  if (k.includes('day') || k.includes('status')) return IconDrop;
  if (k.includes('brief') || k.includes('evidence')) return IconDoc;
  return IconPulse;
}

/** Households' answers get a painted status dot; Cedar decisions a printed square; the rest a quiet mark. */
function Marker({ item }: { item: ActivityItem }) {
  const status = activityStatus(item);
  if (status) {
    return (
      <span className={cx(styles.marker, styles.markerPaint, 'paint paint-flat', `st-${status}`)} aria-hidden="true">
        <StatusIcon status={status} size={18} />
      </span>
    );
  }
  const Icon = iconFor(item.kind);
  return (
    <span
      className={cx(styles.marker, styles.markerPrint, isPolicyItem(item) && styles.markerRule)}
      aria-hidden="true"
    >
      <Icon size={18} />
    </span>
  );
}

function Entry({ item, village, fresh }: { item: ActivityItem; village?: Village; fresh: boolean }) {
  const { locale } = useLocale();
  const policyId = activityPolicyId(item);
  return (
    <li className={cx(styles.item, isPolicyItem(item) && styles.policy, fresh && 'enter')}>
      <time className={styles.time} dateTime={item.at}>
        {clockTime(item.at)}
      </time>
      <Marker item={item} />
      <div className={styles.body}>
        <p className={styles.text} lang={locale}>
          {pickField(item, 'text', locale)}
        </p>
        {(item.village_id || policyId) && (
          <p className={styles.meta}>
            {item.village_id && (
              <Link to={`/villages/${encodeURIComponent(item.village_id)}`} className={styles.village}>
                {village ? villageLabel(village, locale) : item.village_id}
              </Link>
            )}
            {policyId && (
              <span className={styles.policyId}>
                Cedar <code translate="no">{policyId}</code>
              </span>
            )}
          </p>
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

/** Live feed of calls, statuses, tickets and rule decisions, polled every few seconds. */
export function ActivityPage() {
  const api = useApi();
  const t = useT();
  const villages = useAsync(() => api.listVillages(), 'villages');
  const byId = new Map(villages.data?.map((v) => [v.village.id, v.village]) ?? []);
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
  const isFresh = (item: ActivityItem) => baseline.current !== null && Date.parse(item.at) > baseline.current;
  const today = istDate(new Date());

  return (
    <div className="page">
      <header className={styles.header}>
        <Bi as="h1" en="Activity" hi="गतिविधि" className="page-title" />
        <Bi
          as="p"
          en="Calls, day statuses, repair tickets and rule decisions, newest first, as they happen."
          hi="कॉल, दिन की स्थिति, शिकायतें और नियमों के फ़ैसले, नए पहले, जैसे-जैसे होते हैं।"
          className={styles.lede}
        />
        <div className={styles.liveRow}>
          <p className={cx(styles.live, paused && styles.paused)} role="status">
            <span className={styles.dot} aria-hidden="true" />
            {paused
              ? t({ en: 'Paused. New rows will not appear until you resume.', hi: 'रुका हुआ। फिर चालू करने तक नई जानकारी नहीं आएगी।' })
              : t(refreshEvery, { seconds: POLL_MS / 1000 })}
          </p>
          <button type="button" className="btn btn-quiet" onClick={() => setPaused(!paused)}>
            <Bi en={paused ? 'Resume' : 'Pause'} hi={paused ? 'फिर चालू करें' : 'रोकें'} />
          </button>
        </div>
      </header>
      {!loaded && !error && <Loading />}
      {error ? <ErrorNote error={error} onRetry={poll} /> : null}
      {loaded && items.length === 0 && (
        <Empty
          text={{
            en: 'Nothing yet. Calls, statuses and tickets appear here as they happen. Start a call from the phone simulator to see one.',
            hi: 'अभी कोई गतिविधि नहीं। जाँच कॉल चलने पर यहाँ दिखेगी। देखने के लिए फ़ोन सिम्युलेटर से एक कॉल करें।',
          }}
        >
          <Link to="/simulator" className="btn btn-secondary">
            <Bi en="Open the phone simulator" hi="फ़ोन सिम्युलेटर खोलें" />
          </Link>
        </Empty>
      )}
      {groupByDay(items).map(([day, dayItems]) => {
        const label = day === today ? t({ en: 'Today', hi: 'आज' }) : `${t(weekdayName(day))}, ${t(shortDate(day))}`;
        return (
          <section key={day} className={styles.day} aria-label={label}>
            <h2 className={styles.dayTitle}>{label}</h2>
            <ol className={styles.list} role={day === today ? 'log' : undefined}>
              {dayItems.map((item) => (
                <Entry
                  key={`${item.at}|${item.kind}|${item.text_en}`}
                  item={item}
                  village={item.village_id ? byId.get(item.village_id) : undefined}
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
