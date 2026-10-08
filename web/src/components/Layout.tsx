import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { isMock } from '../appConfig';
import { useAuth } from '../auth/AuthContext';
import { LanguageSwitcher, useLocale, useT } from '../i18n/locale';
import { cx } from '../lib/cx';
import { Bi } from './Bi';
import { IconPhone, IconPulse, IconSignOut, IconTap, IconVillage } from './Icons';
import styles from './Layout.module.css';

const NAV = [
  { to: '/', label: { en: 'Villages', hi: 'गाँव' }, Icon: IconVillage, end: true },
  { to: '/activity', label: { en: 'Activity', hi: 'गतिविधि' }, Icon: IconPulse, end: false },
  { to: '/simulator', label: { en: 'Phone simulator', hi: 'फ़ोन सिम्युलेटर' }, Icon: IconPhone, end: false },
];

/** Village pages, tickets and briefs all sit under "Villages" in the navigation. */
function underVillages(pathname: string): boolean {
  return pathname.startsWith('/villages/') || pathname.startsWith('/tickets/');
}

/** Violet hatched strip: the same mark every "not real" label in the console carries. */
export function DemoStrip() {
  return (
    <div className={cx(styles.demo, 'no-print')} role="note">
      <Bi
        en="Demo data: every village, household and number here is a sample. No real calls are placed."
        hi="डेमो डेटा: यहाँ हर गाँव, घर और संख्या नमूना है। कोई असली कॉल नहीं होता।"
      />
    </div>
  );
}

/** "JalSakshi" with "जल साक्षी" beneath (swapped in Hindi). */
export function Wordmark({ className }: { className?: string }) {
  const { locale } = useLocale();
  const latin = (
    <span lang="en" className={styles.wordLatin} translate="no">
      JalSakshi
    </span>
  );
  const deva = (
    <span lang="hi" className={styles.wordDeva} translate="no">
      जल साक्षी
    </span>
  );
  return (
    <span className={cx(styles.wordmark, locale === 'hi' && styles.wordmarkHi, className)}>
      {locale === 'hi' ? (
        <>
          {deva}
          {latin}
        </>
      ) : (
        <>
          {latin}
          {deva}
        </>
      )}
    </span>
  );
}

function Account() {
  const { status, user, signOut } = useAuth();
  const t = useT();
  if (!user) return null;
  const name = status === 'disabled' ? t({ en: 'Demo user', hi: 'डेमो उपयोगकर्ता' }) : user.name;
  const signOutLabel = t({ en: 'Sign out', hi: 'साइन आउट' });
  return (
    <div className={styles.account}>
      <span className={styles.userName}>{name}</span>
      {status === 'signed_in' && (
        <button
          type="button"
          className={cx('btn btn-quiet', styles.signOut)}
          onClick={signOut}
          aria-label={signOutLabel}
        >
          <IconSignOut size={20} />
          <span className={styles.signOutText}>{signOutLabel}</span>
        </button>
      )}
    </div>
  );
}

/** Page chrome: brand, navigation (a bottom bar on phones), the language switcher and the demo label. */
export function Layout() {
  const { pathname } = useLocation();
  const t = useT();
  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">
        {t({ en: 'Skip to content', hi: 'सामग्री पर जाएँ' })}
      </a>
      <header className={cx(styles.banner, 'no-print')}>
        {isMock && <DemoStrip />}
        <div className={styles.header}>
          <Link to="/" className={styles.brand} aria-label={t({ en: 'JalSakshi, home', hi: 'जल साक्षी, मुख्य पन्ना' })}>
            <span className={styles.mark} aria-hidden="true">
              <IconTap size={24} />
            </span>
            <Wordmark />
          </Link>
          <nav aria-label={t({ en: 'Main', hi: 'मुख्य' })} className={styles.nav}>
            <ul>
              {NAV.map(({ to, label, Icon, end }) => (
                <li key={to}>
                  <NavLink
                    to={to}
                    end={end}
                    className={({ isActive }) =>
                      cx(
                        styles.navLink,
                        (isActive || (to === '/' && underVillages(pathname))) && styles.active,
                      )
                    }
                  >
                    <Icon size={22} />
                    <Bi t={label} />
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className={styles.tools}>
            <LanguageSwitcher />
            <Account />
          </div>
        </div>
      </header>
      <main id="main" className={styles.main} tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
