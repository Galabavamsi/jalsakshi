import type { TicketState } from '../api/types';
import { cx } from '../lib/cx';
import { dateTime, type Bilingual } from '../lib/format';
import { TICKET_STATE } from '../lib/labels';
import { Bi } from './Bi';
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
