/**
 * Plain-language framing for Cedar denials. The API sends the rule's own reason (reason_hi,
 * reason_en); the console adds a title, why the rule exists, and what happens next, so a deny
 * reads as the system keeping a promise rather than as an error.
 */

import type { Bilingual } from './format';

export interface PolicyCopy {
  /** Short heading: what the person cannot do right now. */
  title: Bilingual;
  /** Why the rule exists, from the household's side. */
  why: Bilingual;
  /** What happens next, or what the person can do. */
  next?: Bilingual;
}

const COPY: Record<string, PolicyCopy> = {
  'verify-needs-quorum': {
    title: { hi: 'शिकायत अभी बंद नहीं हो सकती', en: 'This ticket cannot close yet' },
    why: {
      hi: 'मरम्मत तभी पूरी मानी जाती है जब गाँव के घर ख़ुद फ़ोन पर बताएँ कि पानी लौट आया।',
      en: 'A repair counts only when the households themselves say on the phone that water is back.',
    },
    next: {
      hi: 'बाकी घरों से पुष्टि के कॉल जारी हैं। ज़रूरी घरों के "हाँ" कहते ही शिकायत बंद हो सकेगी।',
      en: 'Confirmation calls to the other households continue. Once enough say yes, the ticket can close.',
    },
  },
  'stale-data': {
    title: { hi: 'पत्र अभी नहीं बनेगा', en: 'The sheet is on hold' },
    why: {
      hi: 'ग्राम सभा के सामने पुराने आँकड़े न जाएँ, इसलिए पत्र के लिए पिछले 24 घंटे का डेटा ज़रूरी है।',
      en: 'So the Gram Sabha never sees old numbers, the sheet needs data from the last 24 hours.',
    },
    next: {
      hi: 'गाँव के पन्ने से आज की जाँच कॉल चलाएँ, फिर पत्र दोबारा बनाएँ।',
      en: "Run today's check-in from the village page, then make the sheet again.",
    },
  },
  'calling-hours': {
    title: { hi: 'अभी कॉल नहीं होगी', en: 'No calls at this hour' },
    why: {
      hi: 'घरों को सुबह-सवेरे या रात में परेशान नहीं किया जाता। कॉल सिर्फ़ सुबह 9 से रात 9 बजे तक।',
      en: 'Households are never called early in the morning or at night: calls run 09:00 to 21:00 IST only.',
    },
    next: { hi: 'सुबह 9 बजे के बाद फिर कोशिश करें।', en: 'Try again after 09:00 IST.' },
  },
  'consent-required': {
    title: { hi: 'इस घर को कॉल नहीं होगी', en: 'This household will not be called' },
    why: {
      hi: 'जिस घर की सहमति दर्ज नहीं है, उसे कभी कॉल नहीं किया जाता।',
      en: 'Nobody is called without their consent on file.',
    },
    next: {
      hi: 'पहले घर से सहमति लें, फ़ोन पर या आमने-सामने।',
      en: 'Record the household’s consent first, by phone or in person.',
    },
  },
  'one-call-per-day': {
    title: { hi: 'आज कॉल हो चुकी है', en: 'Already called today' },
    why: {
      hi: 'हर घर से दिन में एक ही बार पूछा जाता है, ताकि कोई परेशान न हो।',
      en: 'Each household is asked only once a day, so nobody is pestered.',
    },
    next: { hi: 'कल की जाँच में फिर पूछा जाएगा।', en: 'They will be asked again in tomorrow’s check-in.' },
  },
  'no-household-view-for-dept': {
    title: { hi: 'घरों के जवाब निजी हैं', en: 'Household answers stay private' },
    why: {
      hi: 'विभाग को गाँव का कुल आँकड़ा दिखता है, किसी घर का नाम या जवाब नहीं।',
      en: 'The department sees village totals, never a household’s name or answer.',
    },
  },
  'policy-evaluation-error': {
    title: { hi: 'जाँच पूरी नहीं हुई, इसलिए रोका', en: 'Held back: the check could not finish' },
    why: {
      hi: 'नियम की जाँच में शक हो तो प्रणाली काम रोक देती है।',
      en: 'When the rule check cannot finish, the system holds the action back (it fails closed).',
    },
    next: { hi: 'थोड़ी देर बाद फिर कोशिश करें।', en: 'Try again in a little while.' },
  },
};

const FALLBACK: PolicyCopy = {
  title: { hi: 'नियम के कारण रुका', en: 'Held back by a rule' },
  why: {
    hi: 'यह काम एक लिखे हुए नियम की वजह से नहीं हुआ।',
    en: 'A written rule stopped this action.',
  },
};

/** Title, reason-for-the-rule and next step for a Cedar policy id. */
export function policyCopy(policyId: string): PolicyCopy {
  return COPY[policyId] ?? FALLBACK;
}
