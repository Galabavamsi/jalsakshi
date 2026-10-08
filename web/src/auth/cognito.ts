/**
 * Cognito Hosted UI sign-in with OAuth2 authorization code + PKCE (oidc-client-ts).
 *
 * Endpoints are built from the Hosted UI domain, so no user pool id is needed in the browser.
 * Tokens live in sessionStorage and are refreshed with the refresh token.
 */

import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts';
import type { CognitoConfig } from '../config';

export interface SessionUser {
  name: string;
  email: string | null;
}

export interface CognitoAuth {
  /** Returns a valid access token, refreshing it if needed; null when signed out. */
  getAccessToken(): Promise<string | null>;
  getUser(): Promise<SessionUser | null>;
  signIn(returnTo: string): Promise<void>;
  /** Finishes the redirect; returns the path the user was on before signing in. */
  completeSignIn(): Promise<string>;
  signOut(): Promise<void>;
  /** Drops the local session, e.g. after the API answers 401. */
  forget(): Promise<void>;
}

interface SignInState {
  returnTo?: string;
}

function createManager(cfg: CognitoConfig): UserManager {
  const d = cfg.domain;
  return new UserManager({
    authority: d,
    metadata: {
      issuer: d,
      authorization_endpoint: `${d}/oauth2/authorize`,
      token_endpoint: `${d}/oauth2/token`,
      userinfo_endpoint: `${d}/oauth2/userInfo`,
      revocation_endpoint: `${d}/oauth2/revoke`,
      end_session_endpoint: `${d}/logout`,
    },
    client_id: cfg.clientId,
    redirect_uri: cfg.redirectUri,
    post_logout_redirect_uri: cfg.logoutUri,
    response_type: 'code',
    scope: cfg.scope,
    loadUserInfo: false,
    automaticSilentRenew: true,
    monitorSession: false,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}

function toSessionUser(user: User): SessionUser {
  const p = user.profile;
  const email = typeof p.email === 'string' ? p.email : null;
  const name =
    (typeof p.name === 'string' && p.name) ||
    (typeof p['cognito:username'] === 'string' && (p['cognito:username'] as string)) ||
    email ||
    'Operator';
  return { name, email };
}

/** Builds the auth helper around one UserManager. */
export function createCognitoAuth(cfg: CognitoConfig): CognitoAuth {
  const manager = createManager(cfg);
  let refreshing: Promise<User | null> | null = null;

  async function refresh(): Promise<User | null> {
    try {
      return await manager.signinSilent();
    } catch {
      await manager.removeUser();
      return null;
    }
  }

  async function currentUser(): Promise<User | null> {
    const user = await manager.getUser();
    if (!user) return null;
    if (!user.expired) return user;
    if (!user.refresh_token) return null;
    refreshing ??= refresh().finally(() => {
      refreshing = null;
    });
    return refreshing;
  }

  return {
    async getAccessToken() {
      return (await currentUser())?.access_token ?? null;
    },
    async getUser() {
      const user = await currentUser();
      return user ? toSessionUser(user) : null;
    },
    async signIn(returnTo) {
      const state: SignInState = { returnTo };
      await manager.signinRedirect({ state });
    },
    async completeSignIn() {
      const user = await manager.signinRedirectCallback();
      const state = (user.state ?? {}) as SignInState;
      return state.returnTo && state.returnTo.startsWith('/') ? state.returnTo : '/';
    },
    async signOut() {
      try {
        await manager.revokeTokens(['refresh_token']);
      } catch {
        // Revocation is best effort; the local session is removed either way.
      }
      await manager.removeUser();
      const url = new URL(`${cfg.domain}/logout`);
      url.searchParams.set('client_id', cfg.clientId);
      url.searchParams.set('logout_uri', cfg.logoutUri);
      window.location.assign(url.toString());
    },
    async forget() {
      await manager.removeUser();
    },
  };
}
