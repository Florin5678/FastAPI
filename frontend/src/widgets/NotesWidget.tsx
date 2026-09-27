import { useState, type FormEvent } from 'react'
import { notesApi, type Note, type Reminder } from '../api'
import type { WidgetProps } from './types'

export type NotesData = { reminders: Reminder[]; done: Reminder[]; notes: Note[] }

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

export function NotesWidget({ data, settings, reload }: WidgetProps<NotesData>) {
  const [tab, setTab] = useState<'Reminders' | 'Notes'>(settings.start_tab === 'Notes' ? 'Notes' : 'Reminders')
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

  const overdue = data.reminders.filter((r) => r.due && new Date(r.due) < new Date()).length

  return (
    <div className="notes-widget">
      <div className="segmented plain" role="tablist">
        <button className={tab === 'Reminders' ? 'active' : ''} onClick={() => setTab('Reminders')}>
          Reminders{data.reminders.length > 0 && ` (${data.reminders.length})`}
          {overdue > 0 && <span className="dot" aria-label={`${overdue} overdue`} />}
        </button>
        <button className={tab === 'Notes' ? 'active' : ''} onClick={() => setTab('Notes')}>
          Notes{data.notes.length > 0 && ` (${data.notes.length})`}
        </button>
      </div>

      {error && <p className="error-text small">{error}</p>}
      {tab === 'Reminders'
        ? <Reminders data={data} busy={busy} run={run} />
        : <Notes notes={data.notes} busy={busy} run={run} />}
    </div>
  )
}

type RunFn = (action: () => Promise<unknown>) => Promise<void>

function Reminders({ data, busy, run }: { data: NotesData; busy: boolean; run: RunFn }) {
  const [text, setText] = useState('')
  const [due, setDue] = useState('')
  const [showDone, setShowDone] = useState(false)

  const add = (e: FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    // datetime-local has no timezone: interpret it in the browser's zone, send as UTC
    const dueIso = due ? new Date(due).toISOString() : null
    run(async () => {
      await notesApi.addReminder(text.trim(), dueIso)
      setText('')
      setDue('')
    })
  }

  const row = (r: Reminder) => {
    const label = dueLabel(r.due)
    return (
      <li key={r.id} className={r.done ? 'reminder done' : 'reminder'}>
        <input
          type="checkbox"
          checked={r.done}
          disabled={busy}
          aria-label={r.done ? `Mark "${r.text}" as not done` : `Mark "${r.text}" as done`}
          onChange={() => run(() => notesApi.updateReminder(r.id, { done: !r.done }))}
        />
        <span className="reminder-text">
          {r.text}
          {label && !r.done && <span className={`due ${label.tone}`}>{label.text}</span>}
        </span>
        <button className="icon-button" disabled={busy} onClick={() => run(() => notesApi.deleteReminder(r.id))} aria-label={`Delete "${r.text}"`} title="Delete">✕</button>
      </li>
    )
  }

  return (
    <>
      <form className="quick-add" onSubmit={add}>
        <input type="text" placeholder="Remind me to…" value={text} onChange={(e) => setText(e.target.value)} maxLength={300} aria-label="Reminder" />
        <div className="quick-add-row">
          <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due (optional)" />
          <button type="submit" className="button primary small-button" disabled={busy || !text.trim()}>Add</button>
        </div>
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
    </>
  )
}

function Notes({ notes, busy, run }: { notes: Note[]; busy: boolean; run: RunFn }) {
  const [text, setText] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const add = (e: FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    run(async () => {
      await notesApi.addNote(text.trim())
      setText('')
    })
  }

  const save = (id: string) => {
    if (!draft.trim()) return
    run(async () => {
      await notesApi.updateNote(id, { text: draft.trim() })
      setEditing(null)
    })
  }

  return (
    <>
      <form className="quick-add" onSubmit={add}>
        <textarea placeholder="Write a note…" rows={2} value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} aria-label="New note" />
        <div className="quick-add-row end">
          <button type="submit" className="button primary small-button" disabled={busy || !text.trim()}>Add note</button>
        </div>
      </form>

      {notes.length === 0 && <p className="muted small">No notes yet.</p>}
      <ul className="note-list">
        {notes.map((n) => (
          <li key={n.id} className={n.pinned ? 'note pinned' : 'note'}>
            {editing === n.id ? (
              <>
                <textarea value={draft} rows={4} onChange={(e) => setDraft(e.target.value)} maxLength={2000} autoFocus aria-label="Edit note" />
                <div className="quick-add-row end">
                  <button className="button ghost small-button" onClick={() => setEditing(null)}>Cancel</button>
                  <button className="button primary small-button" disabled={busy || !draft.trim()} onClick={() => save(n.id)}>Save</button>
                </div>
              </>
            ) : (
              <>
                <p className="note-text">{n.text}</p>
                <div className="note-tools">
                  <button className={n.pinned ? 'icon-button on' : 'icon-button'} disabled={busy} onClick={() => run(() => notesApi.updateNote(n.id, { pinned: !n.pinned }))} aria-label={n.pinned ? 'Unpin' : 'Pin'} title={n.pinned ? 'Unpin' : 'Pin to top'}>📌</button>
                  <button className="icon-button" onClick={() => { setEditing(n.id); setDraft(n.text) }} aria-label="Edit note" title="Edit">✎</button>
                  <button className="icon-button" disabled={busy} onClick={() => run(() => notesApi.deleteNote(n.id))} aria-label="Delete note" title="Delete">✕</button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </>
  )
}
