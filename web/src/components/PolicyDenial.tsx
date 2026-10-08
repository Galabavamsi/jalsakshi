import type { PolicyDenied } from '../api/types';
import { Bi } from './Bi';
import { IconShield } from './Icons';
import styles from './PolicyDenial.module.css';

/** A Cedar deny, shown as the rule's own words in Hindi and English plus the policy id. */
export function PolicyDenial({ denied, onDismiss }: { denied: PolicyDenied; onDismiss?: () => void }) {
  return (
    <section className={styles.panel} role="alert" aria-labelledby="policy-denial-title">
      <IconShield className={styles.icon} size={36} />
      <div className={styles.body}>
        <Bi
          as="h3"
          id="policy-denial-title"
          hi="नियम ने रोका"
          en="Blocked by policy"
          className={styles.title}
        />
        <p className={styles.reasonHi} lang="hi">
          {denied.reason_hi}
        </p>
        <p className={styles.reasonEn} lang="en">
          {denied.reason_en}
        </p>
        <p className={styles.policy}>
          <span lang="hi">Cedar नियम</span> <span lang="en">(policy)</span>:{' '}
          <code>{denied.policy_id}</code>
        </p>
      </div>
      {onDismiss && (
        <button type="button" className="btn btn-quiet" onClick={onDismiss}>
          <Bi hi="ठीक है" en="Dismiss" />
        </button>
      )}
    </section>
  );
}
