import { Link, NavLink, Outlet } from 'react-router-dom';
import { isMock } from '../appConfig';
import { useAuth } from '../auth/AuthContext';
import { cx } from '../lib/cx';
import { Bi } from './Bi';
import { IconPhone, IconPulse, IconTap, IconUser, IconVillage } from './Icons';
import styles from './Layout.module.css';

const NAV = [
  { to: '/', hi: 'गाँव', en: 'Villages', Icon: IconVillage, end: true },
  { to: '/activity', hi: 'गतिविधि', en: 'Activity', Icon: IconPulse, end: false },
  { to: '/simulator', hi: 'फ़ोन सिम्युलेटर', en: 'Phone simulator', Icon: IconPhone, end: false },
];

function DemoBanner() {
  return (
    <div className={styles.demo} role="note">
      <Bi
        inline
        hi="डेमो डेटा: इस कंसोल के सभी आँकड़े नमूना हैं और कोई असली कॉल नहीं होता।"
        en="Demo data: every number here is a sample, and no real calls are placed."
      />
    </div>
  );
}

function Account() {
  const { status, user, signOut } = useAuth();
  if (!user) return null;
  return (
    <div className={styles.account}>
      <IconUser size={20} />
      <span className={styles.userName}>{user.name}</span>
      {status === 'signed_in' && (
        <button type="button" className={cx('btn btn-quiet', styles.signOut)} onClick={signOut}>
          <Bi hi="साइन आउट" en="Sign out" />
        </button>
      )}
    </div>
  );
}

/** Page chrome: brand, navigation (a bottom bar on phones) and the demo label. */
export function Layout() {
  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">
        सामग्री पर जाएँ (Skip to content)
      </a>
      {isMock && <DemoBanner />}
      <header className={cx(styles.header, 'no-print')}>
        <Link to="/" className={styles.brand} aria-label="जल साक्षी JalSakshi, home">
          <span className={styles.mark}>
            <IconTap size={26} />
          </span>
          <span className={styles.wordmark}>
            <span lang="hi" className={styles.wordHi}>
              जल साक्षी
            </span>
            <span lang="en" className={styles.wordEn}>
              JalSakshi console
            </span>
          </span>
        </Link>
        <nav aria-label="Main" className={styles.nav}>
          <ul>
            {NAV.map(({ to, hi, en, Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) => cx(styles.navLink, isActive && styles.active)}
                >
                  <Icon size={22} />
                  <Bi hi={hi} en={en} />
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <Account />
      </header>
      <main id="main" className={styles.main} tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
