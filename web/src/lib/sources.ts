/** SourceTags the console derives for numbers the API returns without one. */

import type { CheckIn, IsoDateTime, SourceTag } from '../api/types';

/**
 * Household check-in tallies come from JalSakshi's own calls. Where the API returns them without
 * a SourceTag, the console labels them here: live from phone calls, simulated in demo mode or
 * when the answers were keyed into the web-phone simulator.
 */
export function checkinSource(
  computedAt: IsoDateTime | null | undefined,
  demo: boolean,
  simulator = false,
): SourceTag {
  const at = computedAt ?? new Date().toISOString();
  let source = 'JalSakshi household check-ins';
  if (demo) source += ' (demo)';
  else if (simulator) source += ' (web-phone simulator)';
  return {
    source,
    observed_at: at,
    fetched_at: at,
    freshness: demo || simulator ? 'simulated' : 'live',
    url: null,
  };
}

/** True when any of these answers was keyed into the web-phone simulator. */
export function fromSimulator(checkins: ReadonlyArray<Pick<CheckIn, 'captured_via'>> | undefined): boolean {
  return (checkins ?? []).some((c) => c.captured_via === 'SIMULATOR');
}
