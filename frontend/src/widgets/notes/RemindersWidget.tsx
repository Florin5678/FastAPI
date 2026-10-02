import { useState, type FormEvent } from 'react'
import { notesApi, type Reminder, type Repeat } from '../../api'
import type { WidgetProps } from '../types'
import './notes.css'

export type RemindersData = { reminders: Reminder[]; done: Reminder[] }

function dueLabel(iso: string | null): { text: string; tone: string } | null {
  if (!iso) return null
  const due = new Date(iso)
  const now = new Date()
  const time = due.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const days = Math.round(
    (new Date(due.getFullYear(), due.getMonth(), due.getDate()).getTime() -
      new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / 86400000,
  )
  if (due < now) return { text: days === 0 ? `Overdue · ${time}` : `Overdue · ${due.toLocaleDateString([], { day: 'numeric', month: 'short' })}`, tone: 'overdue' }
  if (days === 0) return { text: `Today ${time}`, tone: 'today' }
  if (days === 1) return { text: `Tomorrow ${time}`, tone: 'soon' }
  return { text: due.toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }), tone: 'later' }
}

// 1 -> "1st", 22 -> "22nd", 13 -> "13th"
function ordinal(n: number): string {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'
  return `${n}${suffix}`
}

function repeatText(repeat: Repeat, day: number | null): string {
  if (repeat === 'daily') return 'Every day'
  if (repeat === 'weekly') return 'Every week'
  return day ? `Every month on the ${ordinal(day)}` : 'Every month'
}

export function RemindersWidget({ data, reload }: WidgetProps<RemindersData>) {
  const [text, setText] = useState('')
  const [due, setDue] = useState('')
  const [repeat, setRepeat] = useState<Repeat | ''>('')
  const [showDone, setShowDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Runs a change, then reloads the widget; shows errors inline
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      reload()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const add = (e: FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    // datetime-local has no timezone: interpret it in the browser's zone, send as UTC
    const dueIso = due ? new Date(due).toISOString() : null
    run(async () => {
      await notesApi.addReminder(text.trim(), dueIso, dueIso && repeat ? repeat : null)
      setText('')
      setDue('')
      setRepeat('')
    })
  }

  const dueDay = due ? new Date(due).getDate() : null

  const row = (r: Reminder) => {
    const label = dueLabel(r.due)
    return (
      <li key={r.id} className={r.done ? 'reminder done' : 'reminder'}>
        <input
          type="checkbox"
          checked={r.done}
          disabled={busy}
          aria-label={r.done ? `Mark "${r.text}" as not done` : r.repeat ? `Done for now: move "${r.text}" to its next time` : `Mark "${r.text}" as done`}
          title={r.repeat && !r.done ? 'Done for now: moves it to the next time' : undefined}
          onChange={() => run(() => notesApi.updateReminder(r.id, { done: !r.done }))}
        />
        <span className="reminder-text">
          {r.text}
          {label && !r.done && (
            <span className={`due ${label.tone}`}>
              {label.text}{r.repeat && <span className="repeat"> · ↻ {repeatText(r.repeat, r.repeat_day).toLowerCase()}</span>}
            </span>
          )}
        </span>
        <button className="icon-button" disabled={busy} onClick={() => run(() => notesApi.deleteReminder(r.id))} aria-label={`Delete "${r.text}"`} title="Delete">✕</button>
      </li>
    )
  }

  const overdue = data.reminders.filter((r) => r.due && new Date(r.due) < new Date()).length

  return (
    <div className="notes-widget">
      {overdue > 0 && <p className="small reminders-overdue"><span className="dot" aria-hidden /> {overdue} overdue</p>}
      {error && <p className="error-text small">{error}</p>}

      <form className="quick-add" onSubmit={add}>
        <input type="text" placeholder="Remind me to…" value={text} onChange={(e) => setText(e.target.value)} maxLength={300} aria-label="Reminder" />
        <div className="quick-add-row">
          <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due (optional)" />
          <button type="submit" className="button primary small-button" disabled={busy || !text.trim()}>Add</button>
        </div>
        <select value={repeat} onChange={(e) => setRepeat(e.target.value as Repeat | '')} disabled={!due} aria-label="Repeat"
          title={due ? undefined : 'Pick a date and time to make it repeat'}>
          <option value="">Doesn't repeat</option>
          <option value="daily">{repeatText('daily', null)}</option>
          <option value="weekly">{repeatText('weekly', null)}</option>
          <option value="monthly">{repeatText('monthly', dueDay)}</option>
        </select>
      </form>

      {data.reminders.length === 0 ? (
        <p className="muted small">No open reminders.</p>
      ) : (
        <ul className="reminder-list">{data.reminders.map(row)}</ul>
      )}

      {data.done.length > 0 && (
        <>
          <button className="link" onClick={() => setShowDone(!showDone)}>
            {showDone ? 'Hide' : 'Show'} completed ({data.done.length})
          </button>
          {showDone && <ul className="reminder-list">{data.done.map(row)}</ul>}
        </>
      )}
    </div>
  )
}
