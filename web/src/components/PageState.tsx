import type { ReactNode } from 'react';
import { ApiError, PolicyDeniedError } from '../api/client';
import type { Bilingual } from '../lib/format';
import { Bi } from './Bi';
import { IconRefresh } from './Icons';
import { PolicyDenial } from './PolicyDenial';
import styles from './PageState.module.css';

/** Plain-language explanation of a failed request. */
export function describeError(error: unknown): Bilingual {
  if (error instanceof ApiError) {
    if (error.code === 'network') {
      return {
        hi: 'सर्वर तक नहीं पहुँच पाए। इंटरनेट देखकर फिर कोशिश करें।',
        en: 'Could not reach the JalSakshi API. Check the connection and try again.',
      };
    }
    if (error.code === 'timeout') {
      return { hi: 'सर्वर ने समय पर जवाब नहीं दिया।', en: error.message };
    }
    if (error.status === 401) {
      return { hi: 'आपका सत्र ख़त्म हो गया। फिर से साइन इन करें।', en: 'Your session ended. Sign in again.' };
    }
    if (error.status === 404) {
      return { hi: 'यह जानकारी नहीं मिली।', en: error.message };
    }
    return { hi: 'अनुरोध पूरा नहीं हुआ।', en: error.message };
  }
  return { hi: 'कुछ ग़लत हो गया।', en: error instanceof Error ? error.message : 'Unexpected error.' };
}

export function Loading({ label }: { label?: Bilingual }) {
  return (
    <div className={styles.loading} role="status" aria-live="polite">
      <span className={styles.drip} aria-hidden="true" />
      <Bi t={label ?? { hi: 'जानकारी आ रही है', en: 'Loading' }} />
    </div>
  );
}

function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button type="button" className="btn btn-quiet" onClick={onRetry}>
      <IconRefresh />
      <Bi hi="फिर से कोशिश करें" en="Try again" />
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
      <PolicyDenial denied={error.denied}>{onRetry && <RetryButton onRetry={onRetry} />}</PolicyDenial>
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

export function Empty({ text, children }: { text: Bilingual; children?: ReactNode }) {
  return (
    <div className={styles.empty}>
      <Bi t={text} />
      {children}
    </div>
  );
}
