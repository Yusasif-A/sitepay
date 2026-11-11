import { useEffect, useState } from 'react'
import { api, fetchImageUrl } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { FLAG_TEXT, STATUS, money, prettyDate } from '../lib/format'
import AiCheck from '../components/AiCheck'

function Photo({ ev, token, onOpen }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let revoked = ''
    fetchImageUrl(`/api/evidence/${ev.evidence_id}/image`, token).then((u) => { revoked = u; setUrl(u) }).catch(() => {})
    return () => revoked && URL.revokeObjectURL(revoked)
  }, [ev.evidence_id, token])
  return url ? <img src={url} alt={ev.ai?.summary || 'Work photo'} onClick={() => onOpen(url)} /> : <div className="card" style={{ aspectRatio: '4/3' }} />
}

/** Per-worker evidence panel: photos + AI summary + supervisor actions. */
export default function EvidenceDrawer({ row, date, currency, showAi, onClose, onChanged }) {
  const { token } = useAuth()
  const [zoom, setZoom] = useState('')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [note, setNote] = useState(row.notes || '')
  const locked = !!row.pay_run_id
  const photos = row.evidence.filter((e) => e.kind === 'photo')
  const notes = row.evidence.filter((e) => e.kind !== 'photo')

  async function act(label, fn) {
    setBusy(label); setErr(''); setMsg('')
    try { await fn(); await onChanged() } catch (e) { setErr(e.message) } finally { setBusy('') }
  }

  const save = (fields) => api.put(`/api/register/${row.worker_id}/${date}`, fields, token)

  async function upload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    const fd = new FormData()
    fd.append('worker_id', row.worker_id); fd.append('date', date); fd.append('file', file)
    await act('upload', () => api.post('/api/evidence/upload', fd, token))
    e.target.value = ''
  }

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={`Evidence for ${row.name}`}>
        <div className="row" style={{ marginBottom: 4 }}>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 800 }}>{row.name}</h2>
          <span className="spacer" />
          <button className="btn btn-secondary btn-sm" onClick={onClose}>Close</button>
        </div>
        <p className="muted small" style={{ marginBottom: 16 }}>
          {row.trade || 'Worker'} · {prettyDate(date)} · {money(row.daily_rate, currency)}/day
        </p>

        <div className="card panel">
          <div className="row" style={{ marginBottom: 8 }}>
            <span className={`status-pill status-${row.status || 'none'}`}>{row.status || '–'}</span>
            <strong>{row.status ? STATUS[row.status].label : 'Not logged'}</strong>
            {row.ot_hours > 0 && <span className="chip chip-neutral">+{row.ot_hours}h OT</span>}
            {row.ot_claim_hours > 0 && row.ot_claim_hours !== row.ot_hours &&
              <span className="chip chip-warn">Worker claims {row.ot_claim_hours}h OT</span>}
          </div>
          <p className="small muted">
            {row.check?.state === 'no_proof' ? 'On the register without a WhatsApp check-in'
              : row.checked_in ? 'Checked in on WhatsApp' : row.logged ? 'Logged on dashboard' : 'No check-in yet'}
          </p>
          {row.location && (
            <p className="small" style={{ marginTop: 6 }}>
              📍 Location shared:{' '}
              <a href={`https://maps.google.com/?q=${row.location.lat},${row.location.lon}`} target="_blank" rel="noreferrer">
                {Number(row.location.lat).toFixed(5)}, {Number(row.location.lon).toFixed(5)}
              </a>
            </p>
          )}
          {locked && <div className="banner banner-info" style={{ marginTop: 12, marginBottom: 0 }}>In pay run {row.pay_run_id}. Locked.</div>}
        </div>

        {err && <div className="banner banner-error">{err}</div>}
        {msg && <div className="banner banner-success">{msg}</div>}

        {showAi && (
          <AiCheck check={row.check} busy={busy === 'ai'}
            onRerun={photos.length ? () => act('ai', async () => {
              await api.post(`/api/register/${row.worker_id}/${date}/ai-check`, {}, token)
              setMsg('AI check updated.')
            }) : null} />
        )}
        {row.accepted_check && row.review === 'accepted' && (
          <p className="small muted" style={{ marginTop: -8, marginBottom: 14 }}>
            You accepted this day when the AI check said: <strong>{row.accepted_check.state.replace('_', ' ')}</strong>
            {row.accepted_check.issues?.length ? ` (${row.accepted_check.issues.join(', ')})` : ''}.
          </p>
        )}

        {photos.length > 0 && (
          <>
            <h3 className="small muted" style={{ fontWeight: 800, margin: '4px 0 8px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Evidence ({photos.length} photo{photos.length === 1 ? '' : 's'})
            </h3>
            <div className="photo-thumbs" style={{ marginBottom: 16 }}>
              {photos.map((ev) => (
                <div key={ev.evidence_id}>
                  <Photo ev={ev} token={token} onOpen={setZoom} />
                  <div className="cap">
                    {ev.purpose === 'check_in' ? 'Check-in' : 'Work'} ·{' '}
                    {new Date(ev.created_at + (String(ev.created_at).endsWith('Z') ? '' : 'Z')).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    {ev.text ? ` · “${ev.text}”` : ''}
                    {(ev.flags || []).filter((f) => FLAG_TEXT[f]).map((f) => ` · ⚠ ${FLAG_TEXT[f]}`).join('')}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
        {photos.length === 0 && <p className="muted small" style={{ marginBottom: 12 }}>No photos yet for this day.</p>}

        {notes.length > 0 && (
          <>
            <h3 style={{ fontWeight: 800, margin: '8px 0 10px' }}>Worker notes</h3>
            {notes.map((n) => <p key={n.evidence_id} className="card panel small" style={{ padding: 12 }}>“{n.text}”</p>)}
          </>
        )}

        {!locked && (
          <div className="card panel">
            <h2>Your decision</h2>
            <div className="row" style={{ marginBottom: 12 }}>
              <button className="btn btn-primary btn-sm" disabled={!!busy}
                onClick={() => act('accept', async () => { await save({ status: row.status || 'P', review: 'accepted' }); setMsg('Accepted.') })}>
                ✓ Accept
              </button>
              {row.ot_claim_hours > 0 && row.ot_claim_hours !== row.ot_hours && (
                <button className="btn btn-secondary btn-sm" disabled={!!busy}
                  onClick={() => act('ot', () => save({ ot_hours: row.ot_claim_hours, review: 'accepted' }))}>
                  Accept {row.ot_claim_hours}h OT
                </button>
              )}
              <button className="btn btn-secondary btn-sm" disabled={!!busy}
                onClick={() => act('photo', async () => {
                  const r = await api.post(`/api/register/${row.worker_id}/${date}/request-photo`, {}, token)
                  setMsg(r.delivered ? 'Asked on WhatsApp for a clearer photo.' : 'Marked “needs photo”. The WhatsApp message could not be delivered (the worker must have messaged the bot in the last 24 hours).')
                })}>
                Request clearer photo
              </button>
            </div>
            <div className="field" style={{ marginBottom: 10 }}>
              <label>Manual note</label>
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <button className="btn btn-secondary btn-sm" disabled={!!busy || note === (row.notes || '')}
              onClick={() => act('note', () => save({ notes: note }))}>Save note</button>
            <hr style={{ border: 0, borderTop: '1px solid var(--color-border)', margin: '16px 0' }} />
            <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
              {busy === 'upload' ? 'Uploading + analysing…' : '⬆ Upload photo for this worker'}
              <input type="file" accept="image/*" hidden onChange={upload} disabled={!!busy} />
            </label>
          </div>
        )}

        {zoom && (
          <div className="drawer-backdrop" style={{ zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => setZoom('')}>
            <img src={zoom} alt="" style={{ maxWidth: '92vw', maxHeight: '90vh', borderRadius: 12 }} />
          </div>
        )}
      </aside>
    </>
  )
}
