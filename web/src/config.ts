/** Build-time configuration from Vite env vars (see web/.env.example). */

export type ApiMode = 'http' | 'mock';

export interface CognitoConfig {
  /** Hosted UI base, e.g. https://jalsakshi-dev.auth.ap-south-1.amazoncognito.com */
  domain: string;
  clientId: string;
  redirectUri: string;
  logoutUri: string;
  scope: string;
}

export interface AppConfig {
  mode: ApiMode;
  apiBase: string;
  cognito: CognitoConfig | null;
  /** Problems with required env vars for the chosen mode; empty when the config is usable. */
  missing: string[];
}

type Env = Record<string, string | boolean | undefined>;

const REQUIRED_HTTP = [
  'VITE_API_BASE',
  'VITE_COGNITO_DOMAIN',
  'VITE_COGNITO_CLIENT_ID',
  'VITE_REDIRECT_URI',
] as const;

function read(env: Env, key: string): string {
  const value = env[key];
  return typeof value === 'string' ? value.trim() : '';
}

/** Adds https:// when missing and drops trailing slashes. */
export function normaliseDomain(raw: string): string {
  if (!raw) return '';
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  return withScheme.replace(/\/+$/, '');
}

function isUrl(value: string): boolean {
  try {
    new URL(value);
    return true;
  } catch {
    return false;
  }
}

/** Reads and validates the env. Mock mode needs nothing; http mode needs API and Cognito. */
export function readConfig(env: Env): AppConfig {
  const mock = read(env, 'VITE_API_MODE') === 'mock' || env.MODE === 'mock';
  if (mock) return { mode: 'mock', apiBase: '', cognito: null, missing: [] };

  const missing: string[] = REQUIRED_HTTP.filter((key) => !read(env, key));
  const redirectUri = read(env, 'VITE_REDIRECT_URI');
  if (redirectUri && !isUrl(redirectUri)) missing.push('VITE_REDIRECT_URI (not a valid URL)');
  const apiBase = read(env, 'VITE_API_BASE').replace(/\/+$/, '');
  if (missing.length > 0) return { mode: 'http', apiBase, cognito: null, missing };

  return {
    mode: 'http',
    apiBase,
    missing,
    cognito: {
      domain: normaliseDomain(read(env, 'VITE_COGNITO_DOMAIN')),
      clientId: read(env, 'VITE_COGNITO_CLIENT_ID'),
      redirectUri,
      logoutUri: read(env, 'VITE_LOGOUT_URI') || new URL('/', redirectUri).toString(),
      scope: read(env, 'VITE_COGNITO_SCOPES') || 'openid email profile',
    },
  };
}

/** The router path that receives the OAuth redirect. */
export function callbackPath(config: AppConfig): string {
  if (!config.cognito) return '/auth/callback';
  return new URL(config.cognito.redirectUri).pathname || '/auth/callback';
}
