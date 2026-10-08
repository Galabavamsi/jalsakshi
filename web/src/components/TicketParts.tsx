import type { TicketState } from '../api/types';
import { confirmedText, verifiedStampLabel } from '../i18n/messages';
import { useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { shortDate, type Bilingual } from '../lib/format';
import { TICKET_STATE } from '../lib/labels';
import { istDate } from '../lib/time';
import { Bi } from './Bi';
import { IconCheck } from './Icons';
import { Wash } from './Wash';
import styles from './TicketParts.module.css';

const STEPS: Array<{ state: TicketState; short: Bilingual }> = [
  { state: 'OPEN', short: { en: 'Opened', hi: 'खुली' } },
  { state: 'ASSIGNED', short: { en: 'Assigned', hi: 'मित्र को' } },
  { state: 'OPERATOR_REPORTED_FIXED', short: { en: 'Says fixed', hi: 'ठीक बताया' } },
  { state: 'VERIFYING', short: { en: 'Checking', hi: 'पुष्टि' } },
  { state: 'CLOSED_VERIFIED', short: { en: 'Verified', hi: 'सत्यापित' } },
];

/** Where an off-path state sits on the happy path. */
function stepIndex(state: TicketState): number {
  if (state === 'REOPENED' || state === 'ESCALATED') return 1;
  return STEPS.findIndex((s) => s.state === state);
}

function toneOf(state: TicketState): string | undefined {
  if (state === 'CLOSED_VERIFIED') return styles.toneVerified;
  if (state === 'OPERATOR_REPORTED_FIXED' || state === 'VERIFYING') return styles.toneProgress;
  return styles.toneBad;
}

/** A ticket's state, printed: the system's word for where the repair is. */
export function TicketStateBadge({ state }: { state: TicketState }) {
  return (
    <span className={cx(styles.badge, toneOf(state))}>
      <Bi t={TICKET_STATE[state]} />
    </span>
  );
}

/** The five steps every repair must pass; households confirm the last one. */
export function TicketProgress({ state }: { state: TicketState }) {
  const t = useT();
  const current = stepIndex(state);
  const closed = state === 'CLOSED_VERIFIED';
  const offPath = state === 'REOPENED' || state === 'ESCALATED';
  return (
    <div className={styles.progressWrap}>
      <ol className={styles.progress} aria-label={t({ en: 'Repair progress', hi: 'मरम्मत कहाँ तक पहुँची' })}>
        {STEPS.map((step, i) => {
          const done = i < current || closed;
          const isCurrent = i === current && !closed;
          return (
            <li
              key={step.state}
              className={cx(
                styles.step,
                done && styles.done,
                isCurrent && styles.current,
                isCurrent && offPath && styles.currentBad,
              )}
              aria-current={i === current ? 'step' : undefined}
            >
              <span className={styles.dot} aria-hidden="true">
                {done && <IconCheck size={14} strokeWidth={3} />}
              </span>
              <Bi t={step.short} className={styles.stepLabel} />
              {(done || isCurrent) && (
                <span className="visually-hidden">
                  {done ? t({ en: ' (done)', hi: ' (हो गया)' }) : t({ en: ' (now)', hi: ' (अभी)' })}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {offPath && (
        <p className={styles.offPath}>
          <Bi t={TICKET_STATE[state]} />
        </p>
      )}
    </div>
  );
}

/**
 * The rubber stamp on a ticket that households confirmed: an oval with a double ring, landing
 * once when the page opens (the console's one orchestrated motion; off with reduced motion).
 */
export function VerifiedStamp({ at, seed }: { at: string; seed: string }) {
  const t = useT();
  const when = t(shortDate(istDate(new Date(at))));
  return (
    <div className={cx(styles.stampWrap, 'has-wash')}>
      <Wash seed={`${seed}:halo`} tone="supplied" strength="decor" fit="slice" className={styles.halo} />
      <div className={styles.stamp} role="img" aria-label={t(verifiedStampLabel, { when })}>
        <span className={styles.stampWords} aria-hidden="true">
          {t({ en: 'Verified by households', hi: 'घरों ने पुष्टि की' })}
        </span>
        <span className={styles.stampDate} aria-hidden="true">
          {when}
        </span>
      </div>
    </div>
  );
}

/**
 * Households that confirmed water is back, against the number needed to close (the quorum).
 * Each confirmation is a violet stamp; the ones still awaited are dashed rings.
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
  const t = useT();
  const slots = Math.max(needed, yes, 1);
  const text = t(confirmedText, { yes, needed });
  return (
    <div className={styles.confirmations}>
      <ol className={styles.slots} aria-hidden="true">
        {Array.from({ length: slots }, (_, i) => (
          <li key={i} className={i < yes ? styles.slotYes : styles.slotWait}>
            {i < yes ? <IconCheck size={22} strokeWidth={2.5} /> : null}
          </li>
        ))}
      </ol>
      {compact ? (
        <span className="visually-hidden">{text}</span>
      ) : (
        <p className={styles.confirmText}>{text}</p>
      )}
    </div>
  );
}
