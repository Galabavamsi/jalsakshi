import type { HouseholdMasked, Operator } from '../../api/types';
import { Bi } from '../../components/Bi';
import { maskPhone } from '../../lib/format';
import { ROLE } from '../../lib/labels';
import styles from './VillageDetail.module.css';

/** Registered households with masked phones and consent. */
export function HouseholdList({ households }: { households: HouseholdMasked[] }) {
  return (
    <ul className={styles.register}>
      {households.map((h) => (
        <li key={h.id} className={styles.person}>
          <div className={styles.personMain}>
            <span className={styles.personName}>{h.display_name || h.id}</span>
            <span className={styles.phone}>{h.phone_masked}</span>
          </div>
          <div className={styles.personMeta}>
            {h.consent ? (
              <Bi
                inline
                hi={h.consent.channel === 'voice' ? 'सहमति: फ़ोन पर' : 'सहमति: आमने-सामने'}
                en={h.consent.channel === 'voice' ? 'consent by voice' : 'consent in person'}
                className={styles.consentYes}
              />
            ) : (
              <Bi inline hi="सहमति नहीं, कॉल नहीं होगा" en="no consent, never called" className={styles.consentNo} />
            )}
            <span className={styles.window}>
              <span lang="hi">कॉल का समय</span> <span lang="en">(call window)</span>{' '}
              <span className="num">{h.call_window}</span>
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Pump operator, sarpanch, secretary and the simulated department contacts. */
export function OperatorList({ operators }: { operators: Operator[] }) {
  return (
    <ul className={styles.register}>
      {operators.map((o) => (
        <li key={o.id} className={styles.person}>
          <div className={styles.personMain}>
            <span className={styles.personName}>{o.display_name || o.id}</span>
            <span className={styles.phone}>{maskPhone(o.phone_e164)}</span>
          </div>
          <Bi t={ROLE[o.role]} inline className={styles.role} />
        </li>
      ))}
    </ul>
  );
}
