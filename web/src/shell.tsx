/** Sign-in, the signed-in user, the village being looked at, and the top bar + four tabs. */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { Navigate, NavLink, Outlet, useNavigate, useParams } from 'react-router-dom';
import { useApi } from './api/context';
import type { Me, VillageDetail, VillageSummary } from './api/types';
import type { CognitoAuth } from './auth/cognito';
import { useAuth } from './auth/AuthContext';
import { useAsync } from './hooks/useAsync';
import { defineMessages } from './lib/text';
import { isSampleVillage } from './lib/demo';
import { Button, ErrorBox, Loading, SampleBanner } from './ui';

const m = defineMessages({
  product: 'JalSakshi',
  line: 'Know if water reached every home in your village.',
  signIn: 'Sign in',
  given: 'Your login is given by the JalSakshi team.',
  signingIn: 'Signing you in…',
  failed: 'Sign-in did not finish. Please try again.',
  home: 'Home',
  complaints: 'Complaints',
  families: 'Families',
  more: 'More',
  village: 'Village',
  notFound: 'This page does not exist.',
  goHome: 'Go to Home',
  config: 'The console is missing its settings:',
});

// ------------------------------------------------------------------ signed-in user

interface MeValue {
  me: Me;
  reload: () => void;
}

const MeContext = createContext<MeValue | null>(null);

export function useMe(): MeValue {
  const v = useContext(MeContext);
  if (!v) throw new Error('useMe needs <RequireAuth>');
  return v;
}

/** Shows the sign-in screen until there is a session, then loads /api/me. */
export function RequireAuth() {
  const { status } = useAuth();
  if (status === 'loading') return <Loading />;
  if (status === 'signed_out') return <SignInScreen />;
  return <MeLoader />;
}

function MeLoader() {
  const api = useApi();
  const state = useAsync(() => api.getMe(), 'me');
  if (state.error && !state.data) return <div className="wrap page"><ErrorBox error={state.error} onRetry={state.reload} /></div>;
  if (!state.data) return <Loading />;
  return (
    <MeContext.Provider value={{ me: state.data, reload: state.reload }}>
      <Outlet />
    </MeContext.Provider>
  );
}

export function SignInScreen() {
  const { signIn } = useAuth();
  return (
    <main className="signin">
      <h1>{m.product}</h1>
      <p>{m.line}</p>
      <Button variant="primary" onClick={signIn}>
        {m.signIn}
      </Button>
      <p className="note">{m.given}</p>
    </main>
  );
}

export function AuthCallback({ auth }: { auth: CognitoAuth | null }) {
  const navigate = useNavigate();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!auth) {
      navigate('/', { replace: true });
      return;
    }
    auth.completeSignIn().then(
      (to) => window.location.replace(to),
      () => setFailed(true),
    );
  }, [auth, navigate]);
  return <main className="signin">{failed ? <><p>{m.failed}</p><SignInButtons /></> : <p>{m.signingIn}</p>}</main>;
}

function SignInButtons() {
  const { signIn } = useAuth();
  return (
    <Button variant="primary" onClick={signIn}>
      {m.signIn}
    </Button>
  );
}

export function ConfigError({ missing }: { missing: string[] }) {
  return (
    <main className="signin">
      <p>{m.config}</p>
      <code>{missing.join(', ')}</code>
    </main>
  );
}

const LAST_KEY = 'jalsakshi.lastVillage';

function rememberVillage(vid: string): void {
  try {
    localStorage.setItem(LAST_KEY, vid);
  } catch {
    /* blocked storage */
  }
}

function lastVillage(): string | null {
  try {
    return localStorage.getItem(LAST_KEY);
  } catch {
    return null;
  }
}

/** "/" → setup on the first login, else the last (or first) village's Home. */
export function RootRedirect() {
  const { me } = useMe();
  if (me.needs_setup || me.village_ids.length === 0) return <Navigate replace to="/setup" />;
  const last = lastVillage();
  const vid = last && me.village_ids.includes(last) ? last : me.village_ids[0];
  return <Navigate replace to={`/villages/${encodeURIComponent(vid ?? '')}`} />;
}

// ------------------------------------------------------------------ the village in view

interface VillageValue {
  vid: string;
  detail: VillageDetail;
  villages: VillageSummary[];
  reload: () => void;
}

const VillageContext = createContext<VillageValue | null>(null);

export function useVillage(): VillageValue {
  const v = useContext(VillageContext);
  if (!v) throw new Error('useVillage needs <VillageLayout>');
  return v;
}

export function villageName(v: { name: string }): string {
  return v.name;
}

/** Loads the village and its siblings, then draws the top bar, the tabs and the page. */
export function VillageLayout() {
  const { vid = '' } = useParams();
  const api = useApi();
  const detail = useAsync(() => api.getVillage(vid), `village:${vid}`);
  const list = useAsync(() => api.listVillages(), 'villages');
  useEffect(() => rememberVillage(vid), [vid]);
  if (detail.error && !detail.data) {
    return (
      <Frame vid={vid} villages={[]}>
        <div className="page">
          <ErrorBox error={detail.error} onRetry={detail.reload} />
        </div>
      </Frame>
    );
  }
  if (!detail.data) return <Loading />;
  const value: VillageValue = {
    vid,
    detail: detail.data,
    villages: list.data ?? [],
    reload: detail.reload,
  };
  return (
    <VillageContext.Provider value={value}>
      <Frame vid={vid} villages={value.villages} current={detail.data}>
        <Outlet />
      </Frame>
    </VillageContext.Provider>
  );
}

function Frame({
  vid,
  villages,
  current,
  children,
}: {
  vid: string;
  villages: VillageSummary[];
  current?: VillageDetail;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const base = `/villages/${encodeURIComponent(vid)}`;
  const name = current ? villageName(current.village) : '';
  return (
    <div className="app">
      <header className="topbar no-print">
        <div className="wrap topbar-inner">
          <span className="brand">{m.product}</span>
          <div className="village-name">
            {villages.length > 1 ? (
              <select
                aria-label={m.village}
                value={vid}
                onChange={(e) => navigate(`/villages/${encodeURIComponent(e.target.value)}`)}
              >
                {villages.map((v) => (
                  <option key={v.village.id} value={v.village.id}>
                    {villageName(v.village)}
                  </option>
                ))}
              </select>
            ) : (
              name
            )}
          </div>
        </div>
      </header>
      <nav className="tabs no-print" aria-label={m.village}>
        <div className="tabs-inner">
          <NavLink to={base} end>
            {m.home}
          </NavLink>
          <NavLink to={`${base}/complaints`}>{m.complaints}</NavLink>
          <NavLink to={`${base}/families`}>{m.families}</NavLink>
          <NavLink to={`${base}/more`}>{m.more}</NavLink>
        </div>
      </nav>
      <main className="wrap">
        {isSampleVillage(vid) && <SampleBanner />}
        {children}
      </main>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="page">
      <p>{m.notFound}</p>
      <a href="/">{m.goHome}</a>
    </div>
  );
}
