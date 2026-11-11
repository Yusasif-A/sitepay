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

/** Multi-day site roster (Bryntum Scheduler): one row per worker, one bar
 *  per logged day, coloured by P / A / H / OT / L. Read-only; clicking a day
 *  opens it in the register. */
export default function SiteCalendar() {
  const { token, me } = useAuth()
  const { site } = useOutletContext()
  const navigate = useNavigate()
  const today = todayIn(me?.settings)
  const currency = me?.settings?.wage_currency || 'NGN'
  const [start, setStart] = useState(() => addDays(today, -13))
  const [data, setData] = useState({ workers: [], days: [] })
  const [error, setError] = useState('')
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
    id: w.worker_id, name: w.name, trade: w.trade, rate: money(w.daily_rate, currency),
  })), [data.workers, currency])

  const events = useMemo(() => data.days.map((d) => ({
    id: `${d.worker_id}|${d.date}`,
    resourceId: d.worker_id,
    startDate: toDate(d.date),
    endDate: toDate(addDays(d.date, 1)),
    // Plain text; Bryntum sets it as textContent.
    name: d.status + (d.ot_hours ? ` +${d.ot_hours}h` : ''),
    eventColor: COLOR[d.status] || 'gray',
    cls: d.pay_run_id ? 'sp-paid' : '',
    day: d,
  })), [data.days])

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
    eventTooltipFeature: {
      template: ({ eventRecord }) => {
        const d = eventRecord.day
        const lines = [
          `${prettyDate(d.date)}: ${STATUS[d.status]?.label || d.status}`,
          d.ot_hours ? `Overtime: ${d.ot_hours}h` : '',
          d.advance ? `Advance: ${money(d.advance, currency)}` : '',
          `Photos: ${d.photos}`,
          d.notes ? `Note: ${d.notes}` : '',
          d.pay_run_id ? `Paid in ${d.pay_run_id}` : `Review: ${d.review}`,
        ].filter(Boolean)
        // Escape everything we interpolate (notes are free text).
        const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
        return `<div style="text-align:left">${lines.map(esc).join('<br>')}</div>`
      },
    },
  }), [start, end, currency])

  const counts = data.days.reduce((acc, d) => { acc[d.status] = (acc[d.status] || 0) + 1; return acc }, {})

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Site calendar</h1>
          <p>{site?.name}: two weeks of the crew at a glance. Hover a day for details, click it to open that day's register.</p>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => setStart(addDays(start, -7))}>← Week</button>
          <span className="small muted">{prettyDate(start)} – {prettyDate(end)}</span>
          <button className="btn btn-secondary btn-sm" onClick={() => setStart(addDays(start, 7))}>Week →</button>
          <button className="btn btn-secondary btn-sm" onClick={() => setStart(addDays(today, -13))}>Last 2 weeks</button>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}

      <div className="toolbar">
        {Object.entries(COLOR).map(([code]) => (
          <span key={code} className="row" style={{ gap: 6 }}>
            <span className={`status-pill status-${code}`}>{code}</span>
            <span className="small muted">{STATUS[code].label} ({counts[code] || 0})</span>
          </span>
        ))}
        <span className="small muted">· faded = already paid</span>
      </div>

      <div className="card" style={{ height: Math.max(320, 110 + resources.length * 54), overflow: 'hidden' }}>
        <BryntumScheduler
          {...config}
          resources={resources}
          events={events}
          onEventClick={({ eventRecord }) => navigate(`/app?date=${eventRecord.day.date}`)}
        />
      </div>
    </div>
  )
}
