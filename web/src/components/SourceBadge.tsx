import type { SourceTag } from '../api/types';
import { cx } from '../lib/cx';
import { dateTime, relative, shortDate } from '../lib/format';
import { FRESHNESS_LABEL } from '../lib/labels';
import { istDate } from '../lib/time';
import styles from './SourceBadge.module.css';

/**
 * Where a number came from and how fresh it is. Shown next to every number in the console.
 * Simulated and replayed data get a dashed, hatched badge so they never pass for live data.
 */
export function SourceBadge({ source }: { source: SourceTag }) {
  const fresh = FRESHNESS_LABEL[source.freshness];
  const asOf = source.observed_at ? shortDate(istDate(new Date(source.observed_at))) : null;
  const fetched = relative(source.fetched_at);
  const when = asOf
    ? { hi: `${asOf.hi} की स्थिति`, en: `as on ${asOf.en}` }
    : { hi: `${fetched.hi} लिया`, en: `fetched ${fetched.en}` };
  const title = `${source.source}. Freshness: ${fresh.en}. Fetched ${dateTime(source.fetched_at).en}.`;
  return (
    <span className={cx(styles.badge, styles[source.freshness])} title={title}>
      <span className={styles.mark} aria-hidden="true" />
      <span className={styles.text}>
        <span className={styles.source}>
          <span className="visually-hidden">Source: </span>
          {source.url ? (
            <a href={source.url} target="_blank" rel="noreferrer noopener">
              {source.source}
            </a>
          ) : (
            source.source
          )}
        </span>
        <span className={styles.meta}>
          <span lang="hi">{fresh.hi}</span> <span lang="en">({fresh.en})</span>,{' '}
          <span lang="hi">{when.hi}</span> <span lang="en">({when.en})</span>
        </span>
      </span>
    </span>
  );
}
