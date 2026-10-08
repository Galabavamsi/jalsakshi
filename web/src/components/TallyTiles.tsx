import { Fragment } from 'react';
import type { DayStatusValue, Observed7d } from '../api/types';
import { useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { STATUS } from '../lib/labels';
import { tally } from '../lib/reliability';
import { StatusIcon } from './Icons';
import styles from './TallyTiles.module.css';

const COUNT_ORDER: DayStatusValue[] = ['NO_SUPPLY', 'DIRTY', 'PARTIAL', 'SUPPLIED', 'UNVERIFIED'];

/**
 * The last seven days as seven painted cells grouped by status (a tally, not a calendar), with
 * the counts written out beneath so colour is never the only carrier of meaning.
 */
export function TallyTiles({ observed }: { observed: Observed7d }) {
  const t = useT();
  const tiles = tally(observed);
  const noData = tiles.filter((s) => s === null).length;
  const counts = COUNT_ORDER.map((status) => ({ status, n: tiles.filter((s) => s === status).length })).filter(
    (c) => c.n > 0,
  );
  const parts = [
    ...counts.map(({ status, n }) => ({
      key: status,
      status,
      n,
      label: t(STATUS[status]).toLocaleLowerCase(),
    })),
    ...(noData > 0
      ? [{ key: 'none', status: null, n: noData, label: t({ en: 'no calls', hi: 'कॉल नहीं' }) }]
      : []),
  ];
  return (
    <div className={styles.wrap}>
      <ol className={styles.tiles} aria-hidden="true">
        {tiles.map((status, i) => (
          <li key={i} className={cx(styles.tile, status ? `paint st-${status}` : cx('dry', styles.none))}>
            {status ? (
              <>
                <StatusIcon status={status} size={20} />
                <span className={styles.word}>{t(STATUS[status].short)}</span>
              </>
            ) : (
              // A day with no calls: a dry outline with a dash, so it reads as "nothing heard",
              // not as a missing tile. The counts line below says "no calls" in words.
              <span className={styles.dash}>–</span>
            )}
          </li>
        ))}
      </ol>
      <p className={styles.counts}>
        <span className="visually-hidden">{t({ en: 'Last 7 days by status: ', hi: 'पिछले 7 दिन, स्थिति के हिसाब से: ' })}</span>
        {parts.map((p, i) => (
          <Fragment key={p.key}>
            {i > 0 && ', '}
            <span className={styles.count}>
              {p.status && <StatusIcon status={p.status} size={16} className={cx(styles.countIcon, `st-${p.status}`)} />}
              <strong className="num">{p.n}</strong> {p.label}
            </span>
          </Fragment>
        ))}
      </p>
    </div>
  );
}
