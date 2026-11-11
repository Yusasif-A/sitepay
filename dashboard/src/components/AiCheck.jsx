/** The AI check for a worker-day: verdict badge + the two findings the
 *  supervisor acts on (attendance, work done) + the checklist behind them. */

export const CHECK_TONE = {
  verified: 'ok', issues: 'bad', no_proof: 'bad', pending: 'warn',
  unavailable: 'neutral', manual: 'neutral', absent: 'neutral', none: 'neutral',
}

const ICON = { verified: '✅', issues: '⚠️', no_proof: '⛔', pending: '⏳', unavailable: '—', manual: '✍️', absent: '·' }

export function CheckBadge({ check, compact }) {
  if (!check || check.state === 'none') return <span className="muted small">—</span>
  const tone = CHECK_TONE[check.state] || 'neutral'
  const extra = check.state === 'issues' && !compact ? ` · ${check.issues.length}` : ''
  return <span className={`chip chip-${tone}`}>{ICON[check.state]} {check.label}{extra}</span>
}

export default function AiCheck({ check, onRerun, busy }) {
  if (!check || check.state === 'none') return null
  const tone = CHECK_TONE[check.state] || 'neutral'
  return (
    <div className={`ai-check ai-check-${tone}`}>
      <div className="row" style={{ marginBottom: 10 }}>
        <strong style={{ fontSize: '0.95rem' }}>AI check</strong>
        <CheckBadge check={check} />
        <span className="spacer" />
        {onRerun && (
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={onRerun}>
            {busy ? 'Checking…' : '↻ Run AI check'}
          </button>
        )}
      </div>

      {check.state === 'no_proof' && (
        <p className="small" style={{ marginBottom: 10 }}>
          On the register, but the worker never shared a location or a check-in photo for this day.
          Don't pay this day without asking them.
        </p>
      )}
      {check.state === 'manual' && (
        <p className="small" style={{ marginBottom: 10 }}>You logged this day on the dashboard. There's no WhatsApp proof to check.</p>
      )}
      {check.state === 'unavailable' && (
        <p className="small" style={{ marginBottom: 10 }}>The AI couldn't read these photos. Look at them yourself, or run the check again.</p>
      )}

      {(check.attendance || check.work) && (
        <div className="ai-findings">
          {check.attendance && <p><span className="ai-tag">Attendance</span>{check.attendance}</p>}
          {check.work && (
            <p>
              <span className="ai-tag">Work done</span>{check.work}
              {check.work_status === 'completed' && <span className="chip chip-ok" style={{ marginLeft: 6 }}>Completed</span>}
              {check.work_status === 'in_progress' && <span className="chip chip-neutral" style={{ marginLeft: 6 }}>In progress</span>}
            </p>
          )}
        </div>
      )}

      {check.items?.length > 0 && (
        <ul className="ai-items">
          {check.items.map((i) => (
            <li key={i.label} className={i.ok ? 'ok' : 'bad'}>
              <span>{i.ok ? '✓' : '✗'}</span>
              <span>{i.label}{i.detail ? <em> · {i.detail}</em> : null}</span>
            </li>
          ))}
        </ul>
      )}
      {check.sample_data && <p className="small muted" style={{ marginTop: 8 }}>Sample data from “Load demo crew”.</p>}
    </div>
  )
}
