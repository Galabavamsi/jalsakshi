import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import type { PolicyDenied } from '../api/types';
import { isMock } from '../appConfig';
import { pickField, useLocale, useT } from '../i18n/locale';
import { clockTime } from '../lib/format';
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
  /** Move focus to the title when it appears (an answer to the person's action). */
  focusOnShow?: boolean;
  /** Extra actions, e.g. "Try again". */
  children?: ReactNode;
}

/**
 * A Cedar deny is the system speaking, so it is printed, never painted: a register slip with
 * what cannot happen yet, the rule's own reason, why the rule exists, what happens next, and
 * the policy id.
 */
export function PolicyDenial({ denied, onDismiss, progress, focusOnShow = true, children }: PolicyDenialProps) {
  const titleId = useId();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const { locale } = useLocale();
  const t = useT();
  const copy = policyCopy(denied.policy_id);
  const [decidedAt] = useState(() => new Date().toISOString());

  useEffect(() => {
    if (focusOnShow) titleRef.current?.focus();
  }, [focusOnShow, denied]);

  return (
    <section className={styles.panel} role="alert" aria-labelledby={titleId}>
      <header className={styles.head}>
        <span className={styles.seal} aria-hidden="true">
          <IconRule size={26} />
        </span>
        <h3 id={titleId} ref={titleRef} tabIndex={-1} className={styles.title}>
          {t(copy.title)}
        </h3>
      </header>

      <div className={styles.reason}>
        {progress && <Confirmations yes={progress.yes} needed={progress.needed} compact />}
        <p className={styles.reasonText} lang={locale}>
          {pickField(denied, 'reason', locale)}
        </p>
      </div>

      <dl className={styles.explain}>
        <div>
          <Bi as="dt" en="Why this rule" hi="यह नियम क्यों" />
          <Bi as="dd" t={copy.why} />
        </div>
        {copy.next && (
          <div>
            <Bi as="dt" en="What happens next" hi="आगे क्या होगा" />
            <Bi as="dd" t={copy.next} />
          </div>
        )}
      </dl>

      <footer className={styles.foot}>
        <p className={styles.decided}>
          <span className={styles.ruleId}>
            {t({ en: 'Cedar policy', hi: 'Cedar नियम' })} <code translate="no">{denied.policy_id}</code>
          </span>
          <span className="num">
            {t({ en: `Decided ${clockTime(decidedAt)} IST`, hi: `${clockTime(decidedAt)} बजे तय` })}
          </span>
          <Bi
            en="By a written rule, not by a person or an AI."
            hi="लिखे हुए नियम से, किसी व्यक्ति या AI से नहीं।"
          />
        </p>
        {isMock && (
          <p className={styles.demoNote}>
            <Bi en="Demo: a browser copy of this rule ran." hi="डेमो: ब्राउज़र में इसी नियम की नकल चली।" />
          </p>
        )}
        {(children || onDismiss) && (
          <div className={styles.actions}>
            {children}
            {onDismiss && (
              <button type="button" className="btn btn-quiet" onClick={onDismiss}>
                <Bi en="Dismiss" hi="ठीक है" />
              </button>
            )}
          </div>
        )}
      </footer>
    </section>
  );
}
