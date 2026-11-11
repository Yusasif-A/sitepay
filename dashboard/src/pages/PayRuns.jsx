import { useCallback, useEffect, useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
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

export default function PayRuns() {
  const { token, me } = useAuth()
  const { site } = useOutletContext()
  const [params] = useSearchParams()
  const today = todayIn(me?.settings)
  const [start, setStart] = useState(params.get('start') || addDays(today, -6))
  const [end, setEnd] = useState(params.get('end') || today)
  const [preview, setPreview] = useState(null)
  const [runs, setRuns] = useState([])
  const [active, setActive] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const loadPreview = useCallback(async () => {
    if (!site) return
    try { setPreview(await api.get(`/api/payruns/preview?site_id=${site.site_id}&start=${start}&end=${end}`, token)); setError('') }
    catch (e) { setError(e.message); setPreview(null) }
  }, [site, start, end, token])

  const loadRuns = useCallback(async () => {
    const data = await api.get('/api/payruns', token)
    setRuns(data.runs.filter((r) => !site || r.site_id === site.site_id))
  }, [token, site])

  useEffect(() => { loadPreview() }, [loadPreview])
  useEffect(() => { loadRuns() }, [loadRuns])

  async function openRun(id) { setActive(await api.get(`/api/payruns/${id}`, token)) }

  async function step(label, fn) {
    setBusy(label); setError('')
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  const approve = () => step('approve', async () => {
    const run = await api.post('/api/payruns', { site_id: site.site_id, start, end }, token)
    setActive(run); await Promise.all([loadPreview(), loadRuns()])
  })
  // workerId = pay just that worker; omit to pay everyone still unpaid.
  const pay = (workerId) => step(workerId ? `pay:${workerId}` : 'pay', async () => {
    const body = workerId ? { worker_ids: [workerId] } : {}
    setActive(await api.post(`/api/payruns/${active.run_id}/pay`, body, token)); await loadRuns()
  })
  const refresh = () => step('refresh', async () => {
    setActive(await api.post(`/api/payruns/${active.run_id}/refresh`, {}, token)); await loadRuns()
  })

  const cur = preview?.wage_currency || me?.settings.wage_currency || 'NGN'
  const pending = preview?.lines.filter((l) => l.days > 0) || []
  const reviewLeft = pending.reduce((s, l) => s + l.pending_review + l.needs_photo, 0)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Pay runs</h1>
          <p>Approve the register for a period, then pay the crew through PayPal Payouts in one batch.</p>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}

      {!active && (
        <div className="card panel">
          <div className="row" style={{ marginBottom: 14 }}>
            <h2 style={{ margin: 0 }}>1 · Review the period</h2>
            <span className="spacer" />
            <div className="toolbar" style={{ margin: 0 }}>
              <input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} />
              <span className="muted">to</span>
              <input type="date" value={end} onChange={(e) => e.target.value && setEnd(e.target.value)} />
              <button className="btn btn-secondary btn-sm" onClick={() => { setStart(addDays(today, -6)); setEnd(today) }}>Last 7 days</button>
            </div>
          </div>

          {preview?.simulate && (
            <div className="banner banner-warn">
              PayPal is in <strong>simulated</strong> mode (no credentials in the backend .env). The full flow runs but no
              PayPal API is called. Add sandbox credentials to send real sandbox payouts.
            </div>
          )}

          {preview && pending.length === 0 && <div className="empty-state"><span className="empty-icon">🧾</span>No unpaid days in {preview.label}.</div>}

          {pending.length > 0 && (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Worker</th><th>Days</th><th>OT hrs</th><th>Gross</th><th>Advances</th><th>Net</th><th>PayPal</th><th></th></tr></thead>
                  <tbody>
                    {pending.map((l) => (
                      <tr key={l.worker_id}>
                        <td><strong>{l.worker_name}</strong><div className="small muted">{l.trade}</div></td>
                        <td>{counts(l.counts)}</td>
                        <td>{l.ot_hours || '—'}</td>
                        <td>{money(l.gross, cur)}</td>
                        <td>{l.advances ? `−${money(l.advances, cur)}` : '—'}</td>
                        <td><strong>{money(l.net, cur)}</strong></td>
                        <td>
                          <div>{l.payout_amount} {preview.payout_currency}</div>
                          <div className="small muted">{l.paypal_email || <span style={{ color: 'var(--color-danger)' }}>no PayPal email</span>}</div>
                        </td>
                        <td>{(l.pending_review + l.needs_photo) > 0 && <span className="chip chip-warn">{l.pending_review + l.needs_photo} to review</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ marginTop: 16 }}>
                <div>
                  <div className="small muted">Total for {preview.label}</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 800 }}>{money(preview.total_net, cur)}
                    <span className="muted" style={{ fontSize: '1rem', fontWeight: 600 }}> ≈ {preview.total_payout} {preview.payout_currency}</span></div>
                  <div className="small muted">at {preview.fx_rate.toLocaleString()} {cur} = 1 {preview.payout_currency}</div>
                </div>
                <span className="spacer" />
                {reviewLeft > 0 && <span className="small muted">{reviewLeft} day(s) not reviewed yet, approving accepts them as-is.</span>}
                <button className="btn btn-primary" disabled={busy === 'approve' || preview.missing_paypal.length > 0} onClick={approve}>
                  {busy === 'approve' ? 'Approving…' : 'Approve period'}
                </button>
              </div>
              {preview.missing_paypal.length > 0 && (
                <div className="banner banner-warn" style={{ marginTop: 12 }}>Add a PayPal email on the Crew page for: {preview.missing_paypal.join(', ')}</div>
              )}
            </>
          )}
        </div>
      )}

      {active && (
        <div className="card panel">
          <div className="row" style={{ marginBottom: 6 }}>
            <h2 style={{ margin: 0 }}>{['approved', 'partial'].includes(active.status) ? '2 · Send payout' : 'Pay run'} {active.run_id}</h2>
            {active.simulated && <span className="chip chip-warn">SIMULATED</span>}
            <span className={`chip ${active.status === 'completed' ? 'chip-ok' : active.status === 'failed' ? 'chip-bad' : 'chip-warn'}`}>{active.status}</span>
            <span className="spacer" />
            <button className="btn btn-secondary btn-sm" onClick={() => setActive(null)}>← Back</button>
          </div>
          <p className="muted small" style={{ marginBottom: 14 }}>
            {active.reference} · {active.worker_count} workers · {money(active.total_net, active.wage_currency)} ≈ {active.total_payout} {active.payout_currency}
            {active.payout_batch_id && <> · PayPal batch <code>{active.payout_batch_id}</code> ({active.batch_status})</>}
          </p>
          {active.error && <div className="banner banner-error">{active.error}</div>}

          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Worker</th><th>Days</th><th>Net</th><th>Payout</th><th>Status</th><th>Transaction</th><th>WhatsApp</th><th></th></tr></thead>
              <tbody>
                {active.lines.map((l) => {
                  const canPay = l.net > 0 && ['NOT_SENT', 'FAILED'].includes(l.transaction_status)
                  return (
                    <tr key={l.worker_id}>
                      <td><strong>{l.worker_name}</strong><div className="small muted">{l.dates.length} day(s) · {l.evidence_ids.length} evidence</div></td>
                      <td>{counts(l.counts)}</td>
                      <td>{money(l.net, active.wage_currency)}</td>
                      <td>{l.payout_amount} {active.payout_currency}<div className="small muted">{l.paypal_email}</div></td>
                      <td><Tx status={l.transaction_status} /></td>
                      <td className="small">{l.transaction_id || '—'}</td>
                      <td>{l.notified ? <span className="chip chip-ok">Pay note sent</span> : <span className="muted small">—</span>}</td>
                      <td>
                        {canPay && (
                          <button className="btn btn-primary btn-sm" disabled={!!busy} onClick={() => pay(l.worker_id)}>
                            {busy === `pay:${l.worker_id}` ? 'Sending…' : `💸 Pay ${l.worker_name.split(' ')[0]}`}
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {(() => {
            const unpaid = active.lines.filter((l) => l.net > 0 && ['NOT_SENT', 'FAILED'].includes(l.transaction_status))
            const inFlight = active.lines.some((l) => ['SUBMITTING', 'PENDING', 'ONHOLD'].includes(l.transaction_status))
            const total = unpaid.reduce((s, l) => s + Number(l.payout_amount), 0).toFixed(2)
            return (
              <div className="row" style={{ marginTop: 16 }}>
                {unpaid.length > 1 && (
                  <button className="btn btn-primary" onClick={() => pay()} disabled={!!busy}>
                    {busy === 'pay' ? 'Sending to PayPal…' : `💸 Pay all ${unpaid.length} · ${total} ${active.payout_currency}`}
                  </button>
                )}
                {inFlight && (
                  <button className="btn btn-secondary" onClick={refresh} disabled={!!busy}>{busy === 'refresh' ? 'Checking…' : '↻ Check PayPal status'}</button>
                )}
                {unpaid.length > 0 && <span className="small muted">Pay one worker with their button, or everyone left at once.</span>}
                {active.status === 'completed' && <span className="banner banner-success" style={{ margin: 0 }}>Paid. Workers got their pay note on WhatsApp.</span>}
              </div>
            )
          })()}
        </div>
      )}

      <div className="card panel">
        <h2>History</h2>
        {runs.length === 0 ? <p className="muted small">No pay runs yet.</p> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Run</th><th>Period</th><th>Workers</th><th>Total</th><th>Status</th><th></th></tr></thead>
              <tbody>{runs.map((r) => (
                <tr key={r.run_id}>
                  <td><code>{r.run_id}</code>{r.simulated && <span className="chip chip-warn" style={{ marginLeft: 6 }}>SIM</span>}</td>
                  <td>{prettyDate(r.start)}{r.start !== r.end && ` – ${prettyDate(r.end)}`}</td>
                  <td>{r.worker_count}</td>
                  <td>{money(r.total_net, r.wage_currency)}<div className="small muted">{r.total_payout} {r.payout_currency}</div></td>
                  <td><span className={`chip ${r.status === 'completed' ? 'chip-ok' : r.status === 'failed' ? 'chip-bad' : 'chip-warn'}`}>{r.status}</span></td>
                  <td><button className="btn btn-secondary btn-sm" onClick={() => openRun(r.run_id)}>Open</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
