import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { CognitoAuth, SessionUser } from './cognito';

/** `disabled` means mock mode: no sign-in at all. */
export type AuthStatus = 'loading' | 'signed_in' | 'signed_out' | 'disabled';

export interface AuthValue {
  status: AuthStatus;
  user: SessionUser | null;
  signIn: () => void;
  signOut: () => void;
}

/** Fired by the API client on a 401, so the console asks the user to sign in again. */
export const UNAUTHORIZED_EVENT = 'jalsakshi:unauthorized';

const DEMO_USER: SessionUser = { name: 'डेमो उपयोगकर्ता (Demo user)', email: null };

const AuthContext = createContext<AuthValue | null>(null);

function currentPath(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export function AuthProvider({ auth, children }: { auth: CognitoAuth | null; children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(auth ? 'loading' : 'disabled');
  const [user, setUser] = useState<SessionUser | null>(auth ? null : DEMO_USER);

  useEffect(() => {
    if (!auth) return;
    let live = true;
    auth
      .getUser()
      .then((u) => {
        if (!live) return;
        setUser(u);
        setStatus(u ? 'signed_in' : 'signed_out');
      })
      .catch(() => live && setStatus('signed_out'));
    const onUnauthorized = () => {
      void auth.forget().finally(() => {
        setUser(null);
        setStatus('signed_out');
      });
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      live = false;
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, [auth]);

  const signIn = useCallback(() => {
    void auth?.signIn(currentPath());
  }, [auth]);

  const signOut = useCallback(() => {
    void auth?.signOut();
  }, [auth]);

  const value = useMemo(() => ({ status, user, signIn, signOut }), [status, user, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
