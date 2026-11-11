import { useCallback, useEffect, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api, fetchImageUrl } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import styles from './Simulator.module.css'

function format(text) {
  // WhatsApp-style *bold* and _italic_
  return text.split('\n').map((line, i) => {
    const parts = line.split(/(\*[^*]+\*|_[^_]+_)/g).map((p, j) => {
      if (/^\*[^*]+\*$/.test(p)) return <strong key={j}>{p.slice(1, -1)}</strong>
      if (/^_[^_]+_$/.test(p)) return <em key={j}>{p.slice(1, -1)}</em>
      return p
    })
    return <div key={i}>{parts.length ? parts : ' '}</div>
  })
}

function Thumb({ id, token }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let u = ''
    fetchImageUrl(`/api/evidence/${id}/image`, token).then((x) => { u = x; setUrl(x) }).catch(() => {})
    return () => u && URL.revokeObjectURL(u)
  }, [id, token])
  return url ? <img className={styles.thumb} src={url} alt="Work photo" /> : null
}

/** A phone-shaped WhatsApp chat that runs the real bot code. For demos
 *  without a Meta app, and for testing the worker experience. */
export default function Simulator() {
  const { token } = useAuth()
  const { site } = useOutletContext()
  const [workers, setWorkers] = useState([])
  const [workerId, setWorkerId] = useState('')
  const [messages, setMessages] = useState([])
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)
  const fileRef = useRef(null)

  useEffect(() => {
    if (!site) return
    api.get(`/api/workers?site_id=${site.site_id}`, token).then((d) => {
      const active = d.workers.filter((w) => w.active)
      setWorkers(active)
      setWorkerId((id) => (active.some((w) => w.worker_id === id) ? id : active[0]?.worker_id || ''))
    })
  }, [site, token])

  const load = useCallback(async () => {
    if (!workerId) { setMessages([]); return }
    setMessages((await api.get(`/api/simulator/${workerId}`, token)).messages)
  }, [workerId, token])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden && !busy) load() }, 5000)
    return () => clearInterval(t)
  }, [load, busy])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length])

  async function send(fields) {
    setBusy(true); setError('')
    const fd = new FormData()
    Object.entries(fields).forEach(([k, v]) => v !== undefined && v !== null && fd.append(k, v))
    try {
      setMessages((await api.post(`/api/simulator/${workerId}`, fd, token)).messages)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function submit(e) {
    e.preventDefault()
    if (!text.trim() && !file) return
    await send({ text: text.trim(), file })
    setText(''); setFile(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  function shareLocation() {
    const fallback = () => send({ lat: 6.4474, lon: 3.4723 }) // Lekki, Lagos
    if (!navigator.geolocation) return fallback()
    navigator.geolocation.getCurrentPosition((p) => send({ lat: p.coords.latitude, lon: p.coords.longitude }), fallback, { timeout: 4000 })
  }

  const worker = workers.find((w) => w.worker_id === workerId)
  const lastButtons = [...messages].reverse().find((m) => m.direction === 'out')?.buttons || []

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>WhatsApp simulator</h1>
          <p>Act as a worker's phone. It runs the same bot as the live WhatsApp number, so check-ins and photos land in the register.</p>
        </div>
        <select className="inline-input" value={workerId} onChange={(e) => setWorkerId(e.target.value)}>
          {workers.map((w) => <option key={w.worker_id} value={w.worker_id}>{w.name} (+{w.phone})</option>)}
        </select>
      </div>
      {error && <div className="banner banner-error">{error}</div>}
      {!workers.length && <div className="banner banner-info">Add workers on the Crew page first.</div>}

      {worker && (
        <div className={styles.layout}>
          <div className={styles.phone}>
            <div className={styles.header}>
              <div className={styles.avatar}>SP</div>
              <div><div className={styles.title}>SitePay</div><div className={styles.sub}>chatting as {worker.name}</div></div>
            </div>
            <div className={styles.chat}>
              {messages.length === 0 && <div className={styles.system}>Say “hi” to start.</div>}
              {messages.map((m, i) => (
                <div key={i} className={m.direction === 'in' ? styles.in : styles.out}>
                  {m.evidence_id && <Thumb id={m.evidence_id} token={token} />}
                  {m.text && <div>{format(m.text.replace(/^\[photo\]\s*/, ''))}</div>}
                  <div className={styles.time}>{new Date(m.at + (m.at.endsWith('Z') ? '' : 'Z')).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
                </div>
              ))}
              {busy && <div className={styles.out}><span className="spinner spinner-dark" /></div>}
              <div ref={endRef} />
            </div>
            {lastButtons.length > 0 && (
              <div className={styles.buttons}>
                {lastButtons.map((b) => <button key={b.id} disabled={busy} onClick={() => send({ button_id: b.id })}>{b.title}</button>)}
              </div>
            )}
            <form className={styles.composer} onSubmit={submit}>
              <button type="button" className={styles.icon} title="Attach work photo" onClick={() => fileRef.current?.click()}>📎</button>
              <button type="button" className={styles.icon} title="Share location" onClick={shareLocation} disabled={busy}>📍</button>
              <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => setFile(e.target.files?.[0] || null)} />
              <input className={styles.input} value={text} onChange={(e) => setText(e.target.value)}
                placeholder={file ? `Caption for ${file.name}…` : 'Message'} />
              <button className={styles.send} disabled={busy || (!text.trim() && !file)}>➤</button>
            </form>
            {file && <div className={styles.attach}>📷 {file.name} attached <button onClick={() => setFile(null)}>✕</button></div>}
          </div>

          <div className="card panel" style={{ alignSelf: 'start' }}>
            <h2>Try the worker flow</h2>
            <ol className="small" style={{ paddingLeft: 18, lineHeight: 1.8 }}>
              <li>Send <code>hi</code>, then tap <strong>✅ Check in</strong></li>
              <li>📎 attach a photo of work with a caption, e.g. <em>Finished wall section B</em></li>
              <li>Send <code>2 hours overtime</code> to claim OT</li>
              <li>Open the <strong>Register</strong>: the row, photo and AI summary are there</li>
              <li>Approve & pay on <strong>Pay runs</strong>. The pay note arrives back here.</li>
              <li>Tap <strong>💰 My pay</strong> any time</li>
            </ol>
            <p className="small muted">Voice notes aren't used; workers send text, photos, location or button taps.</p>
          </div>
        </div>
      )}
    </div>
  )
}
