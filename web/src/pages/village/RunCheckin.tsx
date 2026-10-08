import { useState } from 'react';
import { PolicyDeniedError } from '../../api/client';
import { useApi } from '../../api/context';
import type { PolicyDenied, RunCheckinResponse } from '../../api/types';
import { Bi } from '../../components/Bi';
import { IconCheck, IconPlay } from '../../components/Icons';
import { ErrorNote } from '../../components/PageState';
import { PolicyDenial } from '../../components/PolicyDenial';
import { runCheckinConfirm } from '../../i18n/messages';
import { useT } from '../../i18n/locale';
import styles from './VillageDetail.module.css';

type Step =
  | { kind: 'idle' }
  | { kind: 'confirm' }
  | { kind: 'running' }
  | { kind: 'started'; result: RunCheckinResponse }
  | { kind: 'denied'; denied: PolicyDenied }
  | { kind: 'error'; error: unknown };

/** "Run check-in now": asks once, then starts the CheckInRun state machine. */
export function RunCheckin({ villageId, households }: { villageId: string; households: number }) {
  const api = useApi();
  const t = useT();
  const [step, setStep] = useState<Step>({ kind: 'idle' });

  async function run() {
    setStep({ kind: 'running' });
    try {
      setStep({ kind: 'started', result: await api.runCheckin(villageId) });
    } catch (error) {
      if (error instanceof PolicyDeniedError) setStep({ kind: 'denied', denied: error.denied });
      else setStep({ kind: 'error', error });
    }
  }

  if (step.kind === 'confirm' || step.kind === 'running') {
    return (
      <div
        className={styles.confirm}
        role="group"
        aria-label={t({ en: 'Confirm check-in run', hi: 'जाँच कॉल की पुष्टि' })}
      >
        <p>{t(runCheckinConfirm, { n: households })}</p>
        <div className={styles.confirmActions}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={run}
            disabled={step.kind === 'running'}
          >
            <IconPlay />
            <Bi
              en={step.kind === 'running' ? 'Starting' : 'Yes, start calls'}
              hi={step.kind === 'running' ? 'शुरू हो रहा है' : 'हाँ, कॉल शुरू करें'}
            />
          </button>
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => setStep({ kind: 'idle' })}
            disabled={step.kind === 'running'}
          >
            <Bi en="Cancel" hi="रुकें" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.run}>
      <button type="button" className="btn btn-primary" onClick={() => setStep({ kind: 'confirm' })}>
        <IconPlay />
        <Bi en="Run check-in now" hi="अभी जाँच कॉल चलाएँ" />
      </button>
      {step.kind === 'started' && (
        <p className={styles.started} role="status">
          <IconCheck size={20} />
          <span>
            <Bi
              en="Check-in calls started. Results appear in Activity."
              hi="जाँच कॉल शुरू हो गए। नतीजे गतिविधि में दिखेंगे।"
            />
            <span className={styles.arn}>
              <span lang="en">Step Functions CheckInRun</span>: <code translate="no">{step.result.execution_arn}</code>
            </span>
          </span>
        </p>
      )}
      {step.kind === 'denied' && (
        <PolicyDenial denied={step.denied} onDismiss={() => setStep({ kind: 'idle' })} />
      )}
      {step.kind === 'error' && <ErrorNote error={step.error} onRetry={run} />}
    </div>
  );
}
