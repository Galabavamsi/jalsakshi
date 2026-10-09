import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { CognitoAuth, SessionUser } from './cognito';

/** `disabled` means mock mode: no sign-in at all. */
export type AuthStatus = 'loading' | 'signed_in' | 'signed_out' | 'disabled';

export interface AuthValue {
  status: AuthStatus;
  user: SessionUser | null;
  signIn: () => void;
  signUp: () => void;
  signOut: () => void;
}

/** Fired by the API client on a 401, so the console asks the user to sign in again. */
export const UNAUTHORIZED_EVENT = 'jalsakshi:unauthorized';

const DEMO_USER: SessionUser = { name: 'Panchayat secretary', email: null };

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

  // Mock mode (no Cognito): sign out shows the sign-in screen, sign in returns, and
  // Create account starts a fresh account so the setup flow can be tried.
  const signIn = useCallback(() => {
    if (auth) void auth.signIn(currentPath());
    else setStatus('disabled');
  }, [auth]);

  const signUp = useCallback(() => {
    if (auth) void auth.signUp('/');
    else window.location.assign('/?as=new');
  }, [auth]);

  const signOut = useCallback(() => {
    if (auth) void auth.signOut();
    else setStatus('signed_out');
  }, [auth]);

  const value = useMemo(() => ({ status, user, signIn, signUp, signOut }), [status, user, signIn, signUp, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
