import type { TicketState } from '../api/types';
import { cx } from '../lib/cx';
import { dateTime, type Bilingual } from '../lib/format';
import { TICKET_STATE } from '../lib/labels';
import { Bi } from './Bi';
import { IconCheck } from './Icons';
import styles from './TicketParts.module.css';

const STEPS: Array<{ state: TicketState; short: Bilingual }> = [
  { state: 'OPEN', short: { hi: 'खुली', en: 'Opened' } },
  { state: 'ASSIGNED', short: { hi: 'मित्र को', en: 'Assigned' } },
  { state: 'OPERATOR_REPORTED_FIXED', short: { hi: 'ठीक बताया', en: 'Says fixed' } },
  { state: 'VERIFYING', short: { hi: 'पुष्टि', en: 'Checking' } },
  { state: 'CLOSED_VERIFIED', short: { hi: 'सत्यापित', en: 'Verified' } },
];

/** Where an off-path state sits on the happy path. */
function stepIndex(state: TicketState): number {
  if (state === 'REOPENED' || state === 'ESCALATED') return 1;
  return STEPS.findIndex((s) => s.state === state);
}

function toneOf(state: TicketState): string | undefined {
  if (state === 'CLOSED_VERIFIED') return styles.toneVerified;
  if (state === 'REOPENED' || state === 'ESCALATED') return styles.toneBad;
  return undefined;
}

export function TicketStateBadge({ state }: { state: TicketState }) {
  return (
    <span className={cx(styles.badge, toneOf(state))}>
      <Bi t={TICKET_STATE[state]} />
    </span>
  );
}

/** The five steps every repair must pass; households confirm the last one. */
export function TicketProgress({ state }: { state: TicketState }) {
  const current = stepIndex(state);
  const offPath = state === 'REOPENED' || state === 'ESCALATED';
  return (
    <div className={styles.progressWrap}>
      <ol className={styles.progress} aria-label="Repair progress">
        {STEPS.map((step, i) => (
          <li
            key={step.state}
            className={cx(
              styles.step,
              i < current && styles.done,
              i === current && styles.current,
              i === current && offPath && styles.currentBad,
            )}
            aria-current={i === current ? 'step' : undefined}
          >
            <span className={styles.dot} aria-hidden="true" />
            <Bi t={step.short} className={styles.stepLabel} />
          </li>
        ))}
      </ol>
      {offPath && (
        <p className={styles.offPath}>
          <Bi t={TICKET_STATE[state]} inline />
        </p>
      )}
    </div>
  );
}

/** The rubber stamp on a ticket that households confirmed. */
export function VerifiedStamp({ at }: { at: string }) {
  const when = dateTime(at);
  return (
    <div className={styles.stamp} role="img" aria-label={`Verified by households on ${when.en}`}>
      <span className={styles.stampHi} lang="hi">
        सत्यापित
      </span>
      <span className={styles.stampSub} lang="hi">
        घरों की पुष्टि से बंद
      </span>
      <span className={styles.stampEn} lang="en">
        Closed on households&rsquo; word
      </span>
      <span className={styles.stampDate}>{when.hi}</span>
    </div>
  );
}

function confirmedText(yes: number, needed: number): Bilingual {
  if (yes === 0) {
    return {
      hi: `अभी किसी घर ने पुष्टि नहीं की। ${needed} घरों की "हाँ" ज़रूरी है।`,
      en: `No household has confirmed yet. ${needed} need to say yes.`,
    };
  }
  return {
    hi: `ज़रूरी ${needed} में से ${yes} ${yes === 1 ? 'घर ने' : 'घरों ने'} पुष्टि की कि पानी लौट आया`,
    en: `${yes} of the ${needed} households needed have confirmed water is back`,
  };
}

/**
 * Households that confirmed water is back, against the number needed to close (the quorum).
 * Each confirmation is a filled stamp; the ones still awaited are dashed.
 */
export function Confirmations({
  yes,
  needed,
  compact = false,
}: {
  yes: number;
  needed: number;
  /** Stamps only, for places where the same words are already on screen. */
  compact?: boolean;
}) {
  const slots = Math.max(needed, yes, 1);
  const text = confirmedText(yes, needed);
  return (
    <div className={styles.confirmations}>
      <ol className={styles.slots} aria-hidden="true">
        {Array.from({ length: slots }, (_, i) => (
          <li key={i} className={i < yes ? styles.slotYes : styles.slotWait}>
            {i < yes ? <IconCheck size={22} /> : null}
          </li>
        ))}
      </ol>
      {compact ? (
        <span className="visually-hidden">{text.en}</span>
      ) : (
        <Bi t={text} className={styles.confirmText} />
      )}
    </div>
  );
}
