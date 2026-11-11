import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'
import styles from './DashboardLayout.module.css'

const NAV = [
  { to: '/app', label: 'Register', end: true },
  { to: '/app/calendar', label: 'Site calendar' },
  { to: '/app/pay', label: 'Pay runs' },
  { to: '/app/crew', label: 'Crew' },
  { to: '/app/whatsapp', label: 'WhatsApp simulator' },
  { to: '/app/sites', label: 'Sites' },
]

/** Sidebar + topbar shell (from Avalio), with a site switcher and a strip
 *  that says which integrations are live vs simulated. */
export default function DashboardLayout() {
  const { me, site, siteId, setSiteId, logout } = useAuth()
  const navigate = useNavigate()
  const s = me?.settings || {}

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>₦</span>
          <span>SitePay</span>
        </div>
        <nav className={styles.nav}>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}
              className={({ isActive }) => (isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink)}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <button className={styles.logout} onClick={() => { logout(); navigate('/login') }}>Log out</button>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.siteSwitch}>
            {me?.sites.length ? (
              <select value={siteId} onChange={(e) => setSiteId(e.target.value)} aria-label="Site">
                {me.sites.map((x) => <option key={x.site_id} value={x.site_id}>{x.name}</option>)}
              </select>
            ) : <span className={styles.identity}>No site yet</span>}
          </div>
          <div className={styles.chips}>
            <span className={`chip ${s.paypal_simulated ? 'chip-warn' : 'chip-ok'}`}>
              PayPal {s.paypal_simulated ? 'simulated' : s.paypal_env}
            </span>
            <span className={`chip ${s.whatsapp_live ? 'chip-ok' : 'chip-neutral'}`}>
              WhatsApp {s.whatsapp_live ? 'live' : 'simulator'}
            </span>
            <span className={styles.identity}>{me?.supervisor.name}</span>
          </div>
        </header>
        <div className={styles.content}>
          <Outlet context={{ site }} />
        </div>
      </div>
    </div>
  )
}
