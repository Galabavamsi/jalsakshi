import { Fragment } from 'react';
import { useLocale } from '../i18n/locale';

/** One run of Devanagari (words, spaces and punctuation between them). */
const DEVANAGARI_RUN = /([ऀ-ॿ](?:[ऀ-ॿ\s.,]*[ऀ-ॿ])?)/;

/**
 * Text that mixes a Devanagari name into an English line ("रमेश साहू, Pump operator"): in English
 * mode each Devanagari run gets its own lang="hi", so screen readers switch voice for the name
 * (WCAG 3.1.2). In Hindi mode the text is already in the page language and renders as is.
 */
export function LangRuns({ text }: { text: string }) {
  const { locale } = useLocale();
  if (locale === 'hi' || !DEVANAGARI_RUN.test(text)) return <>{text}</>;
  return (
    <>
      {text.split(DEVANAGARI_RUN).map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} lang="hi" className="name-hi">
            {part}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}
