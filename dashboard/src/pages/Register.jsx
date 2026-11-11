import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'
import { api } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { STATUS, addDays, money, prettyDate, todayIn } from '../lib/format'
import EvidenceDrawer from './EvidenceDrawer'
import { CheckBadge } from '../components/AiCheck'

ModuleRegistry.registerModules([AllCommunityModule])

const gridTheme = themeQuartz.withParams({
  accentColor: '#c2410c',
  headerBackgroundColor: '#faf8f5',
  fontFamily: 'Inter, system-ui, sans-serif',
  rowHeight: 52,
})

function StatusCell({ value }) {
  return <span className={`status-pill status-${value || 'none'}`}>{value || '–'}</span>
}

/** The register's evidence column: the AI verdict for the day, then the
 *  one-line finding. Photos themselves are in the worker panel. */
function EvidenceCell({ data, showAi }) {
  const check = data.check
  const line = check?.work || check?.attendance || ''
  return (
    <div style={{ lineHeight: 1.3, paddingTop: 6 }}>
      <div className="row" style={{ gap: 6 }}>
        {showAi ? <CheckBadge check={check} compact /> :
          <span>{data.photo_count ? `📸 ${data.photo_count}` : <span className="muted">no photo</span>}</span>}
        {data.ot_claim_hours > 0 && data.ot_claim_hours !== data.ot_hours && <span className="chip chip-warn">claims {data.ot_claim_hours}h OT</span>}
        {check?.state === 'issues' && <span className="small" style={{ color: 'var(--color-danger)' }}>{check.issues[0]}</span>}
      </div>
      {showAi && line && <div className="small muted" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{line}</div>}
    </div>
  )
}

function ReviewCell({ data }) {
  // A day in a pay run is approved and locked; it's only "paid" once PayPal
  // has sent the money, which the Pay runs page shows per worker.
  if (data.pay_run_id) return <span className="chip chip-neutral">🔒 Approved</span>
  if (!data.logged) return <span className="muted small">—</span>
  const map = { pending: ['chip-warn', 'Review'], accepted: ['chip-ok', 'Accepted'], needs_photo: ['chip-bad', 'Needs photo'] }
  const [cls, label] = map[data.review] || ['chip-neutral', data.review]
  return <span className={`chip ${cls}`}>{label}</span>
}

export default function Register() {
  const { token, me } = useAuth()
  const { site } = useOutletContext()
  const navigate = useNavigate()
  const settings = me?.settings
  const currency = settings?.wage_currency || 'NGN'
  const [params] = useSearchParams()
  const [date, setDate] = useState(() => params.get('date') || todayIn(settings))
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(null)
  const [selected, setSelected] = useState([])
  const [parseText, setParseText] = useState('')
  const [parsed, setParsed] = useState(null)
  const gridRef = useRef(null)

  const load = useCallback(async () => {
    if (!site) return
    setLoading(true); setError('')
    try {
      const data = await api.get(`/api/register?site_id=${site.site_id}&date=${date}`, token)
      setRows(data.rows)
      setOpen((o) => (o ? data.rows.find((r) => r.worker_id === o.worker_id) || null : null))
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }, [site, date, token])

  useEffect(() => { load() }, [load])
  // Light polling so a worker's WhatsApp photo shows up without a refresh.
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden) load() }, 8000)
    return () => clearInterval(t)
  }, [load])

  async function saveCell(e) {
    const field = e.colDef.field
    const value = field === 'status' ? e.newValue : Number(e.newValue || 0)
    try {
      await api.put(`/api/register/${e.data.worker_id}/${date}`, { [field]: value }, token)
    } catch (err) { setError(err.message) }
    load()
  }

  async function bulk(fields) {
    try {
      const r = await api.post('/api/register/bulk', { site_id: site.site_id, date, worker_ids: selected, ...fields }, token)
      if (r.skipped.length) setError(r.skipped.join(' · '))
    } catch (err) { setError(err.message) }
    gridRef.current?.api.deselectAll()
    load()
  }

  async function runParse() {
    setParsed({ loading: true })
    try { setParsed(await api.post('/api/register/parse', { site_id: site.site_id, text: parseText }, token)) }
    catch (e) { setParsed({ ok: false, reason: e.message }) }
  }

  async function applyParsed() {
    for (const r of parsed.rows) {
      try {
        await api.put(`/api/register/${r.worker_id}/${date}`,
          { status: r.status, ot_hours: r.ot_hours, advance: r.advance, notes: r.notes }, token)
      } catch (e) { setError(e.message) }
    }
    setParsed(null); setParseText(''); load()
  }

  const columns = useMemo(() => [
    { field: 'name', headerName: 'Worker', pinned: 'left', minWidth: 160,
      cellRenderer: (p) => <button className="linklike" onClick={() => setOpen(p.data)}>{p.value}</button> },
    { field: 'trade', headerName: 'Trade', width: 115 },
    { field: 'daily_rate', headerName: `Rate`, width: 105, valueFormatter: (p) => money(p.value, currency) },
    { field: 'status', headerName: 'Status', width: 105, cellRenderer: StatusCell,
      editable: (p) => !p.data.pay_run_id, cellEditor: 'agSelectCellEditor',
      cellEditorParams: { values: Object.keys(STATUS) } },
    { field: 'ot_hours', headerName: 'OT hrs', width: 90, editable: (p) => !p.data.pay_run_id,
      cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 0, max: 12, precision: 1 } },
    { field: 'advance', headerName: 'Advance', width: 110, editable: (p) => !p.data.pay_run_id,
      cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 0 }, valueFormatter: (p) => (p.value ? money(p.value, currency) : '—') },
    { headerName: 'Day pay', width: 115, valueGetter: (p) => {
        const d = p.data
        if (!d.status) return null
        const f = { P: 1, A: 0, H: 0.5, OT: 1, L: 1 }[d.status]
        const ot = ['P', 'H', 'OT'].includes(d.status) ? d.ot_hours * d.ot_rate : 0
        return Math.round(f * d.daily_rate + ot)
      }, valueFormatter: (p) => (p.value == null ? '—' : money(p.value, currency)) },
    { headerName: 'AI check', flex: 1, minWidth: 280, cellRenderer: EvidenceCell,
      cellRendererParams: { showAi: !!settings?.ai_enabled } },
    { headerName: 'Review', width: 120, cellRenderer: ReviewCell },
    { field: 'notes', headerName: 'Notes', width: 150, tooltipField: 'notes' },
  ], [currency, settings?.ai_enabled])

  if (!me?.sites.length) {
    return (
      <div className="card panel">
        <h2>Create your first site</h2>
        <p className="muted" style={{ marginBottom: 12 }}>A site holds a crew and its daily register.</p>
        <Link className="btn btn-primary" to="/app/sites">Add a site</Link>
      </div>
    )
  }

  const logged = rows.filter((r) => r.logged)
  const totalDay = logged.reduce((s, r) => {
    const f = { P: 1, A: 0, H: 0.5, OT: 1, L: 1 }[r.status]
    return s + Math.round(f * r.daily_rate + (['P', 'H', 'OT'].includes(r.status) ? r.ot_hours * r.ot_rate : 0))
  }, 0)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Daily register</h1>
          <p>{site?.name} · {prettyDate(date)}. Click a cell to edit; click a name to see photos.</p>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => setDate(addDays(date, -1))}>←</button>
          <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
          <button className="btn btn-secondary btn-sm" onClick={() => setDate(addDays(date, 1))}>→</button>
          <button className="btn btn-secondary btn-sm" onClick={() => setDate(todayIn(settings))}>Today</button>
        </div>
      </div>

      <div className="stat-grid">
        <div className="card stat-card"><div className="stat-label">On register</div><div className="stat-value">{logged.length}/{rows.length}</div></div>
        <div className="card stat-card"><div className="stat-label">Present / OT</div><div className="stat-value">{logged.filter((r) => ['P', 'OT'].includes(r.status)).length}</div></div>
        <div className="card stat-card"><div className="stat-label">AI verified</div><div className="stat-value" style={{ color: 'var(--color-success)' }}>{logged.filter((r) => r.check?.state === 'verified').length}</div><div className="stat-sub">{logged.filter((r) => ['issues', 'no_proof'].includes(r.check?.state)).length} need a look</div></div>
        <div className="card stat-card"><div className="stat-label">Day's wages</div><div className="stat-value">{money(totalDay, currency)}</div></div>
      </div>

      {error && <div className="banner banner-error" onClick={() => setError('')}>{error}</div>}
      {rows.length === 0 && !loading && (
        <div className="banner banner-info">No crew on this site yet. <Link to="/app/crew">Add workers</Link> or load the demo crew.</div>
      )}

      <div className="toolbar">
        <span className="small muted">{selected.length ? `${selected.length} selected:` : 'Select rows to mark in bulk'}</span>
        {['P', 'H', 'A'].map((s) => (
          <button key={s} className="btn btn-secondary btn-sm" disabled={!selected.length} onClick={() => bulk({ status: s })}>
            Mark {STATUS[s].label}
          </button>
        ))}
        <button className="btn btn-secondary btn-sm" disabled={!selected.length} onClick={() => bulk({ review: 'accepted' })}>Accept</button>
        <span className="spacer" />
        <button className="btn btn-primary btn-sm" onClick={() => navigate(`/app/pay?start=${date}&end=${date}`)}>Approve & pay this day →</button>
      </div>

      <div style={{ height: Math.min(560, 120 + rows.length * 52), minHeight: 260 }}>
        <AgGridReact
          ref={gridRef}
          theme={gridTheme}
          rowData={rows}
          columnDefs={columns}
          getRowId={(p) => p.data.worker_id}
          rowSelection={{ mode: 'multiRow', checkboxes: true, headerCheckbox: true, enableClickSelection: false,
            isRowSelectable: (n) => !n.data?.pay_run_id }}
          onSelectionChanged={(e) => setSelected(e.api.getSelectedRows().map((r) => r.worker_id))}
          onCellValueChanged={saveCell}
          singleClickEdit
          stopEditingWhenCellsLoseFocus
          loading={loading && rows.length === 0}
        />
      </div>

      {settings?.ai_enabled && <div className="card panel" style={{ marginTop: 20 }}>
        <h2>Paste a messy register</h2>
        <p className="small muted" style={{ marginBottom: 10 }}>
          e.g. “Musa full day +2hrs, Chinedu left 1pm took 1k, Ibrahim no show”. The AI turns it into rows; you check them before anything is saved.
        </p>
        <textarea className="inline-input" style={{ width: '100%' }} rows={3} value={parseText} onChange={(e) => setParseText(e.target.value)} />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn btn-secondary btn-sm" disabled={parseText.trim().length < 2 || parsed?.loading} onClick={runParse}>
            {parsed?.loading ? 'Reading…' : 'Read with AI'}
          </button>
        </div>
        {parsed && !parsed.loading && (
          parsed.ok ? (
            <div style={{ marginTop: 14 }}>
              <table className="table">
                <thead><tr><th>Worker</th><th>From text</th><th>Status</th><th>OT</th><th>Advance</th><th>Notes</th></tr></thead>
                <tbody>{parsed.rows.map((r) => (
                  <tr key={r.worker_id}><td>{r.worker_name}</td><td className="muted">{r.matched_from}</td>
                    <td><StatusCell value={r.status} /></td><td>{r.ot_hours || '—'}</td>
                    <td>{r.advance ? money(r.advance, currency) : '—'}</td><td>{r.notes}</td></tr>
                ))}</tbody>
              </table>
              {parsed.unmatched.length > 0 && <p className="small muted">Not matched to crew: {parsed.unmatched.join(', ')}</p>}
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn btn-primary btn-sm" disabled={!parsed.rows.length} onClick={applyParsed}>Apply {parsed.rows.length} rows to {prettyDate(date)}</button>
                <button className="btn btn-secondary btn-sm" onClick={() => setParsed(null)}>Discard</button>
              </div>
            </div>
          ) : <div className="banner banner-warn" style={{ marginTop: 12 }}>{parsed.reason}</div>
        )}
      </div>}

      {open && <EvidenceDrawer row={open} date={date} currency={currency} showAi={!!settings?.ai_enabled} onClose={() => setOpen(null)} onChanged={load} />}
    </div>
  )
}
