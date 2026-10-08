import { useEffect, useRef } from 'react';

/**
 * Calls `tick` now and then every `intervalMs` while `enabled`. Later ticks are skipped while
 * the tab is hidden and catch up as soon as it is visible again.
 */
export function usePolling(tick: () => void, intervalMs: number, enabled = true): void {
  const tickRef = useRef(tick);
  tickRef.current = tick;

  useEffect(() => {
    if (!enabled) return;
    const run = () => {
      if (!document.hidden) tickRef.current();
    };
    tickRef.current();
    const timer = window.setInterval(run, intervalMs);
    document.addEventListener('visibilitychange', run);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', run);
    };
  }, [intervalMs, enabled]);
}
