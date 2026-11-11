import { Link } from 'react-router-dom'
import styles from './AuthShell.module.css'

/** Centred card for sign-in / sign-up (from Avalio). */
export default function AuthShell({ eyebrow, title, subtitle, children, footer, wide }) {
  return (
    <div className={styles.page}>
      <div className={`${styles.card} card ${wide ? styles.wide : ''}`}>
        <Link to="/" className={styles.brand}>
          <span className={styles.brandMark}>₦</span>
          SitePay
        </Link>
        {eyebrow && <span className={styles.eyebrow}>{eyebrow}</span>}
        <h1 className={styles.title}>{title}</h1>
        {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </div>
  )
}
