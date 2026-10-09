/** The few plain building blocks every page uses. Text only, no icons. */

import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, PolicyDeniedError } from './api/client';


type Variant = 'primary' | 'secondary' | 'link' | 'danger';

export function Button({
  variant = 'secondary',
  busy,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={`btn btn-${variant}${className ? ` ${className}` : ''}`}
    >
      {children}
    </button>
  );
}

export function ButtonLink({ to, variant = 'secondary', children }: { to: string; variant?: Variant; children: ReactNode }) {
  return (
    <Link to={to} className={`btn btn-${variant}`}>
      {children}
    </Link>
  );
}

export function Card({ title, children, footer }: { title?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <section className="card">
      {title && <h2 className="card-title">{title}</h2>}
      {children}
      {footer && <div className="card-footer">{footer}</div>}
    </section>
  );
}

/** The quiet grey line that says where numbers come from and how fresh they are. */
export function Note({ children }: { children: ReactNode }) {
  return <p className="note">{children}</p>;
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · JalSakshi`;
  }, [title]);
  return (
    <div className="page-head">
      <h1>{title}</h1>
      {children}
    </div>
  );
}

const loadingText = 'Loading…';

export function Loading() {
  return (
    <p className="loading" role="status">
      {loadingText}
    </p>
  );
}

const fallbackError = 'Something went wrong. Check the internet and try again.';
const retryText = 'Try again';

/** One plain sentence for any error; a policy refusal gives its own reason. */
export function useErrorText(): (err: unknown) => string {
  return (err: unknown) => {
    if (err instanceof PolicyDeniedError) return err.denied.reason_en;
    if (err instanceof ApiError && err.status >= 400 && err.status < 500) return err.message;
    return fallbackError;
  };
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const text = useErrorText();
  return (
    <div className="error-box" role="alert">
      <p>{text(error)}</p>
      {onRetry && <Button onClick={onRetry}>{retryText}</Button>}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {hint && <p className="note">{hint}</p>}
    </div>
  );
}

/** A small modal with a message and two buttons. */
export function ConfirmDialog({
  title,
  children,
  confirm,
  cancel,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirm: string;
  cancel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);
  return (
    <div className="backdrop" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={ref}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id={titleId}>{title}</h2>
        <div className="dialog-body">{children}</div>
        <div className="actions">
          <Button variant="primary" busy={busy} onClick={onConfirm}>
            {confirm}
          </Button>
          <Button onClick={onCancel}>{cancel}</Button>
        </div>
      </div>
    </div>
  );
}

const sampleText = 'Sample village — example data to show how JalSakshi works.';

export function SampleBanner() {
  return <p className="sample-banner">{sampleText}</p>;
}

