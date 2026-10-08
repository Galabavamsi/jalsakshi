import { useEffect, useRef, useState } from 'react';
import { useApi } from '../api/context';
import type { Purpose, SimStartRequest, VillageDetail } from '../api/types';
import { Bi } from '../components/Bi';
import { FeaturePhone } from '../components/FeaturePhone';
import { ErrorNote, Loading } from '../components/PageState';
import { PolicyDenial } from '../components/PolicyDenial';
import { useAsync } from '../hooks/useAsync';
import { simChoicesLine } from '../i18n/messages';
import { useLocale, useT, type Translate } from '../i18n/locale';
import { cx } from '../lib/cx';
import type { Bilingual } from '../lib/format';
import { PURPOSE, ROLE } from '../lib/labels';
import { villageLabel } from '../lib/places';
import { promptCaption, type PromptCaption } from '../lib/prompts';
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

function people(detail: VillageDetail | undefined, kind: CallerKind): Array<{ id: string; label: Bilingual }> {
  if (!detail) return [];
  if (kind === 'operator') {
    return detail.operators.map((o) => {
      const name = o.display_name || o.id;
      return { id: o.id, label: { en: `${name}, ${ROLE[o.role].en}`, hi: `${name}, ${ROLE[o.role].hi}` } };
    });
  }
  return detail.households.map((h) => {
    const name = `${h.display_name || h.id} (${h.phone_masked})`;
    return {
      id: h.id,
      label: h.consent ? { en: name, hi: name } : { en: `${name}, no consent`, hi: `${name}, सहमति नहीं` },
    };
  });
}

/** "Did tap water come today? Press 1 for yes, 2 for no, 3 for a little." */
function captionLine(caption: PromptCaption, t: Translate): string {
  const text = t(caption);
  if (!caption.choices) return text;
  const choices = caption.choices.map((c) => ({ key: c.key, label: t(c.label) }));
  return `${text} ${t(simChoicesLine, { choices })}`;
}

/** "Pressed 2 (No)": the keypad answer in words, from the question it answered. */
function pressedLine(entry: LogEntry, asked: PromptCaption | null, t: Translate): string {
  const pressed = /^दबाया: (.*)$/.exec(entry.hi)?.[1];
  if (pressed === undefined) return t({ en: entry.en ?? entry.hi, hi: entry.hi });
  const choice = asked?.choices?.find((c) => c.key === pressed);
  const label = choice ? ` (${t(choice.label)})` : '';
  return t({ en: `Pressed ${pressed}${label}`, hi: `दबाया: ${pressed}${label}` });
}

function toRequest(setup: Setup): SimStartRequest {
  return setup.kind === 'operator'
    ? { operator_id: setup.personId, purpose: 'OPERATOR' }
    : { household_id: setup.personId, purpose: setup.purpose };
}

function Transcript({ log }: { log: LogEntry[] }) {
  const t = useT();
  const { locale } = useLocale();
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' });
  }, [log.length]);
  if (log.length === 0) {
    return (
      <p className={cx(styles.transcriptEmpty, 'dry')}>
        <Bi
          en="Once a call starts, every IVR prompt and every key press is written here."
          hi="कॉल शुरू होने पर IVR की हर बात और हर दबाया बटन यहाँ लिखा जाएगा।"
        />
      </p>
    );
  }
  let asked: PromptCaption | null = null;
  return (
    <ol className={styles.transcript} role="log" aria-label={t({ en: 'Call transcript', hi: 'कॉल का लेखा' })}>
      {log.map((e) => {
        const isLast = e.id === log[log.length - 1]?.id;
        const who =
          e.who === 'ivr'
            ? 'IVR'
            : e.who === 'caller'
              ? t({ en: 'You', hi: 'आप' })
              : t({ en: 'Note', hi: 'सूचना' });
        if (e.who === 'ivr') {
          const caption = e.key ? promptCaption(e.key, e.hi) : null;
          if (caption?.choices) asked = caption;
          return (
            <li key={e.id} className={cx(styles.entry, styles.ivr)} ref={isLast ? end : undefined}>
              <span className={styles.speaker}>{who}</span>
              <span className={styles.entryBody}>
                {caption ? (
                  <span className={styles.entryMain} lang={locale}>
                    {captionLine(caption, t)}
                  </span>
                ) : (
                  <span className={styles.entryMain} lang="hi-Latn">
                    {e.hi}
                  </span>
                )}
                {/* In Hindi the caption already is what villagers hear; the romanised line would repeat it */}
                {caption && locale === 'en' && (
                  <span className={styles.entryHeard}>
                    {t({ en: 'Villagers hear, in Hindi: ', hi: 'गाँव वाले सुनते हैं: ' })}
                    <span lang="hi-Latn">“{e.hi}”</span>
                  </span>
                )}
              </span>
            </li>
          );
        }
        const text = e.who === 'caller' ? pressedLine(e, asked, t) : t({ en: e.en ?? e.hi, hi: e.hi });
        return (
          <li key={e.id} className={cx(styles.entry, styles[e.who])} ref={isLast ? end : undefined}>
            <span className={styles.speaker}>{who}</span>
            <span className={styles.entryBody}>
              <span className={styles.entryMain}>{text}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The web-phone simulator: the same IVR engine as the phone line, driven from a keypad. */
export function SimulatorPage() {
  const api = useApi();
  const t = useT();
  const call = useSimCall();
  const { locale } = useLocale();
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
          <Bi as="h1" en="Phone simulator" hi="फ़ोन सिम्युलेटर" className="page-title" />
          <span className={styles.simTag}>{t({ en: 'Simulator', hi: 'सिम्युलेटर' })}</span>
        </div>
        <Bi
          as="p"
          en="The same Hindi phone menu villagers hear, driven from a keypad. No phone call is placed; answers are recorded like real ones and marked as simulator."
          hi="वही हिन्दी फ़ोन मेनू जो गाँव वाले सुनते हैं, कीपैड से चलाया गया। कोई फ़ोन कॉल नहीं जाता; जवाब असली जवाबों की तरह दर्ज होते हैं और 'सिम्युलेटर' लिखे जाते हैं।"
          className={styles.lede}
        />
      </header>

      <div className={styles.layout}>
        <form
          className={styles.setup}
          onSubmit={(e) => e.preventDefault()}
          aria-label={t({ en: 'Call setup', hi: 'कॉल की तैयारी' })}
        >
          {villages.error ? <ErrorNote error={villages.error} onRetry={villages.reload} /> : null}
          <div className={styles.field}>
            <Bi as="label" htmlFor="sim-village" en="Village" hi="गाँव" />
            <select
              id="sim-village"
              value={villageId}
              disabled={inCall || !villages.data}
              onChange={(e) => setChoice({ ...choice, villageId: e.target.value, personId: undefined })}
            >
              {villages.data?.map((v) => (
                <option key={v.village.id} value={v.village.id}>
                  {villageLabel(v.village, locale)}
                </option>
              ))}
            </select>
          </div>
          <fieldset className={styles.field} disabled={inCall}>
            <Bi as="legend" en="Who answers the phone" hi="फ़ोन कौन उठा रहा है" />
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
                  <Bi
                    en={k === 'household' ? 'Household' : 'Pump operator'}
                    hi={k === 'household' ? 'घर' : 'नल जल मित्र'}
                  />
                </label>
              ))}
            </div>
          </fieldset>
          <div className={styles.field}>
            <Bi as="label" htmlFor="sim-person" en="Whose phone" hi="किसका फ़ोन" />
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
                    {t(o.label)}
                  </option>
                ))}
              </select>
            )}
          </div>
          {kind === 'household' && (
            <fieldset className={styles.field} disabled={inCall}>
              <Bi as="legend" en="Call purpose" hi="कॉल किस लिए" />
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
            <Bi en="Start call" hi="कॉल शुरू करें" />
          </button>
          <p className={styles.keysHint}>
            <Bi
              en="You can also type 0-9, * and # on a keyboard."
              hi="कंप्यूटर के कीबोर्ड से भी 0-9, * और # दबा सकते हैं।"
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
          <Bi as="h2" id="transcript-title" en="Call transcript" hi="कॉल का लेखा" className={styles.transcriptTitle} />
          {state.denied && <PolicyDenial denied={state.denied} onDismiss={call.reset} />}
          <Transcript log={state.log} />
        </section>
      </div>
    </div>
  );
}
