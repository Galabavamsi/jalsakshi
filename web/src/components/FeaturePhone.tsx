import type { ReactNode } from 'react';
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
  return (
    <div className={styles.phone}>
      <div className={styles.top} aria-hidden="true">
        <span className={styles.speaker} />
        <span className={styles.brand}>
          <span lang="hi">सिम्युलेटर</span> <span lang="en">Simulator</span>
        </span>
      </div>
      <div className={styles.screen}>{screen}</div>
      <div className={styles.callRow}>
        <button
          type="button"
          className={cx(styles.round, styles.call)}
          onClick={onCall}
          disabled={!callEnabled}
          aria-label="कॉल शुरू करें (Start call)"
        >
          <IconCall size={26} />
        </button>
        <button
          type="button"
          className={cx(styles.round, styles.hang)}
          onClick={onHangup}
          disabled={!hangupEnabled}
          aria-label="कॉल काटें (Hang up)"
        >
          <IconHangup size={28} />
        </button>
      </div>
      <div className={styles.keypad} role="group" aria-label="Keypad">
        {KEYS.map(([key, devanagari]) => (
          <button
            type="button"
            key={key}
            className={cx(styles.key, flashKey === key && styles.pressed)}
            onClick={() => onKey(key)}
            disabled={!keysEnabled}
            aria-label={`Key ${key === '#' ? 'hash' : key === '*' ? 'star' : key}`}
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
