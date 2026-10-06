import { useState, type FormEvent } from 'react'
import { gymApi, localDate, type Workout } from '../../api'
import { Dialog } from '../../components/Dialog'
import { KindPicker } from './KindPicker'

// Change a logged workout: its type, minutes, day or note (the Gym tile and the monthly report)
export function EditWorkoutDialog({ workout, kinds, others, onSaved, onClose }: {
  workout: Workout
  kinds: string[] // the shown types (buttons)
  others: string[] // the hidden ones, suggested under "Other…"
  onSaved: () => void
  onClose: () => void
}) {
  const [kind, setKind] = useState(workout.kind)
  const [minutes, setMinutes] = useState(String(workout.minutes))
  const [day, setDay] = useState(workout.day)
  const [note, setNote] = useState(workout.note ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await gymApi.update(workout.id, { kind, minutes: Number(minutes), day, note: note.trim() })
      onSaved()
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <Dialog title="Edit workout" onClose={onClose}>
      <form className="settings-form edit-workout" onSubmit={save}>
        <KindPicker kinds={kinds} others={others} value={kind} onChange={setKind} />
        <label className="field">
          <span>Minutes</span>
          <input type="number" min={1} max={600} value={minutes} onChange={(e) => setMinutes(e.target.value)} />
        </label>
        <label className="field">
          <span>Day</span>
          <input type="date" value={day} max={localDate()} onChange={(e) => setDay(e.target.value || workout.day)} />
        </label>
        <label className="field">
          <span>Note <span className="muted">(optional)</span></span>
          <input type="text" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy || !(Number(minutes) > 0) || !kind.trim()}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}
