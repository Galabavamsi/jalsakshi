import type { DayStatusValue, Observed7d } from '../api/types';
import { cx } from '../lib/cx';
import { STATUS } from '../lib/labels';
import { tally } from '../lib/reliability';
import { StatusIcon } from './Icons';
import styles from './TallyTiles.module.css';

const COUNT_ORDER: DayStatusValue[] = ['SUPPLIED', 'PARTIAL', 'DIRTY', 'NO_SUPPLY', 'UNVERIFIED'];

/**
 * The last seven days as seven tiles grouped by status (a tally, not a calendar), with the
 * counts written out beneath so colour is never the only carrier of meaning.
 */
export function TallyTiles({ observed }: { observed: Observed7d }) {
  const tiles = tally(observed);
  const noData = tiles.filter((t) => t === null).length;
  const counts = COUNT_ORDER.map((status) => ({ status, n: tiles.filter((t) => t === status).length }))
    .filter((c) => c.n > 0);
  return (
    <div className={styles.wrap}>
      <ul className={styles.tiles} aria-hidden="true">
        {tiles.map((status, i) => (
          <li
            key={i}
            className={cx(styles.tile, status ? `st-${status}` : styles.none)}
            title={status ? STATUS[status].en : 'No data'}
          >
            {status ? <StatusIcon status={status} size={20} /> : null}
          </li>
        ))}
      </ul>
      <ul className={styles.counts} aria-label="Last 7 days by status">
        {counts.map(({ status, n }) => (
          <li key={status} className={`st-${status}`}>
            <strong className="num">{n}</strong> <span lang="hi">{STATUS[status].hi}</span>{' '}
            <span lang="en">({STATUS[status].en.toLowerCase()})</span>
          </li>
        ))}
        {noData > 0 && (
          <li className={styles.noData}>
            <strong className="num">{noData}</strong> <span lang="hi">कोई आँकड़ा नहीं</span>{' '}
            <span lang="en">(no data)</span>
          </li>
        )}
      </ul>
    </div>
  );
}
