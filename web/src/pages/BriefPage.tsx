import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useApi } from '../api/context';
import type { Brief, IsoDate } from '../api/types';
import { Bi } from '../components/Bi';
import { IconBack, IconPrint, IconRefresh } from '../components/Icons';
import { ErrorNote, Loading } from '../components/PageState';
import { Markdown } from '../components/Markdown';
import { SourceBadge } from '../components/SourceBadge';
import { useAsync } from '../hooks/useAsync';
import { cx } from '../lib/cx';
import { dateTime } from '../lib/format';
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
  const at = dateTime(brief.generated_at);
  const agent = brief.generated_by === 'agent';
  return (
    <p className={cx(styles.generated, agent ? styles.byAgent : styles.byTemplate)}>
      <Bi
        hi={agent ? 'AI एजेंट ने लिखा, हर संख्या आँकड़ों से जाँची गई' : 'तय ढाँचे (template) से बना'}
        en={
          agent
            ? `Written by the AI agent (Amazon Bedrock${brief.model_id ? `, ${brief.model_id}` : ''}); every number was checked against the data`
            : 'Built from the fixed template'
        }
      />
      <span className={styles.generatedAt}>
        <span lang="hi">{at.hi}</span> <span lang="en">({at.en})</span>
      </span>
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
        <Bi as="label" htmlFor="brief-from" hi="कब से" en="From" />
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
        <Bi as="label" htmlFor="brief-to" hi="कब तक" en="To" />
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
        <Bi hi="पत्र फिर से बनाएँ" en="Make the sheet again" />
      </button>
    </form>
  );
}

function Numbers({ numbers }: { numbers: Brief['numbers'] }) {
  const rows = Object.entries(numbers);
  if (rows.length === 0) return null;
  return (
    <details className={styles.numbers}>
      <summary>
        <Bi inline hi="पत्र में इस्तेमाल हुए आँकड़े" en="Numbers used in this sheet" />
      </summary>
      <table>
        <tbody>
          {rows.map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{key.replace(/_/g, ' ')}</th>
              <td className="num">{value ?? 'null'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** The Hindi evidence sheet for the Gram Sabha, ready to print on A4. */
export function BriefPage() {
  const { vid = '' } = useParams();
  const api = useApi();
  const [range, setRange] = useState<Range>(defaultRange);
  const brief = useAsync(
    () => api.getBrief(vid, range.from, range.to),
    `brief:${vid}:${range.from}:${range.to}`,
  );

  return (
    <div className={cx('page', styles.page)}>
      <Link to={`/villages/${encodeURIComponent(vid)}`} className="backlink no-print">
        <IconBack />
        <Bi inline hi="गाँव का हिसाब" en="Village record" />
      </Link>
      <header className={cx(styles.header, 'no-print')}>
        <Bi as="h1" hi="ग्राम सभा साक्ष्य पत्र" en="Gram Sabha evidence sheet" className={styles.title} />
        <Bi
          hi="ग्राम सभा में पढ़ने और हर घर जल प्रमाणपत्र पर फ़ैसले के लिए। हर संख्या के साथ उसका स्रोत है।"
          en="To read out at the Gram Sabha before deciding on Har Ghar Jal certification. Every number has its source."
          className={styles.lede}
        />
        <div className={styles.controls}>
          <RangeForm range={range} onApply={setRange} />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => window.print()}
            disabled={!brief.data}
          >
            <IconPrint />
            <Bi hi="प्रिंट करें" en="Print" />
          </button>
        </div>
      </header>

      {brief.loading && !brief.data && <Loading label={{ hi: 'पत्र बन रहा है', en: 'Preparing the sheet' }} />}
      {brief.error ? <ErrorNote error={brief.error} onRetry={brief.reload} /> : null}
      {brief.data && (
        <>
          <GeneratedBy brief={brief.data} />
          <article className={styles.sheet} aria-label="Gram Sabha evidence sheet">
            <Markdown source={brief.data.markdown_hi} />
            <footer className={styles.sources}>
              <Bi as="h2" hi="स्रोत" en="Sources" className={styles.sourcesTitle} />
              <ul>
                {brief.data.sources.map((s, i) => (
                  <li key={`${s.source}-${i}`}>
                    <SourceBadge source={s} />
                  </li>
                ))}
              </ul>
              <p className={styles.printNote}>
                <span lang="hi">
                  {brief.data.generated_by === 'agent' ? 'AI एजेंट ने लिखा' : 'तय ढाँचे से बना'},{' '}
                  {dateTime(brief.data.generated_at).hi}। जल साक्षी।
                </span>
              </p>
            </footer>
          </article>
          <Numbers numbers={brief.data.numbers} />
        </>
      )}
    </div>
  );
}
