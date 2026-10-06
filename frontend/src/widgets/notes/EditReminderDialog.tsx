import { useState, type FormEvent } from 'react'
import { notesApi, type Reminder, type Repeat } from '../../api'
import { Dialog } from '../../components/Dialog'
import { repeatText } from './repeat'

// ISO instant -> the value a datetime-local input shows (the browser's local time)
function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// Change a reminder: its text, due time (or none) and how it repeats
export function EditReminderDialog({ reminder, onSaved, onClose }: { reminder: Reminder; onSaved: () => void; onClose: () => void }) {
  const [text, setText] = useState(reminder.text)
  const [due, setDue] = useState(toLocalInput(reminder.due))
  const [repeat, setRepeat] = useState<Repeat | ''>(reminder.repeat ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      await notesApi.updateReminder(reminder.id, {
        text: text.trim(),
        due: due ? new Date(due).toISOString() : null,
        repeat: due && repeat ? repeat : null,
      })
      onSaved()
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  const dueDay = due ? new Date(due).getDate() : null
  return (
    <Dialog title="Edit reminder" onClose={onClose}>
      <form className="settings-form quick-add" onSubmit={save}>
        <label className="field">
          <span>Remind me to</span>
          <input type="text" value={text} maxLength={300} autoFocus onChange={(e) => setText(e.target.value)} />
        </label>
        <label className="field">
          <span>When <span className="muted">(optional)</span></span>
          <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <select value={repeat} onChange={(e) => setRepeat(e.target.value as Repeat | '')} disabled={!due} aria-label="Repeat">
          <option value="">Doesn't repeat</option>
          <option value="daily">{repeatText('daily', null)}</option>
          <option value="weekly">{repeatText('weekly', null)}</option>
          <option value="monthly">{repeatText('monthly', dueDay)}</option>
        </select>
        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy || !text.trim()}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}
