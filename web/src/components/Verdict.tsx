import { verdictText } from '../i18n/messages';
import { useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import type { Verdict as VerdictValue } from '../lib/verdict';
import { IconCheck, IconFlag, IconPulse } from './Icons';
import styles from './Verdict.module.css';

const ICON = { gap: IconFlag, agree: IconCheck, plain: IconPulse, silent: IconPulse } as const;

/** One sentence: does what households said agree with the state record? (lib/verdict.ts) */
export function Verdict({
  verdict,
  checkinTime,
  className,
}: {
  verdict: VerdictValue;
  checkinTime: string;
  className?: string;
}) {
  const t = useT();
  const Icon = ICON[verdict.kind];
  return (
    <p className={cx(styles.verdict, styles[verdict.kind], className)}>
      <Icon size={24} className={styles.icon} />
      <span>{t(verdictText, { ...verdict, checkinTime })}</span>
    </p>
  );
}
