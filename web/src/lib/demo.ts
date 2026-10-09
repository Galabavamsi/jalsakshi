/** Sample data and the mock console user. */

import type { MockUser } from '../api/mock';
import type { OperatorRole } from '../api/types';

/** The labelled sample village (example data) has an id starting with "sample-". */
export function isSampleVillage(vid: string | null | undefined): boolean {
  return !!vid && vid.startsWith('sample-');
}

/** sessionStorage key for the mock console user. */
export const MOCK_USER_KEY = 'jalsakshi.mockUser';

export interface MockIdentity {
  user: MockUser;
  role: OperatorRole;
}

const CHOICES: Record<string, MockIdentity> = {
  admin: { user: 'admin', role: 'PANCHAYAT_SECRETARY' },
  new: { user: 'new', role: 'PANCHAYAT_SECRETARY' },
  sarpanch: { user: 'member', role: 'SARPANCH' },
  secretary: { user: 'member', role: 'PANCHAYAT_SECRETARY' },
};

/**
 * Mock mode only: who is signed in. Default: an admin who sees the sample village.
 * `?as=new` is a fresh account that must set up its village; `?as=sarpanch` can approve
 * announcements. The choice is kept for the browser tab.
 */
export function mockIdentityFromUrl(
  search: string,
  storage: Pick<Storage, 'getItem' | 'setItem'> | null,
): MockIdentity {
  const asked = new URLSearchParams(search).get('as')?.toLowerCase();
  try {
    if (asked && CHOICES[asked]) {
      storage?.setItem(MOCK_USER_KEY, asked);
      return CHOICES[asked];
    }
    const stored = storage?.getItem(MOCK_USER_KEY);
    if (stored && CHOICES[stored]) return CHOICES[stored];
  } catch {
    /* blocked storage */
  }
  return CHOICES.admin as MockIdentity;
}
