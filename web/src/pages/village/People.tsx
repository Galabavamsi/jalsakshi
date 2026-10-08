import type { HouseholdMasked, Operator } from '../../api/types';
import { useT } from '../../i18n/locale';
import { maskPhone } from '../../lib/format';
import { ROLE } from '../../lib/labels';
import styles from './VillageDetail.module.css';

/** Registered households: name as written, masked phone, consent and call window. */
export function HouseholdList({ households }: { households: HouseholdMasked[] }) {
  const t = useT();
  return (
    <ul className={styles.register}>
      {households.map((h) => (
        <li key={h.id} className={styles.person}>
          <div className={styles.personMain}>
            <span className={styles.personName} lang="hi">
              {h.display_name || h.id}
            </span>
            <span className={styles.phone}>{h.phone_masked}</span>
          </div>
          <div className={styles.personMeta}>
            {h.consent ? (
              <span className={styles.consentYes}>
                {h.consent.channel === 'voice'
                  ? t({ en: 'Consent by phone', hi: 'सहमति: फ़ोन पर' })
                  : t({ en: 'Consent in person', hi: 'सहमति: आमने-सामने' })}
              </span>
            ) : (
              <span className={styles.consentNo}>
                {t({ en: 'No consent: never called', hi: 'सहमति नहीं, कॉल नहीं होगा' })}
              </span>
            )}
            <span className={styles.window}>
              {t({ en: 'Call window', hi: 'कॉल का समय' })} <span className="num">{h.call_window}</span>
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Pump operator, sarpanch, secretary and the simulated department contacts. */
export function OperatorList({ operators }: { operators: Operator[] }) {
  const t = useT();
  return (
    <ul className={styles.register}>
      {operators.map((o) => (
        <li key={o.id} className={styles.person}>
          <div className={styles.personMain}>
            <span className={styles.personName} lang="hi">
              {o.display_name || o.id}
            </span>
            <span className={styles.phone}>{maskPhone(o.phone_e164)}</span>
          </div>
          <span className={styles.role}>{t(ROLE[o.role])}</span>
        </li>
      ))}
    </ul>
  );
}
