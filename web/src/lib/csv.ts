/** CSV export for registers the Panchayat keeps outside the console (the consent ledger). */

import type { ConsentLedger } from '../api/types';
import { istStamp } from './format';

/** A cell a spreadsheet would run as a formula (=, +, -, @, tab, CR) gets a leading quote. */
const FORMULA_START = /^[=+\-@\t\r]/;

/** One CSV cell: formula-safe, quoted when it holds a comma, quote or line break. */
export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  let text = String(value);
  if (FORMULA_START.test(text)) text = `'${text}`;
  if (/[",\r\n]/.test(text)) text = `"${text.replace(/"/g, '""')}"`;
  return text;
}

/** Rows to RFC 4180 CSV (CRLF line ends, trailing newline). */
export function toCsv(rows: ReadonlyArray<ReadonlyArray<unknown>>): string {
  return rows.map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

export const CONSENT_CSV_HEADER = [
  'time_ist',
  'at_iso',
  'household_id',
  'phone_masked',
  'action',
  'notice_version',
  'notice_sha256',
  'channel',
  'digits',
  'call_id',
] as const;

/** The consent ledger as CSV, oldest first, masked phones only: the export used as consent proof. */
export function consentLedgerCsv(ledger: Pick<ConsentLedger, 'events'>): string {
  const events = [...ledger.events].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return toCsv([
    CONSENT_CSV_HEADER,
    ...events.map((e) => [
      istStamp(e.at),
      e.at,
      e.household_id,
      e.phone_masked,
      e.action,
      e.notice_version,
      e.notice_sha256,
      e.channel,
      e.digits ?? '',
      e.call_id ?? '',
    ]),
  ]);
}

/** "consent-ledger-v-nayapara-2026-10-09.csv" */
export function consentCsvName(villageId: string, today: string): string {
  const safe = villageId.replace(/[^a-z0-9-]+/gi, '-');
  return `consent-ledger-${safe}-${today}.csv`;
}

/** Hands a text file to the browser's download (UTF-8 with a BOM, so spreadsheets read Hindi). */
export function downloadText(filename: string, text: string, type = 'text/csv;charset=utf-8'): void {
  const blob = new Blob(['﻿', text], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
