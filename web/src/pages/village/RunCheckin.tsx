import { useState } from 'react';
import { PolicyDeniedError } from '../../api/client';
import { useApi } from '../../api/context';
import type { PolicyDenied, RunCheckinResponse } from '../../api/types';
import { Bi } from '../../components/Bi';
import { IconCheck, IconPlay } from '../../components/Icons';
import { ErrorNote } from '../../components/PageState';
import { PolicyDenial } from '../../components/PolicyDenial';
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
      <div className={styles.confirm} role="group" aria-label="Confirm check-in run">
        <Bi
          hi={`अभी ${households} घरों को कॉल जाएगा। आज जिन्हें कॉल हो चुका, उन्हें छोड़ दिया जाएगा।`}
          en={`This calls ${households} households now. Anyone already called today is skipped.`}
        />
        <div className={styles.confirmActions}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={run}
            disabled={step.kind === 'running'}
          >
            <IconPlay />
            <Bi
              hi={step.kind === 'running' ? 'शुरू हो रहा है' : 'हाँ, कॉल शुरू करें'}
              en={step.kind === 'running' ? 'Starting' : 'Yes, start calls'}
            />
          </button>
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => setStep({ kind: 'idle' })}
            disabled={step.kind === 'running'}
          >
            <Bi hi="रुकें" en="Cancel" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.run}>
      <button type="button" className="btn btn-primary" onClick={() => setStep({ kind: 'confirm' })}>
        <IconPlay />
        <Bi hi="अभी जाँच कॉल चलाएँ" en="Run check-in now" />
      </button>
      {step.kind === 'started' && (
        <p className={styles.started} role="status">
          <IconCheck size={20} />
          <span>
            <Bi
              hi="जाँच कॉल शुरू हो गए। नतीजे गतिविधि में दिखेंगे।"
              en="Check-in calls started. Results appear in Activity."
            />
            <span className={styles.arn}>
              Step Functions CheckInRun: <span>{step.result.execution_arn}</span>
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
