/** The AI check for a worker-day. The supervisor reads this instead of
 *  looking at every photo: one conclusion, three answers, then confirms. */

export const CHECK_TONE = {
  verified: 'ok', issues: 'bad', no_proof: 'bad', pending: 'warn',
  unavailable: 'neutral', manual: 'neutral', absent: 'neutral', none: 'neutral',
}

const ICON = { verified: '✅', issues: '⚠️', no_proof: '⛔', pending: '⏳', unavailable: '—', manual: '✍️', absent: '·' }

export function CheckBadge({ check }) {
  if (!check || check.state === 'none') return <span className="muted small">—</span>
  const tone = CHECK_TONE[check.state] || 'neutral'
  return <span className={`chip chip-${tone}`}>{ICON[check.state]} {check.label}</span>
}

export default function AiCheck({ check, onRerun, busy }) {
  if (!check || check.state === 'none') return null
  const tone = CHECK_TONE[check.state] || 'neutral'
  return (
    <div className={`ai-check ai-check-${tone}`}>
      <div className="row" style={{ marginBottom: 8 }}>
        <strong>🤖 AI check</strong>
        <CheckBadge check={check} />
        <span className="spacer" />
        {onRerun && (
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={onRerun}>
            {busy ? 'Checking…' : '↻ Re-check'}
          </button>
        )}
      </div>

      <p className="ai-verdict">{check.verdict}</p>

      {check.answers?.length > 0 && (
        <div className="ai-answers">
          {check.answers.map((a) => (
            <div key={a.q} className={`ai-answer ${a.ok ? 'ok' : 'bad'}`}>
              <span className="ai-answer-icon">{a.ok ? '✓' : '✗'}</span>
              <div>
                <div className="ai-answer-q">{a.q}</div>
                <div className="ai-answer-a">{a.a}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
