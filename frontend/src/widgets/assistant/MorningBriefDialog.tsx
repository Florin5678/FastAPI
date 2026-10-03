import { useState } from 'react'
import { assistantApi, localDate, type MorningBrief } from '../../api'
import { Dialog } from '../../components/Dialog'

// Today's brief, written by Claude after the time set in the Assistant settings (or now,
// with "Generate now"). Uses the AI chat's model and monthly budget.
export function MorningBriefDialog({ brief, onChanged, onClose }: { brief: MorningBrief; onChanged: () => void; onClose: () => void }) {
  const [current, setCurrent] = useState(brief)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const generate = async () => {
    setBusy(true)
    setError(null)
    setCurrent({ ...current, status: 'writing' })
    try {
      setCurrent({ ...current, ...(await assistantApi.generateMorningBrief()) })
      onChanged()
    } catch (err) {
      setError((err as Error).message)
      setCurrent(brief)
    } finally {
      setBusy(false)
    }
  }

  const isToday = current.day === localDate()
  const written = current.created_at ? new Date(current.created_at).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : null

  return (
    <Dialog title="☀️ Morning brief" onClose={onClose} wide>
      {current.status === 'writing' ? (
        <p className="muted">Claude is writing your brief… (about half a minute)</p>
      ) : current.text ? (
        <>
          <p className="muted small">
            {current.status === 'failed' ? 'Couldn\'t write the brief: ' : `Written ${written}${isToday ? '' : ' (not today\'s)'}.`}
          </p>
          <div className="morning-brief-text">{current.text}</div>
        </>
      ) : (
        <p className="muted">
          {current.enabled ? `Today's brief appears here after ${current.time}.` : 'Switch the morning brief on in the Assistant settings (⚙), or generate one now.'}
        </p>
      )}
      {error && <p className="error-text small">{error}</p>}
      <div className="dialog-actions">
        <span className="muted small morning-brief-cost">Uses the AI chat budget (about $0.01).</span>
        <button type="button" className="button ghost" onClick={generate} disabled={busy}>{current.text ? 'Write a new one' : 'Generate now'}</button>
        <button type="button" className="button primary" onClick={onClose}>Close</button>
      </div>
    </Dialog>
  )
}
