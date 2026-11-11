import { useEffect, useState } from 'react'
import { api, fetchImageUrl } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { FLAG_TEXT, STATUS, money, prettyDate } from '../lib/format'

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
            {row.checked_in ? 'Checked in on WhatsApp' : row.logged ? 'Logged on dashboard' : 'No check-in yet'}
            {row.has_location ? ' · 📍 location shared' : ''}
          </p>
          {locked && <div className="banner banner-info" style={{ marginTop: 12, marginBottom: 0 }}>In pay run {row.pay_run_id}. Locked.</div>}
        </div>

        {err && <div className="banner banner-error">{err}</div>}
        {msg && <div className="banner banner-success">{msg}</div>}

        <h3 style={{ fontWeight: 800, margin: '8px 0 10px' }}>Work photos ({photos.length})</h3>
        {photos.length === 0 && <p className="muted small" style={{ marginBottom: 12 }}>No photos yet for this day.</p>}
        {photos.map((ev) => (
          <div key={ev.evidence_id} className="card panel" style={{ padding: 14 }}>
            <div className="photo-grid" style={{ gridTemplateColumns: '1fr' }}>
              <Photo ev={ev} token={token} onOpen={setZoom} />
            </div>
            {ev.text && <p className="small" style={{ marginTop: 8 }}>“{ev.text}”</p>}
            {showAi && <div style={{ marginTop: 10 }}>
              {ev.ai?.ok ? (
                <>
                  <p className="small"><strong>AI summary:</strong> {ev.ai.summary}</p>
                  <p className="small muted">{ev.ai.scene_type} · {ev.ai.progress} · confidence {ev.ai.confidence}</p>
                </>
              ) : (
                <p className="small muted">AI summary: {ev.ai ? ev.ai.reason : 'analysing…'}</p>
              )}
            </div>}
            {ev.flags?.length > 0 && (
              <div className="row" style={{ marginTop: 8 }}>
                {ev.flags.map((f) => <span key={f} className="chip chip-warn">{FLAG_TEXT[f] || f}</span>)}
              </div>
            )}
          </div>
        ))}

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
                  setMsg(r.delivered ? 'Asked on WhatsApp for a clearer photo.' : 'Marked “needs photo” (message is in the WhatsApp simulator).')
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
