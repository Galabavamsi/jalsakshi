import type { Village } from '../api/types';
import { useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import type { Bilingual } from '../lib/format';
import { SourceBadge } from './SourceBadge';
import styles from './RegisterSlip.module.css';

function yesNo(value: boolean | null | undefined): Bilingual {
  if (value === true) return { en: 'Yes', hi: 'हाँ' };
  if (value === false) return { en: 'No', hi: 'नहीं' };
  return { en: 'Not known', hi: 'पता नहीं' };
}

/**
 * The state's claim, printed on a ruled register slip: what JJM's Har Ghar Jal record says about
 * the village, with its source and freshness. Its deckled edge is the seam against the painted
 * household answers beside it.
 */
export function RegisterSlip({
  village,
  compact = false,
  gloss = false,
  deckle = true,
  headingLevel = 3,
  className,
}: {
  village: Village;
  /** One-line rows for the village page header. */
  compact?: boolean;
  /** Spell out "Har Ghar Jal (tap water in every home)" (once per page). */
  gloss?: boolean;
  deckle?: boolean;
  /** The slip's heading level in the page outline. */
  headingLevel?: 2 | 3;
  className?: string;
}) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3';
  const t = useT();
  const hgj = gloss
    ? t({ en: 'Har Ghar Jal (tap water in every home)', hi: 'हर घर जल (हर घर में नल का पानी)' })
    : t({ en: 'Har Ghar Jal', hi: 'हर घर जल' });
  return (
    <div
      className={cx('slip', !compact && 'slip-ruled', styles.slip, compact && styles.compact, deckle && styles.deckle, className)}
    >
      <Heading className={styles.title}>{t({ en: 'State record', hi: 'सरकारी रिकॉर्ड' })}</Heading>
      <dl className={styles.rows}>
        <div className={styles.row}>
          <dt>{hgj}</dt>
          <dd className={cx('slip-value', styles.value, village.claimed_hgj === true && styles.claimed)}>
            {t(yesNo(village.claimed_hgj))}
          </dd>
        </div>
        <div className={styles.row}>
          <dt>{t({ en: 'Gram Sabha certified', hi: 'ग्राम सभा का प्रमाणपत्र' })}</dt>
          <dd className={cx('slip-value', styles.value)}>{t(yesNo(village.hgj_certified))}</dd>
        </div>
      </dl>
      {village.claimed_source && <SourceBadge source={village.claimed_source} className={styles.source} />}
    </div>
  );
}
