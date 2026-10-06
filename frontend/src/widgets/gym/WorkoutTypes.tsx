import { useState } from 'react'
import { gymApi } from '../../api'
import { seriesSlot } from './colors'

// The list of workout types, one per line, in order: the first `shown` are the log form's
// buttons, the rest come up under "Other…"; the order also sets each type's colour. Types
// added with "Other…" appear at the end. Renaming here doesn't rename workouts already logged.
export function WorkoutTypes({ types, shown, onSaved }: { types: string[]; shown: number; onSaved: () => void }) {
  const [text, setText] = useState(types.join('\n'))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  const changed = lines.join('\n') !== types.join('\n')
  const colors = Object.fromEntries(lines.map((k, i) => [k, (i % 12) + 1]))

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await gymApi.saveTypes(lines)
      setText(r.types.join('\n'))
      setSaved(true)
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card gym-types">
      <p className="muted small">
        One type per line. The first {shown} are the buttons when you log a workout; the rest come up under "Other…".
        The order also sets each type's colour. Types you add with "Other…" appear at the end.
      </p>
      <div className="gym-types-body">
        <textarea rows={Math.min(Math.max(lines.length + 1, 6), 20)} value={text} aria-label="Workout types, one per line"
          onChange={(e) => { setText(e.target.value); setSaved(false) }} />
        <ol className="gym-types-preview" aria-label="Preview">
          {lines.map((k, i) => (
            <li key={`${k}-${i}`} className={i < shown ? '' : 'hidden-type'}>
              <span className={`gym-swatch gym-series-${seriesSlot(k, colors)}`} aria-hidden />
              {k}{i === shown - 1 && <span className="muted small"> · last button</span>}
            </li>
          ))}
        </ol>
      </div>
      {error && <p className="error-text small">{error}</p>}
      <div className="dialog-actions">
        {saved && !changed && <span className="muted small">Saved.</span>}
        <button type="button" className="button primary" onClick={save} disabled={busy || !changed || lines.length === 0}>
          {busy ? 'Saving…' : 'Save types'}
        </button>
      </div>
    </div>
  )
}
