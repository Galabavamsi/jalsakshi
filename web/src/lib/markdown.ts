/**
 * Markdown to HTML for the Gram Sabha brief. The text may come from an LLM, so raw HTML is
 * escaped, images become their alt text, and links keep only http(s) and mailto targets.
 */

import { Marked } from 'marked';

const SAFE_HREF = /^(https?:|mailto:)/i;

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const marked = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    html({ text }) {
      return escapeHtml(text);
    },
    image({ text }) {
      return escapeHtml(text);
    },
    link({ href, title, tokens }) {
      const inner = this.parser.parseInline(tokens);
      if (!SAFE_HREF.test(href.trim())) return inner;
      const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
      return `<a href="${escapeHtml(href)}"${titleAttr} target="_blank" rel="noreferrer noopener">${inner}</a>`;
    },
  },
});

/** Renders trusted-shape HTML from untrusted markdown. */
export function renderMarkdown(source: string): string {
  return marked.parse(source, { async: false });
}
