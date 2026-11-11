import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import AuthShell from '../components/AuthShell'
import { useAuth } from '../lib/AuthContext'

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError(''); setLoading(true)
    try { await login(email, password); navigate('/app') }
    catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  return (
    <AuthShell eyebrow="Supervisor" title="Sign in" subtitle="Your site register, work photos and crew pay."
      footer={<span>New to SitePay? <Link to="/signup">Create an account</Link></span>}>
      <form onSubmit={submit}>
        {error && <div className="banner banner-error">{error}</div>}
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" required autoFocus autoComplete="username"
            value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input id="password" type="password" required autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button className="btn btn-primary btn-block" disabled={loading}>
          {loading && <span className="spinner" />}{loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </AuthShell>
  )
}

export function Signup() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  const [f, setF] = useState({ name: '', company: '', email: '', phone: '', password: '', site_name: '', site_location: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setError(''); setLoading(true)
    try { await signup(f); navigate('/app') }
    catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  return (
    <AuthShell wide eyebrow="Supervisor" title="Create your SitePay account"
      subtitle="Log site days with photo proof, approve the register, and pay your crew through PayPal."
      footer={<span>Already have an account? <Link to="/login">Sign in</Link></span>}>
      <form onSubmit={submit}>
        {error && <div className="banner banner-error">{error}</div>}
        <div className="field-row">
          <div className="field"><label>Your name</label><input required value={f.name} onChange={set('name')} /></div>
          <div className="field"><label>Company (optional)</label><input value={f.company} onChange={set('company')} /></div>
        </div>
        <div className="field-row">
          <div className="field"><label>Email</label><input type="email" required value={f.email} onChange={set('email')} autoComplete="username" /></div>
          <div className="field"><label>Phone (optional)</label><input value={f.phone} onChange={set('phone')} placeholder="0803 123 4567" /></div>
        </div>
        <div className="field">
          <label>Password</label>
          <input type="password" required minLength={8} value={f.password} onChange={set('password')} autoComplete="new-password" />
          <span className="hint">At least 8 characters.</span>
        </div>
        <div className="field-row">
          <div className="field"><label>First site name</label><input value={f.site_name} onChange={set('site_name')} placeholder="Lekki Phase 2 Duplex" /></div>
          <div className="field"><label>Site location</label><input value={f.site_location} onChange={set('site_location')} placeholder="Lekki, Lagos" /></div>
        </div>
        <button className="btn btn-primary btn-block" disabled={loading}>
          {loading && <span className="spinner" />}{loading ? 'Creating…' : 'Create account'}
        </button>
      </form>
    </AuthShell>
  )
}
