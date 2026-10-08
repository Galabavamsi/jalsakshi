import { useEffect, useRef, useState } from 'react';
import { useApi } from '../api/context';
import type { Purpose, SimStartRequest, VillageDetail } from '../api/types';
import { Bi } from '../components/Bi';
import { FeaturePhone } from '../components/FeaturePhone';
import { ErrorNote, Loading } from '../components/PageState';
import { PolicyDenial } from '../components/PolicyDenial';
import { useAsync } from '../hooks/useAsync';
import { cx } from '../lib/cx';
import { PURPOSE, ROLE } from '../lib/labels';
import { promptCaption } from '../lib/prompts';
import type { LogEntry } from '../lib/simSession';
import { PhoneScreen } from './simulator/PhoneScreen';
import { useSimCall } from './simulator/useSimCall';
import styles from './simulator/Simulator.module.css';

type CallerKind = 'household' | 'operator';

interface Setup {
  villageId: string;
  kind: CallerKind;
  personId: string;
  purpose: Exclude<Purpose, 'OPERATOR'>;
}

function people(detail: VillageDetail | undefined, kind: CallerKind) {
  if (!detail) return [];
  if (kind === 'operator') {
    return detail.operators.map((o) => ({
      id: o.id,
      label: `${o.display_name || o.id}, ${ROLE[o.role].hi}`,
    }));
  }
  return detail.households.map((h) => ({
    id: h.id,
    label: `${h.display_name || h.id} (${h.phone_masked})${h.consent ? '' : ', सहमति नहीं'}`,
  }));
}

function toRequest(setup: Setup): SimStartRequest {
  return setup.kind === 'operator'
    ? { operator_id: setup.personId, purpose: 'OPERATOR' }
    : { household_id: setup.personId, purpose: setup.purpose };
}

function Transcript({ log }: { log: LogEntry[] }) {
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' });
  }, [log.length]);
  if (log.length === 0) {
    return (
      <p className={styles.transcriptEmpty}>
        <Bi
          hi="कॉल शुरू होने पर IVR की हर बात और हर दबाया बटन यहाँ लिखा जाएगा।"
          en="Once a call starts, every IVR prompt and every key press is written here."
        />
      </p>
    );
  }
  return (
    <ol className={styles.transcript} role="log" aria-label="Call transcript">
      {log.map((e) => {
        const caption = e.who === 'ivr' && e.key ? promptCaption(e.key, e.hi) : null;
        return (
          <li
            key={e.id}
            className={cx(styles.entry, styles[e.who])}
            ref={e.id === log[log.length - 1]?.id ? end : undefined}
          >
            <span lang="hi" className={styles.entryHi}>
              {caption ? caption.hi : e.hi}
            </span>
            {(caption?.en ?? e.en) && (
              <span lang="en" className={styles.entryEn}>
                {caption?.en ?? e.en}
              </span>
            )}
            {caption && (
              <span className={styles.entryKey}>
                <span lang="hi">आवाज़ में</span> <span lang="en">(spoken)</span>:{' '}
                <span lang="hi-Latn">{e.hi}</span>
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** The web-phone simulator: the same IVR engine as the phone line, driven from a keypad. */
export function SimulatorPage() {
  const api = useApi();
  const call = useSimCall();
  const villages = useAsync(() => api.listVillages(), 'villages');
  const [choice, setChoice] = useState<Partial<Setup>>({ kind: 'household', purpose: 'DAILY' });
  const villageId = choice.villageId ?? villages.data?.[0]?.village.id ?? '';
  const detail = useAsync(
    () => (villageId ? api.getVillage(villageId) : Promise.resolve(undefined)),
    `village:${villageId}`,
  );
  const kind = choice.kind ?? 'household';
  const options = people(detail.data, kind);
  const personId = options.some((o) => o.id === choice.personId) ? choice.personId : options[0]?.id;
  const setup: Setup | null = personId
    ? { villageId, kind, personId, purpose: choice.purpose ?? 'DAILY' }
    : null;

  const { state } = call;
  const inCall = ['dialing', 'live', 'sending'].includes(state.phase);
  const phoneRef = useRef<HTMLDivElement>(null);

  // On a phone the keypad sits below the form; bring its screen into view when a call starts.
  // Wider screens show form, phone and transcript side by side, so nothing needs to move there.
  useEffect(() => {
    if (state.phase !== 'dialing') return;
    if (!window.matchMedia('(max-width: 759px)').matches) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    phoneRef.current?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' });
  }, [state.phase]);
  const startCall = () => {
    if (setup) void call.start(toRequest(setup));
  };

  return (
    <div className="page">
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <Bi as="h1" hi="फ़ोन सिम्युलेटर" en="Phone simulator" className={styles.title} />
          <span className={styles.simTag}>
            <span lang="hi">सिम्युलेटर</span> <span lang="en">Simulator</span>
          </span>
        </div>
        <Bi
          hi="यह वही IVR चलाता है जो असली फ़ोन लाइन पर चलता है, पर कोई फ़ोन कॉल नहीं जाता। जवाब असली जवाबों की तरह दर्ज होते हैं और 'सिम्युलेटर' लिखे जाते हैं।"
          en="Runs the same IVR as the real phone line, but no phone call is placed. Answers are recorded like real ones and marked as simulator."
          className={styles.lede}
        />
      </header>

      <div className={styles.layout}>
        <form className={styles.setup} onSubmit={(e) => e.preventDefault()} aria-label="Call setup">
          {villages.error ? <ErrorNote error={villages.error} onRetry={villages.reload} /> : null}
          <div className={styles.field}>
            <Bi as="label" htmlFor="sim-village" hi="गाँव" en="Village" />
            <select
              id="sim-village"
              value={villageId}
              disabled={inCall || !villages.data}
              onChange={(e) => setChoice({ ...choice, villageId: e.target.value, personId: undefined })}
            >
              {villages.data?.map((v) => (
                <option key={v.village.id} value={v.village.id}>
                  {v.village.name}
                </option>
              ))}
            </select>
          </div>
          <fieldset className={styles.field} disabled={inCall}>
            <Bi as="legend" hi="फ़ोन कौन उठा रहा है" en="Who answers the phone" />
            <div className={styles.segmented}>
              {(['household', 'operator'] as const).map((k) => (
                <label key={k} className={cx(styles.segment, kind === k && styles.segmentOn)}>
                  <input
                    type="radio"
                    name="sim-kind"
                    value={k}
                    checked={kind === k}
                    onChange={() => setChoice({ ...choice, kind: k, personId: undefined })}
                  />
                  <Bi hi={k === 'household' ? 'घर' : 'नल जल मित्र'} en={k === 'household' ? 'Household' : 'Operator'} />
                </label>
              ))}
            </div>
          </fieldset>
          <div className={styles.field}>
            <Bi as="label" htmlFor="sim-person" hi="किसका फ़ोन" en="Whose phone" />
            {detail.loading && !detail.data ? (
              <Loading />
            ) : (
              <select
                id="sim-person"
                value={personId ?? ''}
                disabled={inCall || options.length === 0}
                onChange={(e) => setChoice({ ...choice, personId: e.target.value })}
              >
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
          </div>
          {kind === 'household' && (
            <fieldset className={styles.field} disabled={inCall}>
              <Bi as="legend" hi="कॉल किस लिए" en="Call purpose" />
              <div className={styles.segmented}>
                {(['DAILY', 'VERIFY'] as const).map((p) => (
                  <label key={p} className={cx(styles.segment, choice.purpose === p && styles.segmentOn)}>
                    <input
                      type="radio"
                      name="sim-purpose"
                      value={p}
                      checked={choice.purpose === p}
                      onChange={() => setChoice({ ...choice, purpose: p })}
                    />
                    <Bi t={PURPOSE[p]} />
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          <button type="button" className="btn btn-primary" onClick={startCall} disabled={!setup || inCall}>
            <Bi hi="कॉल शुरू करें" en="Start call" />
          </button>
          <p className={styles.keysHint}>
            <Bi
              hi="कंप्यूटर के कीबोर्ड से भी 0-9, * और # दबा सकते हैं।"
              en="You can also type 0-9, * and # on a keyboard."
            />
          </p>
        </form>

        <div className={styles.phoneCol} ref={phoneRef}>
          <FeaturePhone
            screen={<PhoneScreen state={state} />}
            onKey={call.press}
            onCall={startCall}
            onHangup={call.hangup}
            keysEnabled={state.phase === 'live'}
            callEnabled={Boolean(setup) && !inCall}
            hangupEnabled={inCall}
            flashKey={call.flashKey}
          />
          <audio {...call.audioProps} preload="auto" className="visually-hidden" />
        </div>

        <section className={styles.transcriptCol} aria-labelledby="transcript-title">
          <Bi as="h2" id="transcript-title" hi="कॉल का लेखा" en="Call transcript" className={styles.transcriptTitle} />
          {state.denied && <PolicyDenial denied={state.denied} onDismiss={call.reset} />}
          <Transcript log={state.log} />
        </section>
      </div>
    </div>
  );
}
