import type { SourceTag } from '../api/types';
import { useLocale, type Locale } from '../i18n/locale';
import { cx } from '../lib/cx';
import { dateTime, relative, shortDate, type Bilingual } from '../lib/format';
import { FRESHNESS_LABEL } from '../lib/labels';
import { sourceName } from '../lib/sources';
import { istDate } from '../lib/time';
import styles from './SourceBadge.module.css';

/**
 * Where a number came from and how fresh it is: a printed tag on register paper, next to every
 * number in the console. Simulated and replayed data get a dashed, hatched edge so they never
 * pass for live data.
 */
export function SourceBadge({
  source,
  className,
  locale: forced,
}: {
  source: SourceTag;
  className?: string;
  /** Pin the language, e.g. Hindi on the printed Gram Sabha sheet. */
  locale?: Locale;
}) {
  const { locale: chosen } = useLocale();
  const locale = forced ?? chosen;
  const t = (m: Bilingual) => m[locale];
  const fresh = t(FRESHNESS_LABEL[source.freshness]);
  const name = t(sourceName(source.source));
  const asOf = source.observed_at ? t(shortDate(istDate(new Date(source.observed_at)))) : null;
  const fetched = t(relative(source.fetched_at));
  const when = asOf
    ? t({ en: `as on ${asOf}`, hi: `${asOf} की स्थिति` })
    : t({ en: `fetched ${fetched}`, hi: `${fetched} लिया` });
  const title = t({
    en: `${name}. Freshness: ${fresh}. Fetched ${dateTime(source.fetched_at).en}.`,
    hi: `${name}। ताज़गी: ${fresh}। ${dateTime(source.fetched_at).hi} को लिया।`,
  });
  return (
    <span className={cx(styles.badge, styles[source.freshness], className)} title={title} lang={locale}>
      <span className={styles.mark} aria-hidden="true" />
      <span className={styles.text}>
        <span className={styles.source}>
          <span className="visually-hidden">{t({ en: 'Source: ', hi: 'स्रोत: ' })}</span>
          {source.url ? (
            <a href={source.url} target="_blank" rel="noreferrer noopener">
              {name}
            </a>
          ) : (
            name
          )}
        </span>
        <span className={styles.meta}>
          {fresh}, {when}
        </span>
      </span>
    </span>
  );
}
