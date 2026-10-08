import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import type { CognitoAuth } from '../auth/cognito';
import { Bi } from '../components/Bi';
import { IconTap } from '../components/Icons';
import { ErrorNote, Loading } from '../components/PageState';
import styles from './AuthScreens.module.css';

function Frame({ children }: { children: ReactNode }) {
  return (
    <div className={styles.frame}>
      <div className={styles.card}>
        <span className={styles.mark} aria-hidden="true">
          <IconTap size={34} />
        </span>
        <p className={styles.word} lang="hi">
          जल साक्षी
        </p>
        {children}
      </div>
    </div>
  );
}

/** Shown to signed-out operators. Sign-in happens on the Cognito Hosted UI. */
export function SignInScreen() {
  const { signIn } = useAuth();
  return (
    <Frame>
      <Bi
        as="h1"
        hi="गाँव के नल का हिसाब, घरों की ज़ुबानी"
        en="The village tap, in its households' own words"
        className={styles.tagline}
      />
      <Bi
        hi="पंचायत सचिव, सरपंच और नल जल मित्र के लिए।"
        en="For Panchayat Secretaries, sarpanches and pump operators."
        className={styles.who}
      />
      <button type="button" className="btn btn-primary" onClick={signIn}>
        <Bi hi="साइन इन करें" en="Sign in" />
      </button>
    </Frame>
  );
}

/** Waits for the stored session to be read. */
export function Splash() {
  return (
    <Frame>
      <Loading label={{ hi: 'सत्र जाँच रहे हैं', en: 'Checking your session' }} />
    </Frame>
  );
}

/** OAuth redirect target: exchanges the code (PKCE) and returns to where the user was. */
export function AuthCallback({ auth }: { auth: CognitoAuth | null }) {
  const started = useRef(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!auth || started.current) return;
    started.current = true;
    auth
      .completeSignIn()
      .then((returnTo) => window.location.replace(returnTo))
      .catch((e: unknown) => setError(e));
  }, [auth]);

  if (!auth) return <Navigate to="/" replace />;
  return (
    <Frame>
      {error ? (
        <>
          <ErrorNote error={error} />
          <a className="btn btn-secondary" href="/">
            <Bi hi="फिर से साइन इन करें" en="Sign in again" />
          </a>
        </>
      ) : (
        <Loading label={{ hi: 'साइन इन पूरा हो रहा है', en: 'Finishing sign-in' }} />
      )}
    </Frame>
  );
}

/** The build is missing env vars for real mode. */
export function ConfigError({ missing }: { missing: string[] }) {
  return (
    <Frame>
      <Bi
        as="h1"
        hi="कंसोल की सेटिंग अधूरी है"
        en="This console build is missing settings"
        className={styles.tagline}
      />
      <p className={styles.who}>
        Set these in <code>web/.env.local</code> and rebuild, or run <code>pnpm dev:mock</code> for
        demo data:
      </p>
      <ul className={styles.missing}>
        {missing.map((m) => (
          <li key={m}>
            <code>{m}</code>
          </li>
        ))}
      </ul>
    </Frame>
  );
}

export function NotFound() {
  return (
    <div className="page">
      <Bi as="h1" hi="यह पन्ना नहीं मिला" en="Page not found" className={styles.notFound} />
      <p>
        <Link to="/">
          <Bi inline hi="सभी गाँव देखें" en="See all villages" />
        </Link>
      </p>
    </div>
  );
}
