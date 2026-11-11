import { useCallback, useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { money } from '../lib/format'

const EMPTY = { name: '', phone: '', trade: '', daily_rate: '', ot_rate: '', paypal_email: '' }

export default function Crew() {
  const { token, me, refresh, setSiteId } = useAuth()
  const { site } = useOutletContext()
  const [workers, setWorkers] = useState([])
  const [form, setForm] = useState(EMPTY)
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const cur = me?.settings.wage_currency || 'NGN'

  const load = useCallback(async () => {
    if (!site) return
    setWorkers((await api.get(`/api/workers?site_id=${site.site_id}`, token)).workers)
  }, [site, token])
  useEffect(() => { load() }, [load])

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(''); setInfo('')
    const body = { ...form, daily_rate: Number(form.daily_rate), ot_rate: form.ot_rate === '' ? undefined : Number(form.ot_rate) }
    try {
      if (editing) await api.patch(`/api/workers/${editing}`, body, token)
      else await api.post('/api/workers', { ...body, site_id: site.site_id }, token)
      setForm(EMPTY); setEditing(null); load()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  function edit(w) {
    setEditing(w.worker_id)
    setForm({ name: w.name, phone: '+' + w.phone, trade: w.trade, daily_rate: w.daily_rate, ot_rate: w.ot_rate, paypal_email: w.paypal_email })
  }

  async function toggle(w) {
    await api.patch(`/api/workers/${w.worker_id}`, { active: !w.active }, token)
    load()
  }

  async function seed() {
    setBusy(true); setError('')
    try {
      const r = await api.post('/api/demo/seed', {}, token)
      await refresh()
      setSiteId(r.site.site_id)
      setInfo(`Demo site “${r.site.name}” created with 4 workers and the past 6 days of register.` +
        (r.using_placeholder_emails ? ' Workers have placeholder PayPal emails; set DEMO_PAYPAL_RECEIVERS or edit them to your sandbox personal account.' : ''))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  if (!site) return (
    <div className="card panel">
      <h2>No site yet</h2>
      {error && <div className="banner banner-error">{error}</div>}
      <p className="muted" style={{ marginBottom: 12 }}>Add a site on the Sites page, or load the demo crew (it creates its own site).</p>
      <button className="btn btn-primary" onClick={seed} disabled={busy}>Load demo crew</button>
    </div>
  )

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Crew</h1>
          <p>Workers on {site.name}. Their WhatsApp number is how the bot knows them; their PayPal email is where pay goes.</p>
        </div>
        <button className="btn btn-secondary" onClick={seed} disabled={busy}>Load demo crew</button>
      </div>
      {error && <div className="banner banner-error">{error}</div>}
      {info && <div className="banner banner-success">{info}</div>}

      <form className="card panel" onSubmit={submit}>
        <h2>{editing ? 'Edit worker' : 'Add a worker'}</h2>
        <div className="field-row">
          <div className="field"><label>Full name</label><input required value={form.name} onChange={set('name')} /></div>
          <div className="field"><label>WhatsApp number</label><input required value={form.phone} onChange={set('phone')} placeholder="0803 123 4567" /></div>
        </div>
        <div className="field-row">
          <div className="field"><label>Trade</label><input value={form.trade} onChange={set('trade')} placeholder="Mason, Labourer, Painter…" /></div>
          <div className="field"><label>PayPal email</label><input type="email" value={form.paypal_email} onChange={set('paypal_email')} placeholder="worker@example.com" /></div>
        </div>
        <div className="field-row">
          <div className="field"><label>Daily rate ({cur})</label><input required type="number" min="0" value={form.daily_rate} onChange={set('daily_rate')} /></div>
          <div className="field"><label>OT rate per hour ({cur})</label><input type="number" min="0" value={form.ot_rate} onChange={set('ot_rate')} placeholder="default: 1.5× hourly" /></div>
        </div>
        <div className="row">
          <button className="btn btn-primary" disabled={busy}>{editing ? 'Save' : 'Add worker'}</button>
          {editing && <button type="button" className="btn btn-secondary" onClick={() => { setEditing(null); setForm(EMPTY) }}>Cancel</button>}
        </div>
      </form>

      <div className="card">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Name</th><th>Trade</th><th>WhatsApp</th><th>Rate</th><th>OT/hr</th><th>PayPal</th><th></th></tr></thead>
            <tbody>
              {workers.length === 0 && <tr><td colSpan={7} className="empty-state">No workers yet.</td></tr>}
              {workers.map((w) => (
                <tr key={w.worker_id} style={{ opacity: w.active ? 1 : 0.5 }}>
                  <td><strong>{w.name}</strong></td><td>{w.trade}</td><td>+{w.phone}</td>
                  <td>{money(w.daily_rate, cur)}</td><td>{money(w.ot_rate, cur)}</td>
                  <td className="small">{w.paypal_email || <span style={{ color: 'var(--color-danger)' }}>missing</span>}</td>
                  <td className="row">
                    <button className="btn btn-secondary btn-sm" onClick={() => edit(w)}>Edit</button>
                    <button className="btn btn-secondary btn-sm" onClick={() => toggle(w)}>{w.active ? 'Deactivate' : 'Reactivate'}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
