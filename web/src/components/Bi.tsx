import type { Bilingual } from '../lib/format';
import { cx } from '../lib/cx';

type Tag = 'span' | 'p' | 'h1' | 'h2' | 'h3' | 'div' | 'strong' | 'dt' | 'dd' | 'legend' | 'label';

interface BiProps {
  /** Either a label pair or explicit hi/en strings. */
  t?: Bilingual;
  hi?: string;
  en?: string;
  as?: Tag;
  /** One line, "हिंदी / English", instead of stacked. */
  inline?: boolean;
  className?: string;
  id?: string;
  htmlFor?: string;
}

/** Hindi first, English below in smaller type. Each half carries its own `lang`. */
export function Bi({ t, hi, en, as: Tag = 'span', inline = false, className, id, htmlFor }: BiProps) {
  const textHi = t?.hi ?? hi ?? '';
  const textEn = t?.en ?? en ?? '';
  const extra = Tag === 'label' && htmlFor ? { htmlFor } : {};
  return (
    <Tag id={id} className={cx('bi', inline && 'bi-inline', className)} {...extra}>
      <span lang="hi" className="bi-hi">
        {textHi}
      </span>
      {textEn && (
        <span lang="en" className="bi-en">
          {textEn}
        </span>
      )}
    </Tag>
  );
}
