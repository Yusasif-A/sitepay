import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { BryntumScheduler } from '@bryntum/scheduler-react'
import '@bryntum/scheduler/scheduler.css'
import '@bryntum/scheduler/svalbard-light.css'
import '@bryntum/scheduler/fontawesome/css/fontawesome.css'
import '@bryntum/scheduler/fontawesome/css/solid.css'
import { api } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { STATUS, addDays, money, prettyDate, todayIn } from '../lib/format'

// Bryntum colour names per register code
const COLOR = { P: 'green', OT: 'blue', H: 'orange', A: 'red', L: 'purple' }

function toDate(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function toIso(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

/** Site calendar (Bryntum Scheduler).
 *  Past/today: one bar per register day, coloured P / A / H / OT / L.
 *  Future: planned shifts (striped). Double-click an empty day, or use
 *  "Schedule worker", to plan a shift; the worker is told on WhatsApp. */
export default function SiteCalendar() {
  const { token, me } = useAuth()
  const { site } = useOutletContext()
  const navigate = useNavigate()
  const today = todayIn(me?.settings)
  const currency = me?.settings?.wage_currency || 'NGN'
  const [start, setStart] = useState(() => addDays(today, -6))
  const [data, setData] = useState({ workers: [], days: [], shifts: [] })
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [form, setForm] = useState(null) // {worker_id, start, end, task, start_time}
  const [saving, setSaving] = useState(false)
  const end = addDays(start, 13)

  const load = useCallback(async () => {
    if (!site) return
    try {
      setData(await api.get(`/api/register/range?site_id=${site.site_id}&start=${start}&end=${end}`, token))
      setError('')
    } catch (e) { setError(e.message) }
  }, [site, start, end, token])
  useEffect(() => { load() }, [load])

  const resources = useMemo(() => data.workers.map((w) => ({
    id: w.worker_id, name: w.name, trade: w.trade,
  })), [data.workers])

  const events = useMemo(() => {
    const logged = new Set(data.days.map((d) => `${d.worker_id}|${d.date}`))
    const dayEvents = data.days.map((d) => ({
      id: `day|${d.worker_id}|${d.date}`,
      resourceId: d.worker_id,
      startDate: toDate(d.date),
      endDate: toDate(addDays(d.date, 1)),
      name: d.status + (d.ot_hours ? ` +${d.ot_hours}h` : ''),
      eventColor: COLOR[d.status] || 'gray',
      cls: d.pay_run_id ? 'sp-paid' : '',
      kind: 'day',
      day: d,
    }))
    // A shift only shows while the day hasn't been worked yet.
    const shiftEvents = (data.shifts || [])
      .filter((s) => !logged.has(`${s.worker_id}|${s.date}`))
      .map((s) => ({
        id: `shift|${s.worker_id}|${s.date}`,
        resourceId: s.worker_id,
        startDate: toDate(s.date),
        endDate: toDate(addDays(s.date, 1)),
        name: '📅 ' + (s.task || 'Scheduled'),
        eventColor: 'gray',
        cls: 'sp-shift',
        kind: 'shift',
        shift: s,
      }))
    return [...dayEvents, ...shiftEvents]
  }, [data.days, data.shifts])

  function openForm(workerId, iso) {
    const s = iso < today ? today : iso
    setInfo(''); setError('')
    setForm({ worker_id: workerId || data.workers[0]?.worker_id || '', start: s, end: s, task: '', start_time: '08:00' })
  }

  async function saveShift(e) {
    e.preventDefault()
    setSaving(true); setError('')
    try {
      const r = await api.post('/api/schedule', { site_id: site.site_id, ...form }, token)
      const w = data.workers.find((x) => x.worker_id === form.worker_id)
      setInfo(`${w?.name} scheduled for ${r.shifts.length} day(s). ` +
        (r.delivered ? 'WhatsApp message sent ✓' : 'Message saved in the WhatsApp simulator (outside the 24-hour window or WhatsApp not live).'))
      setForm(null)
      await load()
    } catch (err) { setError(err.message) } finally { setSaving(false) }
  }

  async function removeShift(shift) {
    const w = data.workers.find((x) => x.worker_id === shift.worker_id)
    if (!window.confirm(`Remove ${w?.name || 'this worker'} from ${prettyDate(shift.date)}? They'll be told on WhatsApp.`)) return
    try {
      await api.del(`/api/schedule/${shift.worker_id}/${shift.date}`, token)
      setInfo(`Removed ${w?.name} from ${prettyDate(shift.date)}.`)
      await load()
    } catch (err) { setError(err.message) }
  }

  const config = useMemo(() => ({
    startDate: toDate(start),
    endDate: toDate(addDays(end, 1)),
    viewPreset: 'dayAndMonth',
    rowHeight: 54,
    barMargin: 8,
    eventStyle: 'tonal',
    readOnly: true,
    forceFit: true,
    columns: [
      { text: 'Worker', field: 'name', width: 160 },
      { text: 'Trade', field: 'trade', width: 100 },
    ],
    // The React wrapper takes each feature as its own `<name>Feature` prop.
    eventEditFeature: false,
    eventMenuFeature: false,
    scheduleMenuFeature: false,
    eventDragCreateFeature: false,
    timeRangesFeature: { showCurrentTimeLine: true },
    eventTooltipFeature: {
      template: ({ eventRecord }) => {
        if (eventRecord.kind === 'shift') {
          const s = eventRecord.shift
          const lines = [`${prettyDate(s.date)}: scheduled`, s.start_time ? `Start: ${s.start_time}` : '',
            s.task ? `Task: ${s.task}` : '', s.notified ? 'Told on WhatsApp ✓' : 'Not notified yet', 'Click to remove']
          return `<div style="text-align:left">${lines.filter(Boolean).map(esc).join('<br>')}</div>`
        }
        const d = eventRecord.day
        const lines = [
          `${prettyDate(d.date)}: ${STATUS[d.status]?.label || d.status}`,
          d.ot_hours ? `Overtime: ${d.ot_hours}h` : '',
          d.advance ? `Advance: ${money(d.advance, currency)}` : '',
          `Photos: ${d.photos}`,
          d.notes ? `Note: ${d.notes}` : '',
          d.pay_run_id ? `Paid in ${d.pay_run_id}` : `Review: ${d.review}`,
        ].filter(Boolean)
        return `<div style="text-align:left">${lines.map(esc).join('<br>')}</div>`
      },
    },
  }), [start, end, currency])

  const counts = data.days.reduce((acc, d) => { acc[d.status] = (acc[d.status] || 0) + 1; return acc }, {})
  const upcoming = (data.shifts || []).filter((s) => s.date >= today).length

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Site calendar</h1>
          <p>{site?.name}: the crew's last week and the plan ahead. <strong>Double-click an empty day</strong> to schedule a worker; they're told on WhatsApp.</p>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => setStart(addDays(start, -7))}>← Week</button>
          <span className="small muted">{prettyDate(start)} – {prettyDate(end)}</span>
          <button className="btn btn-secondary btn-sm" onClick={() => setStart(addDays(start, 7))}>Week →</button>
          <button className="btn btn-secondary btn-sm" onClick={() => setStart(addDays(today, -6))}>This week</button>
          <button className="btn btn-primary btn-sm" disabled={!data.workers.length} onClick={() => openForm('', addDays(today, 1))}>+ Schedule worker</button>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}
      {info && <div className="banner banner-success">{info}</div>}

      <div className="toolbar">
        {Object.entries(COLOR).map(([code]) => (
          <span key={code} className="row" style={{ gap: 6 }}>
            <span className={`status-pill status-${code}`}>{code}</span>
            <span className="small muted">{STATUS[code].label} ({counts[code] || 0})</span>
          </span>
        ))}
        <span className="row" style={{ gap: 6 }}>
          <span className="status-pill sp-shift-pill">📅</span>
          <span className="small muted">Scheduled ({upcoming})</span>
        </span>
        <span className="small muted">· faded = already paid</span>
      </div>

      <div className="card" style={{ height: Math.max(320, 110 + resources.length * 54), overflow: 'hidden' }}>
        <BryntumScheduler
          {...config}
          resources={resources}
          events={events}
          onEventClick={({ eventRecord }) => {
            if (eventRecord.kind === 'shift') removeShift(eventRecord.shift)
            else navigate(`/app?date=${eventRecord.day.date}`)
          }}
          onScheduleDblClick={({ date, resourceRecord }) => {
            const iso = toIso(date)
            if (iso < today) { setError("You can only schedule today or a future day."); return }
            openForm(resourceRecord?.id, iso)
          }}
        />
      </div>

      {form && (
        <>
          <div className="drawer-backdrop" onClick={() => !saving && setForm(null)} />
          <form className="drawer" onSubmit={saveShift} style={{ height: 'auto', bottom: 'auto', top: '10vh', right: '50%', transform: 'translateX(50%)', borderRadius: 16, width: 'min(440px, calc(100vw - 32px))' }}>
            <h2 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: 4 }}>Schedule a worker</h2>
            <p className="small muted" style={{ marginBottom: 16 }}>They'll get a WhatsApp message with the dates, start time and task.</p>
            <div className="field">
              <label>Worker</label>
              <select value={form.worker_id} onChange={(e) => setForm({ ...form, worker_id: e.target.value })}>
                {data.workers.map((w) => <option key={w.worker_id} value={w.worker_id}>{w.name} · {w.trade}</option>)}
              </select>
            </div>
            <div className="field-row">
              <div className="field"><label>From</label><input type="date" min={today} value={form.start} required
                onChange={(e) => setForm({ ...form, start: e.target.value, end: e.target.value > form.end ? e.target.value : form.end })} /></div>
              <div className="field"><label>To</label><input type="date" min={form.start} value={form.end} required
                onChange={(e) => setForm({ ...form, end: e.target.value })} /></div>
            </div>
            <div className="field-row">
              <div className="field"><label>Start time</label><input type="time" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} /></div>
              <div className="field"><label>Task (optional)</label><input value={form.task} maxLength={120} placeholder="Blockwork, 2nd floor"
                onChange={(e) => setForm({ ...form, task: e.target.value })} /></div>
            </div>
            <div className="row">
              <button className="btn btn-primary" disabled={saving}>{saving ? 'Scheduling…' : '📅 Schedule & notify on WhatsApp'}</button>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        </>
      )}
    </div>
  )
}
