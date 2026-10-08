import { IconSpeaker } from '../../components/Icons';
import { useT } from '../../i18n/locale';
import { promptCaption } from '../../lib/prompts';
import { timerRunning, type SimState } from '../../lib/simSession';
import styles from './Simulator.module.css';

function Line({ hi, en }: { hi: string; en: string }) {
  return (
    <p className={styles.lcdLine}>
      <span lang="hi">{hi}</span>
      <span lang="en" className={styles.lcdEn}>
        {en}
      </span>
    </p>
  );
}

/**
 * What the phone's display shows for each moment of a call: the question and the keys to press.
 * The phone is the villagers' channel, so its screen is Hindi in both console languages, with a
 * small English line under each prompt.
 */
export function PhoneScreen({ state }: { state: SimState }) {
  const t = useT();
  if (state.phase === 'idle') {
    return <Line hi="तैयार। हरा बटन दबाकर कॉल शुरू करें।" en="Ready. Press the green key to start a call." />;
  }
  if (state.phase === 'dialing') return <Line hi="कॉल लग रहा है…" en="Connecting" />;
  if (state.phase === 'failed') {
    return <Line hi="कॉल नहीं हो पाया" en={state.denied ? 'Held back by a rule' : state.error ?? 'Call failed'} />;
  }
  if (state.phase === 'ended') {
    return <Line hi="कॉल समाप्त। नया कॉल हरे बटन से।" en="Call ended. Press green for a new call." />;
  }

  const waiting = state.waiting;
  const running = timerRunning(state);
  const caption = state.screen ? promptCaption(state.screen.key, state.screen.text) : null;
  const choices = waiting?.kind === 'digits' ? caption?.choices : undefined;
  return (
    <div className={styles.lcd} aria-live="polite">
      <p className={styles.lcdHeader}>
        <span>JalSakshi IVR</span>
        {state.audio.length > 0 && (
          <span className={styles.playing}>
            <IconSpeaker size={16} />
            <span lang="hi">बोल रहा है</span>
          </span>
        )}
      </p>
      {state.screen &&
        (caption ? (
          <p className={styles.prompt}>
            <span lang="hi">{caption.hi}</span>
            <span lang="en" className={styles.promptEn}>
              {caption.en}
            </span>
          </p>
        ) : (
          <p className={styles.prompt} lang="hi">
            {state.screen.text}
          </p>
        ))}
      {choices && (
        <ul className={styles.choices}>
          {choices.map((c) => (
            <li key={c.key}>
              <span className={styles.choiceKey}>{c.key}</span>
              <span lang="hi">{c.label.hi}</span>
              <span lang="en" className={styles.choiceEn}>
                {c.label.en}
              </span>
            </li>
          ))}
        </ul>
      )}
      {state.phase === 'sending' && <Line hi="भेज रहे हैं" en="Sending" />}
      {waiting?.kind === 'digits' && !choices && (
        <p className={styles.ask}>
          <span lang="hi">अब नंबर दबाएँ</span>{' '}
          <span lang="en">(press a key{state.buffer ? `: ${state.buffer}` : ''})</span>
        </p>
      )}
      {waiting?.kind === 'record' && (
        <p className={styles.ask}>
          <span lang="hi">बोलने का समय, # से आगे</span> <span lang="en">(press # to skip)</span>
        </p>
      )}
      {waiting && running && (
        <span
          key={waiting.seq}
          className={styles.countdown}
          style={{ animationDuration: `${waiting.timeoutS}s` }}
          role="timer"
          aria-label={t({ en: `${waiting.timeoutS} seconds to answer`, hi: `जवाब के लिए ${waiting.timeoutS} सेकंड` })}
        />
      )}
    </div>
  );
}
