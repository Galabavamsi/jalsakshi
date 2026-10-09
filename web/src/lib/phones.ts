/** Indian mobile numbers, read the same way as the API (api_onboarding.normalise_mobile). */

/** "+91XXXXXXXXXX" for a 10-digit Indian mobile in any common spelling, else null. */
export function normaliseMobile(raw: string): string | null {
  let digits = raw.replace(/\D/g, '');
  if (digits.length === 12 && digits.startsWith('91')) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith('0')) digits = digits.slice(1);
  if (digits.length !== 10 || !'6789'.includes(digits[0] ?? '')) return null;
  return `+91${digits}`;
}

export interface ParsedPhones {
  /** Valid numbers, de-duplicated, in the order pasted. */
  valid: string[];
  /** Lines that are not a mobile number (blank lines are ignored). */
  invalid: string[];
}

/** Splits pasted text on new lines, commas and semicolons and checks every entry. */
export function parsePhoneList(text: string): ParsedPhones {
  const valid: string[] = [];
  const invalid: string[] = [];
  for (const entry of text.split(/[\n,;]+/)) {
    const trimmed = entry.trim();
    if (!trimmed) continue;
    const phone = normaliseMobile(trimmed);
    if (!phone) invalid.push(trimmed);
    else if (!valid.includes(phone)) valid.push(phone);
  }
  return { valid, invalid };
}

/** "+91XXXXXX3210" style masking, as the API does. */
export function maskMobile(e164: string): string {
  if (e164.length <= 7) return 'X'.repeat(e164.length);
  return `${e164.slice(0, 3)}${'X'.repeat(e164.length - 7)}${e164.slice(-4)}`;
}

/** "+91XXXXXX3210" → "XXXXXX3210" style display: just the last four digits matter to people. */
export function shortMasked(masked: string | null | undefined): string {
  if (!masked) return '';
  return `•••• ${masked.slice(-4)}`;
}

/** The JalSakshi missed-call number families call to join (one number for every village). */
export const MISSED_CALL = '080 6426 0325';

/** "+918064260325" → "080 6426 0325"; empty → the default number; anything else as written. */
export function displayMissedCall(raw: string | null | undefined): string {
  const digits = (raw ?? '').replace(/\D/g, '');
  const local = digits.length === 12 && digits.startsWith('91') ? digits.slice(2) : digits.length === 10 ? digits : null;
  if (!local) return raw?.trim() || MISSED_CALL;
  return `0${local.slice(0, 2)} ${local.slice(2, 6)} ${local.slice(6)}`;
}
