import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import type { CognitoAuth } from '../auth/cognito';
import { Bi } from '../components/Bi';
import { IconTap } from '../components/Icons';
import { Wordmark } from '../components/Layout';
import { Empty, ErrorNote, Loading } from '../components/PageState';
import { Wash } from '../components/Wash';
import { LanguageSwitcher } from '../i18n/locale';
import { cx } from '../lib/cx';
import styles from './AuthScreens.module.css';

/** A solid sheet centred on the wall, over a large neel wash; the switcher stays top right. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className={styles.frame}>
      <div className={styles.topbar}>
        <LanguageSwitcher />
      </div>
      <main className={cx(styles.stage, 'has-wash')}>
        <Wash seed="jalsakshi:sign-in" tone="jal" strength="decor" fit="slice" className={styles.backdrop} />
        <div className={styles.card}>
          <div className={styles.brand}>
            <span className={styles.mark} aria-hidden="true">
              <IconTap size={30} />
            </span>
            <Wordmark />
          </div>
          {children}
        </div>
      </main>
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
        en="The village tap, in its households' own words"
        hi="गाँव के नल का हिसाब, घरों की ज़ुबानी"
        className={styles.tagline}
      />
      <Bi
        as="p"
        en="For Panchayat Secretaries, sarpanches and pump operators."
        hi="पंचायत सचिव, सरपंच और नल जल मित्र के लिए।"
        className={styles.who}
      />
      <button type="button" className="btn btn-primary" onClick={signIn}>
        <Bi en="Sign in" hi="साइन इन करें" />
      </button>
    </Frame>
  );
}

/** Waits for the stored session to be read. */
export function Splash() {
  return (
    <Frame>
      <Loading label={{ en: 'Checking your session', hi: 'सत्र जाँच रहे हैं' }} />
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
            <Bi en="Sign in again" hi="फिर से साइन इन करें" />
          </a>
        </>
      ) : (
        <Loading label={{ en: 'Finishing sign-in', hi: 'साइन इन पूरा हो रहा है' }} />
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
        en="This console build is missing settings"
        hi="कंसोल की सेटिंग अधूरी है"
        className={styles.tagline}
      />
      <p className={styles.who} lang="en">
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
      <Bi as="h1" en="Page not found" hi="यह पन्ना नहीं मिला" className="page-title" />
      <Empty
        className={styles.notFound}
        text={{
          en: 'This address does not match a village, ticket or page in the console.',
          hi: 'यह पता कंसोल के किसी गाँव, शिकायत या पन्ने से मेल नहीं खाता।',
        }}
      >
        <Link to="/" className="btn btn-secondary">
          <Bi en="See all villages" hi="सभी गाँव देखें" />
        </Link>
      </Empty>
    </div>
  );
}
