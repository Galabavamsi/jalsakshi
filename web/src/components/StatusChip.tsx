import type { DayStatusValue } from '../api/types';
import { cx } from '../lib/cx';
import { STATUS } from '../lib/labels';
import { Bi } from './Bi';
import { StatusIcon } from './Icons';
import styles from './StatusChip.module.css';

const ICON_SIZE = { s: 18, m: 22, l: 28 } as const;

/** A day status as a painted chip: colour, icon and words together. */
export function StatusChip({ status, size = 'm' }: { status: DayStatusValue; size?: 's' | 'm' | 'l' }) {
  return (
    <span className={cx(styles.chip, size !== 'm' && styles[size], 'paint paint-flat', `st-${status}`)}>
      <StatusIcon status={status} size={ICON_SIZE[size]} />
      <Bi t={STATUS[status]} />
    </span>
  );
}
