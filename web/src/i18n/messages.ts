/**
 * Messages with numbers in them. English is written first and is the source of truth; both
 * languages take the same parameters, so a missing translation or a wrong parameter is a
 * compile error. Plurals use Intl.PluralRules, with an explicit zero message (CLDR puts 0 in
 * "one" for Hindi).
 */

import type { Verdict } from '../lib/verdict';
import type { BilingualFn } from './locale';

const enPlural = new Intl.PluralRules('en');

/** "1 household" / "3 households". */
export function enCount(n: number, one: string, other: string): string {
  return `${n} ${enPlural.select(n) === 'one' ? one : other}`;
}

// ---------------------------------------------------------------- villages

export const villagesLede: BilingualFn<{ gap: number; claimed: number }> = {
  en: ({ gap, claimed }) =>
    gap === 0
      ? `This week, households in every village on record as Har Ghar Jal (tap water in every home) back the record.`
      : `This week, households in ${gap} of ${enCount(claimed, 'village', 'villages')} on record as Har Ghar Jal (tap water in every home) reported days without water.`,
  hi: ({ gap, claimed }) =>
    gap === 0
      ? 'इस हफ़्ते रिकॉर्ड में हर घर जल वाले सभी गाँवों के घर रिकॉर्ड से सहमत हैं।'
      : `इस हफ़्ते रिकॉर्ड में हर घर जल वाले ${claimed} में से ${gap} गाँवों के घरों ने बिना पानी वाले दिन बताए।`,
};

/** The verdict line on a village board and the village page header. */
export const verdictText: BilingualFn<Verdict & { checkinTime: string }> = {
  en: (v) => {
    switch (v.kind) {
      case 'silent':
        return `No household answers yet this week. Today's calls at ${v.checkinTime} IST.`;
      case 'gap': {
        const parts: string[] = [];
        if (v.no > 0) parts.push(`no water on ${v.no}`);
        if (v.dirty > 0) parts.push(`dirty water on ${v.dirty}`);
        return `The record says tap water in every home. Households said ${parts.join(' and ')} of the last ${v.days} days.`;
      }
      case 'agree':
        return `Households back the record: water came on ${v.supplied} of the last ${v.days} days.`;
      case 'plain': {
        const tail: string[] = [];
        if (v.no > 0) tail.push(`no water on ${v.no}`);
        if (v.dirty > 0) tail.push(`dirty water on ${v.dirty}`);
        const extra = tail.length > 0 ? `, ${tail.join(' and ')}` : '';
        return `Households said water came on ${v.supplied} of the last ${v.days} days${extra}.`;
      }
    }
  },
  hi: (v) => {
    switch (v.kind) {
      case 'silent':
        return `इस हफ़्ते अभी किसी घर का जवाब नहीं आया। आज के कॉल ${v.checkinTime} बजे।`;
      case 'gap': {
        const parts: string[] = [];
        if (v.no > 0) parts.push(`${v.no} दिन पानी नहीं आया`);
        if (v.dirty > 0) parts.push(`${v.dirty} दिन गंदा पानी आया`);
        return `रिकॉर्ड कहता है हर घर में नल का पानी। घरों ने बताया: पिछले ${v.days} में से ${parts.join(' और ')}।`;
      }
      case 'agree':
        return `घर रिकॉर्ड से सहमत हैं: पिछले ${v.days} में से ${v.supplied} दिन पानी आया।`;
      case 'plain': {
        const tail: string[] = [];
        if (v.no > 0) tail.push(`${v.no} दिन पानी नहीं आया`);
        if (v.dirty > 0) tail.push(`${v.dirty} दिन गंदा पानी`);
        const extra = tail.length > 0 ? `, ${tail.join(' और ')}` : '';
        return `घरों ने बताया: पिछले ${v.days} में से ${v.supplied} दिन पानी आया${extra}।`;
      }
    }
  },
};

export const openTicketLine: BilingualFn<{ reason: string; since: string }> = {
  en: ({ reason, since }) => `Repair ticket open: ${reason.toLowerCase()}. Opened ${since}.`,
  hi: ({ reason, since }) => `मरम्मत की शिकायत खुली: ${reason}। ${since} खुली।`,
};

// ---------------------------------------------------------------- village page

export const villageIntro: BilingualFn<{ place: string; callable: number; time: string; quorum: number }> = {
  en: ({ place, callable, time, quorum }) =>
    callable === 0
      ? `${place}. No household with consent on file yet, so nobody is called. At least ${quorum} must answer for a day to count.`
      : `${place}. ${enCount(callable, 'household is', 'households are')} called daily at ${time} IST. At least ${quorum} must answer for a day to count.`,
  hi: ({ place, callable, time, quorum }) =>
    callable === 0
      ? `${place}। अभी किसी घर की सहमति दर्ज नहीं, इसलिए कोई कॉल नहीं। दिन तय करने के लिए कम से कम ${quorum} घरों का जवाब ज़रूरी।`
      : `${place}। रोज़ ${time} बजे ${callable} घरों को कॉल। दिन तय करने के लिए कम से कम ${quorum} घरों का जवाब ज़रूरी।`,
};

export const householdsTitle: BilingualFn<{ n: number }> = {
  en: ({ n }) => `Registered households (${n})`,
  hi: ({ n }) => `पंजीकृत घर (${n})`,
};

export const runCheckinConfirm: BilingualFn<{ n: number }> = {
  en: ({ n }) => `This calls ${enCount(n, 'household', 'households')} now. Anyone already called today is skipped.`,
  hi: ({ n }) => `अभी ${n} घरों को कॉल जाएगा। आज जिन्हें कॉल हो चुका, उन्हें छोड़ दिया जाएगा।`,
};

export const dayHeadline: BilingualFn<{ date: string; status: string; answered: number; no: number; yes: number }> = {
  en: ({ date, status, answered, yes, no }) => {
    if (answered === 0) return `${date}: ${status}. Nobody answered.`;
    const said = no > 0 ? `${no} said no` : `${yes} said yes`;
    return `${date}: ${status}. ${answered} answered, ${said}.`;
  },
  hi: ({ date, status, answered, yes, no }) => {
    if (answered === 0) return `${date}: ${status}। किसी ने जवाब नहीं दिया।`;
    const said = no > 0 ? `${no} ने ना कहा` : `${yes} ने हाँ कहा`;
    return `${date}: ${status}। ${answered} ने जवाब दिया, ${said}।`;
  },
};

export const stripCellLabel: BilingualFn<{
  date: string;
  status: string | null;
  answered: number;
  no: number;
  partial: number;
  dirty: number;
  today: boolean;
}> = {
  en: ({ date, status, answered, no, partial, dirty, today }) => {
    const day = today ? `Today, ${date}` : date;
    if (!status) return `${day}: no calls`;
    return `${day}: ${status}. ${answered} answered, ${no} no, ${partial} partial, ${dirty} dirty.`;
  },
  hi: ({ date, status, answered, no, partial, dirty, today }) => {
    const day = today ? `आज, ${date}` : date;
    if (!status) return `${day}: कोई कॉल नहीं`;
    return `${day}: ${status}। ${answered} ने जवाब दिया, ${no} नहीं, ${partial} थोड़ा, ${dirty} गंदा।`;
  },
};

// ---------------------------------------------------------------- ticket

export const ticketTitle: BilingualFn<{ reason: string; village: string }> = {
  en: ({ reason, village }) => `${reason} in ${village}`,
  hi: ({ reason, village }) => `${village}: ${reason}`,
};

export const ticketMeta: BilingualFn<{ opened: string; updated: string }> = {
  en: ({ opened, updated }) => `Opened ${opened}. Updated ${updated}.`,
  hi: ({ opened, updated }) => `${opened} को खुली। ${updated} बदली।`,
};

export const confirmedText: BilingualFn<{ yes: number; needed: number }> = {
  en: ({ yes, needed }) =>
    yes === 0
      ? `No household has confirmed yet. ${needed} need to say yes.`
      : `${yes} of the ${needed} households needed have confirmed water is back`,
  hi: ({ yes, needed }) =>
    yes === 0
      ? `अभी किसी घर ने पुष्टि नहीं की। ${needed} घरों की "हाँ" ज़रूरी है।`
      : `ज़रूरी ${needed} में से ${yes} ${yes === 1 ? 'घर ने' : 'घरों ने'} पुष्टि की कि पानी लौट आया`,
};

export const verifiedStampLabel: BilingualFn<{ when: string }> = {
  en: ({ when }) => `Verified by households, ${when}`,
  hi: ({ when }) => `घरों ने पुष्टि की, ${when}`,
};

// ---------------------------------------------------------------- brief

export const briefGist: BilingualFn<{
  days: number;
  supplied: number;
  noSupply: number | null;
  opened: number | null;
  closed: number | null;
}> = {
  en: ({ days, supplied, noSupply, opened, closed }) => {
    let s = `Households reported water on ${supplied} of ${days} days.`;
    if (noSupply !== null && noSupply > 0) s += ` No water on ${noSupply}.`;
    if (opened !== null && closed !== null) {
      s += ` ${enCount(opened, 'repair ticket', 'repair tickets')} opened, ${closed} closed after households confirmed.`;
    }
    return s;
  },
  hi: ({ days, supplied, noSupply, opened, closed }) => {
    let s = `${days} में से ${supplied} दिन घरों ने पानी आने की बात कही।`;
    if (noSupply !== null && noSupply > 0) s += ` ${noSupply} दिन पानी नहीं आया।`;
    if (opened !== null && closed !== null) {
      s += ` ${opened} ${opened === 1 ? 'शिकायत खुली' : 'शिकायतें खुलीं'}; घरों की पुष्टि से बंद: ${closed}।`;
    }
    return s;
  },
};

// ---------------------------------------------------------------- simulator and activity

export const simChoicesLine: BilingualFn<{ choices: Array<{ key: string; label: string }> }> = {
  en: ({ choices }) => `Press ${choices.map((c) => `${c.key} for ${c.label}`).join(', ')}.`,
  hi: ({ choices }) => `${choices.map((c) => `${c.label} के लिए ${c.key}`).join(', ')} दबाएँ।`,
};

export const refreshEvery: BilingualFn<{ seconds: number }> = {
  en: ({ seconds }) => `Refreshes every ${seconds} seconds`,
  hi: ({ seconds }) => `हर ${seconds} सेकंड में नई जानकारी`,
};
