import type { Observed7d } from '../api/types';
import { cx } from '../lib/cx';
import { STATUS } from '../lib/labels';
import { tally } from '../lib/reliability';
import { StatusIcon } from './Icons';
import styles from './TallyTiles.module.css';

/**
 * The last seven days as seven tiles grouped by status (a tally, not a calendar).
 * Screen readers get the counts as a sentence.
 */
export function TallyTiles({ observed }: { observed: Observed7d }) {
  const tiles = tally(observed);
  const summary =
    `${observed.supplied} supplied, ${observed.partial} partial, ${observed.dirty} dirty, ` +
    `${observed.no_supply} no supply, ${observed.unverified} unverified, ` +
    `${tiles.filter((t) => t === null).length} without data.`;
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
      <p className="visually-hidden">Last 7 days: {summary}</p>
    </div>
  );
}
