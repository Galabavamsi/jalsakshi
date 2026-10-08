import { useMemo } from 'react';
import { cx } from '../lib/cx';
import { renderMarkdown } from '../lib/markdown';
import styles from './Markdown.module.css';

/** Renders a Hindi markdown document in the printed-sheet style. */
export function Markdown({ source, className }: { source: string; className?: string }) {
  const html = useMemo(() => renderMarkdown(source), [source]);
  // renderMarkdown escapes raw HTML and unsafe links, so the output is safe to inject.
  return <div lang="hi" className={cx(styles.doc, className)} dangerouslySetInnerHTML={{ __html: html }} />;
}
