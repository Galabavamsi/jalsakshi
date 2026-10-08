import type { ReactNode } from 'react';
import { ApiError, PolicyDeniedError } from '../api/client';
import type { Bilingual } from '../lib/format';
import { cx } from '../lib/cx';
import { Bi } from './Bi';
import { IconRefresh } from './Icons';
import { PolicyDenial } from './PolicyDenial';
import styles from './PageState.module.css';

/** Plain-language explanation of a failed request: what failed and what to do about it. */
export function describeError(error: unknown): Bilingual {
  if (error instanceof ApiError) {
    if (error.code === 'network') {
      return {
        en: 'Could not reach the JalSakshi API. Check the connection and try again.',
        hi: 'सर्वर तक नहीं पहुँच पाए। इंटरनेट देखकर फिर कोशिश करें।',
      };
    }
    if (error.code === 'timeout') {
      return {
        en: `${error.message} Try again in a moment.`,
        hi: 'सर्वर ने समय पर जवाब नहीं दिया। थोड़ी देर में फिर कोशिश करें।',
      };
    }
    if (error.status === 401) {
      return { en: 'Your session ended. Sign in again.', hi: 'आपका सत्र ख़त्म हो गया। फिर से साइन इन करें।' };
    }
    if (error.status === 404) {
      return { en: `${error.message} Check the link, or go back to all villages.`, hi: 'यह जानकारी नहीं मिली। लिंक जाँचें या सभी गाँव पर लौटें।' };
    }
    return { en: `The request did not complete: ${error.message}`, hi: 'अनुरोध पूरा नहीं हुआ।' };
  }
  return {
    en: error instanceof Error ? `Something went wrong: ${error.message}` : 'Something went wrong. Try again.',
    hi: 'कुछ ग़लत हो गया। फिर कोशिश करें।',
  };
}

export function Loading({ label }: { label?: Bilingual }) {
  return (
    <div className={styles.loading} role="status" aria-live="polite">
      <span className={styles.drip} aria-hidden="true" />
      <Bi t={label ?? { en: 'Loading', hi: 'जानकारी आ रही है' }} />
    </div>
  );
}

function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button type="button" className="btn btn-quiet" onClick={onRetry}>
      <IconRefresh />
      <Bi en="Try again" hi="फिर से कोशिश करें" />
    </button>
  );
}

/**
 * A failed request in plain words. A Cedar deny (403 with a reason) is not a failure: it is shown
 * as the rule's notice, with the same retry button.
 */
export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof PolicyDeniedError) {
    return (
      <PolicyDenial denied={error.denied} focusOnShow={false}>
        {onRetry && <RetryButton onRetry={onRetry} />}
      </PolicyDenial>
    );
  }
  const text = describeError(error);
  return (
    <div className={styles.error} role="alert">
      <Bi t={text} className={styles.errorText} />
      {onRetry && <RetryButton onRetry={onRetry} />}
    </div>
  );
}

/** Nothing here yet: a dry-brush outline, what will appear, and the next action. */
export function Empty({ text, children, className }: { text: Bilingual; children?: ReactNode; className?: string }) {
  return (
    <div className={cx(styles.empty, 'dry', className)}>
      <Bi t={text} as="p" />
      {children}
    </div>
  );
}
