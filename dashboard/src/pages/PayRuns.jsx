import { useCallback, useEffect, useState } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { TX_STATUS, addDays, money, prettyDate, todayIn } from '../lib/format'

function Tx({ status }) {
  const s = TX_STATUS[status] || { label: status, tone: 'neutral' }
  return <span className={`chip chip-${s.tone}`}>{s.label}</span>
}

function counts(c) {
  return ['P', 'OT', 'H', 'L', 'A'].filter((k) => c[k]).map((k) => `${c[k]}${k}`).join(' · ') || '—'
}

/** AI check across a worker's days, shown next to their Pay button. */
function PeriodCheck({ check, days }) {
  if (!check) return <span className="muted small">—</span>
  const ok = check.verified
  const bad = check.flagged
  return (
    <div style={{ minWidth: 190 }}>
      <div className="row" style={{ gap: 6 }}>
        {ok > 0 && <span className="chip chip-ok">✅ {ok}/{days} AI verified</span>}
        {bad > 0 && <span className="chip chip-bad">⚠️ {bad} flagged</span>}
        {!ok && !bad && <span className="chip chip-neutral">No AI proof</span>}
      </div>
      {check.flagged_days?.slice(0, 2).map((d) => (
        <div key={d.date} className="small" style={{ color: 'var(--color-danger)', marginTop: 3 }}>
          {prettyDate(d.date)}: {d.state === 'no_proof' ? 'no location or check-in photo' : d.issues.join(', ')}
        </div>
      ))}
    </div>
  )
}

/** One screen: who's owed what for the period, the AI check for their days,
 *  and a Pay button per worker (plus Pay all). Paying sends only days the
 *  supervisor approved on the Register. */
export default function PayRuns() {
  const { token, me } = useAuth()
  const { site } = useOutletContext()
  const [params] = useSearchParams()
  const today = todayIn(me?.settings)
  const [start, setStart] = useState(params.get('start') || addDays(today, -6))
  const [end, setEnd] = useState(params.get('end') || today)
  const [preview, setPreview] = useState(null)
  const [runs, setRuns] = useState([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  const load = useCallback(async () => {
    if (!site) return
    try {
      const [p, r] = await Promise.all([
        api.get(`/api/payruns/preview?site_id=${site.site_id}&start=${start}&end=${end}`, token),
        api.get('/api/payruns', token),
      ])
      setPreview(p)
      setRuns(r.runs.filter((x) => x.site_id === site.site_id))
      setError('')
    } catch (e) { setError(e.message) }
  }, [site, start, end, token])
  useEffect(() => { load() }, [load])

  async function payNow(workerIds, label) {
    setBusy(label); setError(''); setDone('')
    try {
      const body = { site_id: site.site_id, start, end }
      if (workerIds) body.worker_ids = workerIds
      const run = await api.post('/api/pay-now', body, token)
      const paid = run.lines.filter((l) => ['SUCCESS', 'UNCLAIMED', 'PENDING'].includes(l.transaction_status))
      setDone(`Sent ${paid.map((l) => l.worker_name).join(', ')}'s pay to PayPal. It shows Paid here in a few seconds, and the pay note goes to WhatsApp.`)
      await load()
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  // Lines from earlier runs (paid, or approved before this screen existed).
  const paidLines = runs.flatMap((r) => (r.lines || []).map((l) => ({ ...l, run: r })))
  const cur = preview?.wage_currency || me?.settings.wage_currency || 'NGN'
  // Workers with nothing left to pay (already paid, or nothing approved) drop off the top table.
  const lines = (preview?.lines || []).filter((l) => l.net > 0 || l.awaiting_approval > 0 || l.rejected_days > 0)

  // PayPal confirms a payout a few seconds after it's sent. While any line is
  // still on its way, ask PayPal again every 4s; that also sends the WhatsApp
  // pay note once it's confirmed.
  const inFlightRuns = [...new Set(paidLines
    .filter((l) => ['SUBMITTING', 'PENDING', 'ONHOLD'].includes(l.transaction_status))
    .map((l) => l.run.run_id))].join(',')
  useEffect(() => {
    if (!inFlightRuns) return
    const t = setInterval(async () => {
      for (const id of inFlightRuns.split(',')) {
        try { await api.post(`/api/payruns/${id}/refresh`, {}, token) } catch { /* try again next tick */ }
      }
      load()
    }, 4000)
    return () => clearInterval(t)
  }, [inFlightRuns, token, load])
  const payable = lines.filter((l) => l.net > 0 && l.paypal_email)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Pay</h1>
          <p>Approved days only. Check the AI result, then pay one worker or everyone through PayPal.</p>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} />
          <span className="muted">to</span>
          <input type="date" value={end} onChange={(e) => e.target.value && setEnd(e.target.value)} />
          <button className="btn btn-secondary btn-sm" onClick={() => { setStart(addDays(today, -6)); setEnd(today) }}>Last 7 days</button>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}
      {done && <div className="banner banner-success">✅ {done}</div>}
      {preview?.simulate && <div className="banner banner-warn">PayPal is in simulated mode: no PayPal API is called.</div>}

      <div className="card panel">
        {lines.length === 0 ? (
          <div className="empty-state"><span className="empty-icon">🧾</span>Nothing to pay for {preview?.label || 'this period'}.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Worker</th><th>Approved days</th><th>AI check</th><th>Net</th><th>PayPal</th><th></th></tr></thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.worker_id}>
                    <td><strong>{l.worker_name}</strong><div className="small muted">{l.trade}</div></td>
                    <td>
                      {counts(l.counts)}
                      {l.ot_hours ? <div className="small muted">+{l.ot_hours}h OT</div> : null}
                      {l.advances ? <div className="small muted">−{money(l.advances, cur)} advance</div> : null}
                      {l.awaiting_approval > 0 && (
                        <div className="small" style={{ color: 'var(--color-warning)', marginTop: 3 }}>
                          {l.awaiting_approval} day(s) waiting for your approval ·{' '}
                          <Link to={`/app?date=${l.awaiting_dates[0]}`}>approve on Register</Link>
                        </div>
                      )}
                      {l.rejected_days > 0 && (
                        <div className="small" style={{ color: 'var(--color-danger)', marginTop: 3 }}>
                          {l.rejected_days} day(s) rejected, not paid
                        </div>
                      )}
                    </td>
                    <td><PeriodCheck check={l.check} days={l.days + (l.awaiting_approval || 0)} /></td>
                    <td><strong>{money(l.net, cur)}</strong><div className="small muted">≈ {l.payout_amount} {preview.payout_currency}</div></td>
                    <td className="small">{l.paypal_email || <span style={{ color: 'var(--color-danger)' }}>no PayPal email</span>}</td>
                    <td>
                      {l.net > 0 && l.paypal_email ? (
                        <button className="btn btn-primary btn-sm" disabled={!!busy} onClick={() => payNow([l.worker_id], l.worker_id)}>
                          {busy === l.worker_id ? 'Paying…' : `💸 Pay ${l.worker_name.split(' ')[0]}`}
                        </button>
                      ) : <span className="muted small">{l.net > 0 ? '' : 'Nothing approved'}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {payable.length > 1 && (
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn btn-primary" disabled={!!busy} onClick={() => payNow(null, 'all')}>
              {busy === 'all' ? 'Paying…' : `💸 Pay all ${payable.length} · ${money(payable.reduce((s, l) => s + l.net, 0), cur)}`}
            </button>
          </div>
        )}
      </div>

      <div className="card panel">
        <h2>Approved & paid</h2>
        {paidLines.length === 0 ? <p className="muted small">Nobody paid yet.</p> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Worker</th><th>Days</th><th>Net</th><th>PayPal</th><th>WhatsApp</th><th></th></tr></thead>
              <tbody>{paidLines.map((l) => (
                <tr key={`${l.run.run_id}-${l.worker_id}`}>
                  <td><strong>{l.worker_name}</strong><div className="small muted">{prettyDate(l.run.start)}{l.run.start !== l.run.end && ` – ${prettyDate(l.run.end)}`}</div></td>
                  <td>{counts(l.counts)}</td>
                  <td>{money(l.net, l.run.wage_currency)}<div className="small muted">{l.payout_amount} {l.run.payout_currency}</div></td>
                  <td><Tx status={l.transaction_status} />{l.transaction_id && <div className="small muted">{l.transaction_id}</div>}</td>
                  <td>{l.notified ? <span className="chip chip-ok">Pay note sent</span> : <span className="muted small">—</span>}</td>
                  <td>
                    {l.net > 0 && ['NOT_SENT', 'FAILED'].includes(l.transaction_status) && (
                      <button className="btn btn-primary btn-sm" disabled={!!busy}
                        onClick={async () => {
                          setBusy(`run:${l.worker_id}`); setError(''); setDone('')
                          try {
                            await api.post(`/api/payruns/${l.run.run_id}/pay`, { worker_ids: [l.worker_id] }, token)
                            setDone(`Paid ${l.worker_name} via PayPal. Pay note sent on WhatsApp.`)
                            await load()
                          } catch (e) { setError(e.message) } finally { setBusy('') }
                        }}>
                        {busy === `run:${l.worker_id}` ? 'Paying…' : `💸 Pay ${l.worker_name.split(' ')[0]}`}
                      </button>
                    )}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
