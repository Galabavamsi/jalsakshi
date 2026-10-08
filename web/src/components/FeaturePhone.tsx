import type { ReactNode } from 'react';
import { useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { IconCall, IconHangup } from './Icons';
import styles from './FeaturePhone.module.css';

const KEYS: Array<[string, string]> = [
  ['1', '१'],
  ['2', '२'],
  ['3', '३'],
  ['4', '४'],
  ['5', '५'],
  ['6', '६'],
  ['7', '७'],
  ['8', '८'],
  ['9', '९'],
  ['*', ''],
  ['0', '०'],
  ['#', ''],
];

interface PhoneProps {
  screen: ReactNode;
  onKey: (key: string) => void;
  onCall: () => void;
  onHangup: () => void;
  keysEnabled: boolean;
  callEnabled: boolean;
  hangupEnabled: boolean;
  /** Key to show as pressed, for physical-keyboard presses. */
  flashKey?: string | null;
}

/** A keypad phone drawn in CSS. Keys carry Devanagari numerals as on phones sold in India. */
export function FeaturePhone(props: PhoneProps) {
  const { screen, onKey, onCall, onHangup, keysEnabled, callEnabled, hangupEnabled, flashKey } = props;
  const t = useT();
  const keyName = (key: string) =>
    key === '#' ? t({ en: 'hash', hi: 'हैश' }) : key === '*' ? t({ en: 'star', hi: 'स्टार' }) : key;
  return (
    <div className={styles.phone}>
      <div className={styles.top} aria-hidden="true">
        <span className={styles.speaker} />
        <span className={styles.brand}>{t({ en: 'JalSakshi simulator', hi: 'जल साक्षी सिम्युलेटर' })}</span>
      </div>
      <div className={styles.screen}>{screen}</div>
      <div className={styles.callRow}>
        <button
          type="button"
          className={cx(styles.round, styles.call)}
          onClick={onCall}
          disabled={!callEnabled}
          aria-label={t({ en: 'Start call', hi: 'कॉल शुरू करें' })}
        >
          <IconCall size={26} />
        </button>
        <button
          type="button"
          className={cx(styles.round, styles.hang)}
          onClick={onHangup}
          disabled={!hangupEnabled}
          aria-label={t({ en: 'Hang up', hi: 'कॉल काटें' })}
        >
          <IconHangup size={28} />
        </button>
      </div>
      <div className={styles.keypad} role="group" aria-label={t({ en: 'Keypad', hi: 'कीपैड' })}>
        {KEYS.map(([key, devanagari]) => (
          <button
            type="button"
            key={key}
            className={cx(styles.key, flashKey === key && styles.pressed)}
            onClick={() => onKey(key)}
            disabled={!keysEnabled}
            aria-label={t({ en: `Key ${keyName(key)}`, hi: `बटन ${keyName(key)}` })}
          >
            <span className={styles.digit}>{key}</span>
            {devanagari && (
              <span className={styles.dev} lang="hi" aria-hidden="true">
                {devanagari}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
