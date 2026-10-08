import { useId, type ReactNode } from 'react';
import type { PolicyDenied } from '../api/types';
import { isMock } from '../appConfig';
import { policyCopy } from '../lib/policy';
import { Bi } from './Bi';
import { IconRule } from './Icons';
import { Confirmations } from './TicketParts';
import styles from './PolicyDenial.module.css';

interface PolicyDenialProps {
  denied: PolicyDenied;
  onDismiss?: () => void;
  /** For verify-needs-quorum: confirmations so far against the number needed. */
  progress?: { yes: number; needed: number } | null;
  /** Extra actions, e.g. "Try again". */
  children?: ReactNode;
}

/**
 * A Cedar deny, shown as a notice rather than an error: what cannot happen yet, the rule's own
 * reason in Hindi and English, why the rule exists, what happens next, and the rule's id.
 */
export function PolicyDenial({ denied, onDismiss, progress, children }: PolicyDenialProps) {
  const titleId = useId();
  const copy = policyCopy(denied.policy_id);
  return (
    <section className={styles.panel} role="alert" aria-labelledby={titleId}>
      <header className={styles.head}>
        <span className={styles.seal} aria-hidden="true">
          <IconRule size={30} />
        </span>
        <Bi as="h3" id={titleId} t={copy.title} className={styles.title} />
      </header>

      <div className={styles.reason}>
        {progress && <Confirmations yes={progress.yes} needed={progress.needed} compact />}
        <div className={styles.reasonText}>
          <p className={styles.reasonHi} lang="hi">
            {denied.reason_hi}
          </p>
          <p className={styles.reasonEn} lang="en">
            {denied.reason_en}
          </p>
        </div>
      </div>

      <dl className={styles.explain}>
        <div>
          <Bi as="dt" hi="यह नियम क्यों" en="Why this rule" />
          <Bi as="dd" t={copy.why} />
        </div>
        {copy.next && (
          <div>
            <Bi as="dt" hi="आगे क्या होगा" en="What happens next" />
            <Bi as="dd" t={copy.next} />
          </div>
        )}
      </dl>

      <footer className={styles.foot}>
        <p className={styles.decided}>
          <span className={styles.ruleId}>
            <span lang="en">Cedar</span> <code>{denied.policy_id}</code>
          </span>
          <Bi
            hi="यह फ़ैसला लिखे हुए नियम से हुआ, किसी व्यक्ति या AI से नहीं।"
            en="Decided by a written rule, not by a person or an AI."
          />
        </p>
        {isMock && (
          <p className={styles.demoNote}>
            <Bi
              inline
              hi="डेमो: ब्राउज़र में इसी नियम की नकल चली"
              en="Demo: a browser copy of this rule ran"
            />
          </p>
        )}
        {(children || onDismiss) && (
          <div className={styles.actions}>
            {children}
            {onDismiss && (
              <button type="button" className="btn btn-quiet" onClick={onDismiss}>
                <Bi hi="समझ गए" en="Understood" />
              </button>
            )}
          </div>
        )}
      </footer>
    </section>
  );
}
