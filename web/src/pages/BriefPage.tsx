import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import type { Brief, IsoDate } from '../api/types';
import { Bi } from '../components/Bi';
import { IconBack, IconPrint, IconRefresh } from '../components/Icons';
import { ErrorNote, Loading } from '../components/PageState';
import { Markdown } from '../components/Markdown';
import { SourceBadge } from '../components/SourceBadge';
import { Wash } from '../components/Wash';
import { useAsync } from '../hooks/useAsync';
import { briefGist } from '../i18n/messages';
import { useLocale, useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { dateTime, longDate, type Bilingual } from '../lib/format';
import { villageLabel } from '../lib/places';
import { addDays, istDate } from '../lib/time';
import styles from './BriefPage.module.css';

interface Range {
  from: IsoDate;
  to: IsoDate;
}

function defaultRange(): Range {
  const to = istDate(new Date());
  return { from: addDays(to, -13), to };
}

function GeneratedBy({ brief }: { brief: Brief }) {
  const t = useT();
  const agent = brief.generated_by === 'agent';
  return (
    <p className={cx(styles.generated, agent ? styles.byAgent : styles.byTemplate, 'no-print')}>
      <span>
        {agent
          ? t({
              en: `Written by the AI agent (Amazon Bedrock${brief.model_id ? `, ${brief.model_id}` : ''}); every number was checked against the data.`,
              hi: `AI एजेंट ने लिखा (Amazon Bedrock${brief.model_id ? `, ${brief.model_id}` : ''}); हर संख्या आँकड़ों से जाँची गई।`,
            })
          : t({
              en: 'Built from the fixed template; every number comes from the data.',
              hi: 'तय ढाँचे (template) से बना; हर संख्या आँकड़ों से आई है।',
            })}
      </span>
      <span className={cx(styles.generatedAt, 'num')}>{t(dateTime(brief.generated_at))}</span>
    </p>
  );
}

function RangeForm({ range, onApply }: { range: Range; onApply: (r: Range) => void }) {
  const [draft, setDraft] = useState(range);
  const valid = draft.from <= draft.to;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) onApply(draft);
  };
  return (
    <form className={styles.form} onSubmit={submit}>
      <div className={styles.field}>
        <Bi as="label" htmlFor="brief-from" en="From" hi="कब से" />
        <input
          id="brief-from"
          type="date"
          value={draft.from}
          max={draft.to}
          onChange={(e) => setDraft({ ...draft, from: e.target.value })}
          required
        />
      </div>
      <div className={styles.field}>
        <Bi as="label" htmlFor="brief-to" en="To" hi="कब तक" />
        <input
          id="brief-to"
          type="date"
          value={draft.to}
          min={draft.from}
          onChange={(e) => setDraft({ ...draft, to: e.target.value })}
          required
        />
      </div>
      <button type="submit" className="btn btn-secondary" disabled={!valid}>
        <IconRefresh />
        <Bi en="Make the sheet again" hi="पत्र फिर से बनाएँ" />
      </button>
    </form>
  );
}

const NUMBER_LABEL: Record<string, Bilingual> = {
  days: { en: 'Days in the period', hi: 'कुल दिन' },
  supplied: { en: 'Days water came', hi: 'पानी आया (दिन)' },
  partial: { en: 'Days with partial supply', hi: 'थोड़ा पानी (दिन)' },
  no_supply: { en: 'Days with no water', hi: 'पानी नहीं आया (दिन)' },
  dirty: { en: 'Days with dirty water', hi: 'गंदा पानी (दिन)' },
  unverified: { en: 'Days with too few answers', hi: 'पुष्टि नहीं (दिन)' },
  supplied_pct: { en: 'Share of days water came (%)', hi: 'पानी वाले दिन (%)' },
  households: { en: 'Registered households', hi: 'पंजीकृत घर' },
  tickets_opened: { en: 'Repair tickets opened', hi: 'खुली शिकायतें' },
  tickets_closed_verified: {
    en: 'Tickets closed after households confirmed',
    hi: 'घरों की पुष्टि से बंद शिकायतें',
  },
  median_hours_to_verified_fix: {
    en: 'Median hours to a confirmed repair',
    hi: 'पुष्ट मरम्मत में लगे घंटे (माध्यिका)',
  },
};

function numberLabel(key: string): Bilingual {
  const words = key.replace(/_/g, ' ');
  return NUMBER_LABEL[key] ?? { en: words.charAt(0).toUpperCase() + words.slice(1), hi: words };
}

function count(numbers: Brief['numbers'], key: string): number | null {
  const value = numbers[key];
  return typeof value === 'number' ? value : null;
}

function NumbersTable({ numbers }: { numbers: Brief['numbers'] }) {
  const t = useT();
  const rows = Object.entries(numbers);
  return (
    <table className={cx('data-table', styles.numbersTable)}>
      <caption>{t({ en: 'Every number the sheet uses', hi: 'पत्र में इस्तेमाल हर संख्या' })}</caption>
      <tbody>
        {rows.map(([key, value]) => (
          <tr key={key}>
            <th scope="row">{t(numberLabel(key))}</th>
            <td className="n">{value ?? '–'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * English mode: the sheet's key numbers in English, so someone who does not read the Hindi sheet
 * still gets its point. Only numbers the API returned are used.
 */
function KeyNumbers({ numbers }: { numbers: Brief['numbers'] }) {
  const t = useT();
  const days = count(numbers, 'days');
  const supplied = count(numbers, 'supplied');
  return (
    <section className={cx('board', styles.keyNumbers, 'no-print')} aria-labelledby="key-title">
      <h2 id="key-title" className={styles.keyTitle}>
        {t({ en: 'Key numbers', hi: 'मुख्य संख्याएँ' })}
      </h2>
      {days !== null && supplied !== null && (
        <p className={styles.gist}>
          {t(briefGist, {
            days,
            supplied,
            noSupply: count(numbers, 'no_supply'),
            opened: count(numbers, 'tickets_opened'),
            closed: count(numbers, 'tickets_closed_verified'),
          })}
        </p>
      )}
      {Object.keys(numbers).length > 0 && <NumbersTable numbers={numbers} />}
    </section>
  );
}

/** The Hindi evidence sheet for the Gram Sabha, ready to print on A4. */
export function BriefPage() {
  const { vid = '' } = useParams();
  const api = useApi();
  const { locale } = useLocale();
  const t = useT();
  const [range, setRange] = useState<Range>(defaultRange);
  const brief = useAsync(
    () => api.getBrief(vid, range.from, range.to),
    `brief:${vid}:${range.from}:${range.to}`,
  );
  const village = useAsync(() => api.getVillage(vid), `village:${vid}`);
  const villageHi = village.data ? villageLabel(village.data.village, 'hi') : vid;

  return (
    <div className={cx('page', styles.page)}>
      <Link to={`/villages/${encodeURIComponent(vid)}`} className="backlink no-print">
        <IconBack />
        <Bi en="Village record" hi="गाँव का हिसाब" />
      </Link>
      <header className={cx(styles.header, 'no-print')}>
        <div className={cx(styles.band, 'has-wash')}>
          <Wash seed={`${vid}:brief`} tone="jal" bleed />
          <Bi as="h1" en="Gram Sabha evidence sheet" hi="ग्राम सभा साक्ष्य पत्र" className="page-title" />
          <Bi
            as="p"
            className={styles.lede}
            en="For reading out at the Gram Sabha before it decides on Har Ghar Jal (tap water in every home) certification. Every number has its source."
            hi="ग्राम सभा में पढ़ने के लिए, हर घर जल प्रमाणपत्र पर फ़ैसले से पहले। हर संख्या के साथ उसका स्रोत है।"
          />
        </div>
        <div className={styles.controls}>
          <RangeForm range={range} onApply={setRange} />
          <button type="button" className="btn btn-primary" onClick={() => window.print()} disabled={!brief.data}>
            <IconPrint />
            <Bi en="Print" hi="प्रिंट करें" />
          </button>
        </div>
      </header>

      {brief.loading && !brief.data && <Loading label={{ en: 'Preparing the sheet', hi: 'पत्र बन रहा है' }} />}
      {brief.error ? <ErrorNote error={brief.error} onRetry={brief.reload} /> : null}
      {brief.data && (
        <>
          <GeneratedBy brief={brief.data} />
          {locale === 'en' && <KeyNumbers numbers={brief.data.numbers} />}
          {locale === 'en' && (
            <p className={cx(styles.printedNote, 'no-print')}>
              {t({
                en: 'Printed in Hindi for the Gram Sabha:',
                hi: 'ग्राम सभा के लिए हिन्दी में छपता है:',
              })}
            </p>
          )}
          <article className={styles.sheet} lang="hi" aria-label="ग्राम सभा साक्ष्य पत्र (Gram Sabha evidence sheet)">
            <Markdown source={brief.data.markdown_hi} />
            <footer className={styles.sources}>
              <h2 className={styles.sourcesTitle}>स्रोत</h2>
              <ol>
                {brief.data.sources.map((s, i) => (
                  <li key={`${s.source}-${i}`}>
                    <SourceBadge source={s} locale="hi" />
                  </li>
                ))}
              </ol>
              <p className={styles.printNote}>
                {villageHi}, {longDate(range.from).hi} से {longDate(range.to).hi}।{' '}
                {brief.data.generated_by === 'agent' ? 'AI एजेंट ने लिखा' : 'तय ढाँचे से बना'},{' '}
                {dateTime(brief.data.generated_at).hi}। जल साक्षी (JalSakshi)।
              </p>
            </footer>
          </article>
          {locale === 'hi' && (
            <details className={cx(styles.numbers, 'no-print')}>
              <summary>पत्र में इस्तेमाल हुए आँकड़े</summary>
              <NumbersTable numbers={brief.data.numbers} />
            </details>
          )}
        </>
      )}
    </div>
  );
}
