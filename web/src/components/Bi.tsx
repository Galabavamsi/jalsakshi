import type { Bilingual } from '../lib/format';
import { useLocale } from '../i18n/locale';

type Tag = 'span' | 'p' | 'h1' | 'h2' | 'h3' | 'div' | 'strong' | 'dt' | 'dd' | 'legend' | 'label';

interface BiProps {
  /** Either a label pair or explicit en/hi strings. */
  t?: Bilingual;
  en?: string;
  hi?: string;
  as?: Tag;
  /** Kept for old call sites; text is always one language now. */
  inline?: boolean;
  className?: string;
  id?: string;
  htmlFor?: string;
}

/**
 * Text in the console's chosen language (English by default, Hindi from the switcher).
 * One element, one language, carrying its own `lang` so screen readers pronounce it right.
 */
export function Bi({ t, hi, en, as: Tag = 'span', className, id, htmlFor }: BiProps) {
  const { locale } = useLocale();
  const textEn = t?.en ?? en ?? '';
  const textHi = t?.hi ?? hi ?? '';
  // A pair with one side missing still shows something, in that side's language.
  const lang = locale === 'hi' ? (textHi ? 'hi' : 'en') : textEn ? 'en' : 'hi';
  const text = lang === 'hi' ? textHi : textEn;
  const extra = Tag === 'label' && htmlFor ? { htmlFor } : {};
  return (
    <Tag id={id} lang={lang} className={className} {...extra}>
      {text}
    </Tag>
  );
}
