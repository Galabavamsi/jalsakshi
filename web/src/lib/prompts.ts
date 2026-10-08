/**
 * Captions for the IVR prompts. The call audio is rendered from romanised Hindi
 * (prompts/hi.yaml), so the API's `text_hi` is in Latin letters. On the simulator's screen and in
 * its transcript the console shows the same sentence in Devanagari with an English line below,
 * plus the keypad choices the question offers.
 */

import type { Bilingual } from './format';

export interface KeyChoice {
  key: string;
  label: Bilingual;
}

export interface PromptCaption extends Bilingual {
  /** Keypad choices the prompt asks for, in order. */
  choices?: KeyChoice[];
}

const YES_NO_PARTIAL: KeyChoice[] = [
  { key: '1', label: { hi: 'हाँ, आया', en: 'yes' } },
  { key: '2', label: { hi: 'नहीं आया', en: 'no' } },
  { key: '3', label: { hi: 'थोड़ा आया', en: 'a little' } },
];

const CAPTIONS: Record<string, PromptCaption> = {
  'household.greet': {
    hi: 'नमस्ते। जल साक्षी से बोल रहे हैं। आपके गाँव के नल के पानी के बारे में तीन छोटे सवाल हैं।',
    en: 'Hello, this is JalSakshi. Three short questions about your village tap water.',
  },
  'household.q_water': {
    hi: 'आज नल में पानी आया?',
    en: 'Did tap water come today?',
    choices: YES_NO_PARTIAL,
  },
  'household.q_hours': {
    hi: 'कितने घंटे पानी आया? 0 से 9 तक नंबर दबाइए।',
    en: 'For how many hours did water come? Press 0 to 9.',
  },
  'household.q_clean': {
    hi: 'पानी साफ़ था?',
    en: 'Was the water clean?',
    choices: [
      { key: '1', label: { hi: 'साफ़', en: 'clean' } },
      { key: '2', label: { hi: 'गंदा', en: 'dirty' } },
    ],
  },
  'household.q_note': {
    hi: 'कुछ और बताना हो तो बीप के बाद 15 सेकंड बोलें। नहीं तो # दबाइए।',
    en: 'Anything else? Speak for 15 seconds after the beep, or press #.',
  },
  'household.bye': {
    hi: 'धन्यवाद। आपका जवाब गाँव की ग्राम सभा तक पहुँचेगा।',
    en: 'Thank you. Your answer will reach the village Gram Sabha.',
  },
  'household.invalid': {
    hi: 'माफ़ कीजिए, समझ नहीं आया। फिर से सुनते हैं।',
    en: 'Sorry, that was not clear. Let us hear it again.',
  },
  'verify.greet': {
    hi: 'नमस्ते। जल साक्षी से बोल रहे हैं। आपने बताया था कि नल में पानी नहीं आ रहा था।',
    en: 'Hello, this is JalSakshi. You told us the tap had no water.',
  },
  'verify.q_water': {
    hi: 'क्या अब नल में पानी आ रहा है?',
    en: 'Is tap water coming now?',
    choices: [
      { key: '1', label: { hi: 'हाँ, आ रहा है', en: 'yes' } },
      { key: '2', label: { hi: 'नहीं', en: 'no' } },
    ],
  },
  'verify.bye': {
    hi: 'धन्यवाद। आपकी पुष्टि के बिना शिकायत बंद नहीं होगी।',
    en: 'Thank you. The complaint will not close without your confirmation.',
  },
  'operator.greet': {
    hi: 'नमस्ते। जल साक्षी से नल जल मित्र के लिए सूचना है।',
    en: 'Hello, this is JalSakshi with a message for the Nal Jal Mitra (pump operator).',
  },
  'operator.q_fixed': {
    hi: 'समस्या ठीक हो गई है?',
    en: 'Is the problem fixed?',
    choices: [
      { key: '1', label: { hi: 'ठीक हो गई', en: 'fixed' } },
      { key: '2', label: { hi: 'अभी नहीं', en: 'not yet' } },
    ],
  },
  'operator.ack_fixed': {
    hi: 'धन्यवाद। हम घरों से पुष्टि करेंगे, फिर शिकायत बंद होगी।',
    en: 'Thank you. We will check with the households, then the complaint closes.',
  },
  'operator.ack_pending': {
    hi: 'ठीक है। मरम्मत हो जाने पर पंचायत को बताएँ, फिर घरों से पुष्टि होगी।',
    en: 'All right. Tell the Panchayat once it is repaired; then the households will confirm.',
  },
};

/** The first number in a spoken sentence, e.g. the household count in an operator summary. */
function firstNumber(text: string): string | null {
  const match = /\d+/.exec(text);
  return match ? match[0] : null;
}

function summaryCaption(key: string, spoken: string): PromptCaption | null {
  const n = firstNumber(spoken);
  const count = n ?? 'कुछ';
  const countEn = n ?? 'some';
  if (key === 'operator.summary_no_supply') {
    return {
      hi: `आज गाँव के ${count} घरों ने बताया कि नल में पानी नहीं आया।`,
      en: `Today ${countEn} households in the village said the tap had no water.`,
    };
  }
  if (key === 'operator.summary_dirty') {
    return {
      hi: `आज गाँव के ${count} घरों ने बताया कि पानी गंदा था।`,
      en: `Today ${countEn} households in the village said the water was dirty.`,
    };
  }
  return null;
}

/** Devanagari + English caption for a prompt key, or null for a key the console does not know. */
export function promptCaption(key: string, spoken: string): PromptCaption | null {
  return CAPTIONS[key] ?? summaryCaption(key, spoken);
}
