import { Link } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'
import styles from './Landing.module.css'

const STEPS = [
  ['📲', 'Worker checks in on WhatsApp', 'Tap Check in and send a photo of the day\'s work. No app to install.'],
  ['🧠', 'AI structures the evidence', 'Each photo gets a one-line summary and flags for dark, repeated or unrelated pictures.'],
  ['✅', 'Supervisor approves', 'Hajri-style register: P / A / H / OT / advances. Edit any line, then approve the period.'],
  ['💸', 'PayPal pays the crew', 'One Payouts batch, one line per worker, with a clear "what this payment is for" note.'],
  ['🧾', 'Worker gets a pay note', 'Days, overtime, advances and net, sent back on WhatsApp. A digital trail, not cash.'],
]

export default function Landing() {
  const { token } = useAuth()
  return (
    <div className={styles.page}>
      <nav className={styles.nav}>
        <span className={styles.brand}><span className={styles.mark}>₦</span>SitePay</span>
        <div className="row">
          {token ? <Link className="btn btn-primary" to="/app">Open dashboard</Link> : (
            <>
              <Link className="btn btn-secondary" to="/login">Sign in</Link>
              <Link className="btn btn-primary" to="/signup">Get started</Link>
            </>
          )}
        </div>
      </nav>

      <header className={styles.hero}>
        <span className={styles.eyebrow}>Day-labour payroll</span>
        <h1>From site day → proof → approved pay → PayPal payout.</h1>
        <p>Supervisors log the day with photo evidence. Workers get fair, traceable pay and a receipt on WhatsApp. No more paper registers and cash disputes.</p>
        <div className="row" style={{ justifyContent: 'center' }}>
          <Link className="btn btn-primary" to={token ? '/app' : '/signup'}>Start a site register</Link>
        </div>
      </header>

      <section className={styles.steps}>
        {STEPS.map(([icon, title, body], i) => (
          <div key={title} className={`card ${styles.step}`}>
            <span className={styles.num}>{i + 1}</span>
            <span className={styles.icon}>{icon}</span>
            <h3>{title}</h3>
            <p>{body}</p>
          </div>
        ))}
      </section>

      <section className={styles.rule}>
        <strong>AI never pays.</strong> It summarises photos and tidies messy notes. A supervisor approves every amount before any money moves.
      </section>
    </div>
  )
}
