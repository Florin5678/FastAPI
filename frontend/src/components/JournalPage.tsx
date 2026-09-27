import { useCallback, useEffect, useState } from 'react'
import {
  isJournalLocked, journalApi, localDate, shiftDay,
  type JournalEntry, type JournalHistory, type JournalPrompt, type MoodMonth,
} from '../api'
import { JournalComposer, QUICK_MOODS } from '../widgets/JournalComposer'
import { MoodMonths } from './MoodMonths'

const RANGES: { label: string; days: number }[] = [
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: 'Year', days: 365 },
  { label: 'All', days: 3660 },
]
const MONTH_RANGES = [3, 6, 12]

function dayTitle(day: string): string {
  const today = localDate()
  if (day === today) return 'Today'
  if (day === shiftDay(today, -1)) return 'Yesterday'
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'long' })
}

function longDate(day: string): string {
  return new Date(day + 'T12:00').toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' })
}

function timeOf(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
}

// The journal's history is locked behind a fresh Google sign-in (server-enforced)
export function JournalPage() {
  const [access, setAccess] = useState<{ unlocked: boolean; expires_at: string | null } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const check = useCallback(() => {
    journalApi.access().then(setAccess).catch((err) => setError(err.message))
  }, [])
  useEffect(check, [check])

  // Lock the page when the unlock window ends
  useEffect(() => {
    if (!access?.unlocked || !access.expires_at) return
    const ms = new Date(access.expires_at).getTime() - Date.now()
    const timer = setTimeout(() => setAccess({ unlocked: false, expires_at: null }), Math.max(ms, 0))
    return () => clearTimeout(timer)
  }, [access])

  const lock = async () => {
    await journalApi.lock().catch(() => undefined)
    setAccess({ unlocked: false, expires_at: null })
  }

  if (error) return <p className="error-text">{error}</p>
  if (!access) return <p className="muted">Loading…</p>
  if (!access.unlocked) return <LockScreen />
  return <JournalHistoryView expiresAt={access.expires_at} onLock={lock} onLocked={() => setAccess({ unlocked: false, expires_at: null })} />
}

function LockScreen() {
  return (
    <section className="journal-lock">
      <div className="card lock-card">
        <div className="lock-icon" aria-hidden>🔒</div>
        <h2>Your journal is private</h2>
        <p className="muted">
          Confirm it's you with Google to read your past entries. It stays open for 15 minutes.
        </p>
        <a className="button primary large" href="/auth/google/login?purpose=journal">Confirm with Google</a>
        <p className="muted small">You can still write new entries from the Journal widget on your dashboard.</p>
      </div>
    </section>
  )
}

function JournalHistoryView({ expiresAt, onLock, onLocked }: { expiresAt: string | null; onLock: () => void; onLocked: () => void }) {
  const today = localDate()
  const [day, setDay] = useState(today)
  const [dayEntries, setDayEntries] = useState<JournalEntry[] | null>(null)
  const [prompt, setPrompt] = useState<JournalPrompt | null | undefined>(undefined)
  const [range, setRange] = useState(90)
  const [history, setHistory] = useState<JournalHistory | null>(null)
  const [monthsBack, setMonthsBack] = useState(6)
  const [months, setMonths] = useState<MoodMonth[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Any "locked" answer (window expired, locked elsewhere) returns to the lock screen
  const handle = useCallback((err: unknown) => {
    if (isJournalLocked(err)) onLocked()
    else setError((err as Error).message)
  }, [onLocked])

  const loadDay = useCallback(() => {
    journalApi.day(day).then((d) => setDayEntries(d.entries)).catch(handle)
  }, [day, handle])
  const loadHistory = useCallback(() => {
    journalApi.history(today, range).then(setHistory).catch(handle)
  }, [today, range, handle])
  const loadMoods = useCallback(() => {
    journalApi.moods(today, monthsBack).then((r) => setMonths(r.months)).catch(handle)
  }, [today, monthsBack, handle])

  useEffect(loadDay, [loadDay])
  useEffect(loadHistory, [loadHistory])
  useEffect(loadMoods, [loadMoods])
  useEffect(() => { journalApi.prompt().then(setPrompt).catch(() => setPrompt(null)) }, [])

  const changed = () => { loadDay(); loadHistory(); loadMoods() }

  const goTo = (next: string) => {
    if (next > today) return
    setDayEntries(null)
    setDay(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const locksAt = expiresAt ? new Date(expiresAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''

  return (
    <section className="journal-page">
      <div className="section-head">
        <h2>Journal</h2>
        <span className="lock-status">
          <span className="muted small">🔓 Open until {locksAt}</span>
          <button className="button ghost small-button" onClick={onLock}>Lock</button>
        </span>
      </div>
      {error && <p className="error-text">{error}</p>}

      <div className="day-nav">
        <button className="button" onClick={() => goTo(shiftDay(day, -1))} aria-label="Previous day">‹</button>
        <div className="day-nav-label">
          <strong>{dayTitle(day)}</strong>
          <span className="muted small">{longDate(day)}</span>
        </div>
        <button className="button" onClick={() => goTo(shiftDay(day, 1))} disabled={day >= today} aria-label="Next day">›</button>
        <input type="date" className="day-picker" value={day} max={today} onChange={(e) => e.target.value && goTo(e.target.value)} aria-label="Pick a day" />
        {day !== today && <button className="button ghost" onClick={() => goTo(today)}>Today</button>}
      </div>

      {day === today && prompt !== undefined && (
        <div className="card composer-card">
          <JournalComposer initialPrompt={prompt} onSaved={changed} />
        </div>
      )}

      {dayEntries === null && <p className="muted">Loading…</p>}
      {dayEntries?.length === 0 && (
        <div className="empty">{day === today ? 'No entries yet today.' : 'Nothing written on this day.'}</div>
      )}
      {dayEntries?.map((entry) => (
        <EntryCard
          key={entry.id}
          entry={entry}
          onError={handle}
          onChanged={(e) => { setDayEntries((prev) => prev?.map((x) => (x.id === e.id ? e : x)) ?? null); loadHistory(); loadMoods() }}
          onDeleted={(id) => { setDayEntries((prev) => prev?.filter((x) => x.id !== id) ?? null); loadHistory(); loadMoods() }}
        />
      ))}

      <div className="section-head history-head">
        <h2>Mood by month</h2>
        <div className="segmented" role="group" aria-label="Months">
          {MONTH_RANGES.map((n) => (
            <button key={n} className={monthsBack === n ? 'active' : ''} onClick={() => setMonthsBack(n)}>{n} months</button>
          ))}
        </div>
      </div>
      {months && <MoodMonths months={months} today={today} onPickDay={goTo} />}

      <div className="section-head history-head">
        <h2>History</h2>
        <div className="segmented" role="group" aria-label="Range">
          {RANGES.map((r) => (
            <button key={r.days} className={range === r.days ? 'active' : ''} onClick={() => setRange(r.days)}>{r.label}</button>
          ))}
        </div>
      </div>
      {history && (
        <>
          <p className="muted small history-summary">
            {history.total} entr{history.total === 1 ? 'y' : 'ies'} in total
            {history.streak > 0 && ` · 🔥 ${history.streak}-day streak`}
            {history.first_entry_day && ` · writing since ${longDate(history.first_entry_day)}`}
          </p>
          {history.days.length === 0 ? (
            <div className="empty">No entries in this period.</div>
          ) : (
            <div className="table-scroll">
              <table className="history-table journal-history">
                <thead>
                  <tr>
                    <th scope="col">Day</th>
                    <th scope="col">Mood</th>
                    <th scope="col">Entries</th>
                    <th scope="col">Words</th>
                    <th scope="col" className="preview-col">Beginning</th>
                  </tr>
                </thead>
                <tbody>
                  {history.days.map((d) => (
                    <tr
                      key={d.day}
                      className={d.day === day ? 'selected' : ''}
                      onClick={() => goTo(d.day)}
                      tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && goTo(d.day)}
                    >
                      <th scope="row">{new Date(d.day + 'T12:00').toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}</th>
                      <td className="moods-cell">{d.moods.join(' ') || '–'}</td>
                      <td>{d.entries}</td>
                      <td>{d.words}</td>
                      <td className="preview-col">{d.preview}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <p className="muted small crisis-note">
        Journaling isn't a substitute for professional help. In a crisis: 112 · Livslinien 70 201 201 (DK) · 0800 801 200 (RO).
      </p>
    </section>
  )
}

function EntryCard({ entry, onChanged, onDeleted, onError }: {
  entry: JournalEntry
  onChanged: (e: JournalEntry) => void
  onDeleted: (id: number) => void
  onError: (err: unknown) => void
}) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(entry.body)
  const [mood, setMood] = useState(entry.mood ?? '')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      onChanged(await journalApi.update(entry.id, { body, mood: mood.trim() || null }))
      setEditing(false)
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await journalApi.remove(entry.id)
      onDeleted(entry.id)
    } catch (err) {
      onError(err)
      setBusy(false)
    }
  }

  return (
    <article className="entry-card">
      <div className="entry-head">
        <span className="entry-mood" aria-label={entry.mood ? `Mood ${entry.mood}` : 'No mood'}>{entry.mood ?? ''}</span>
        <span className="muted small">{timeOf(entry.created_at)}</span>
        <span className="entry-tools">
          {!editing && <button className="icon-button" onClick={() => setEditing(true)} aria-label="Edit entry" title="Edit">✎</button>}
          {confirmDelete ? (
            <>
              <button className="button small-button danger" onClick={remove} disabled={busy}>Delete</button>
              <button className="button ghost small-button" onClick={() => setConfirmDelete(false)}>Keep</button>
            </>
          ) : (
            <button className="icon-button" onClick={() => setConfirmDelete(true)} aria-label="Delete entry" title="Delete">✕</button>
          )}
        </span>
      </div>

      {entry.prompt_text && <p className="prompt-text">{entry.prompt_text}</p>}

      {editing ? (
        <div className="entry-edit">
          <div className="mood-row">
            {QUICK_MOODS.map((emoji) => (
              <button key={emoji} type="button" className={mood === emoji ? 'mood active' : 'mood'} onClick={() => setMood(mood === emoji ? '' : emoji)}>{emoji}</button>
            ))}
            <input className="mood-custom" value={QUICK_MOODS.includes(mood) ? '' : mood} onChange={(e) => setMood(e.target.value)} maxLength={16} placeholder="any 🙃" aria-label="Any emoji for your mood" />
          </div>
          <textarea className="journal-body" rows={6} value={body} onChange={(e) => setBody(e.target.value)} maxLength={20000} aria-label="Edit entry" />
          <div className="composer-actions">
            <button className="button ghost small-button" onClick={() => { setEditing(false); setBody(entry.body); setMood(entry.mood ?? '') }}>Cancel</button>
            <button className="button primary small-button" onClick={save} disabled={busy || !body.trim()}>Save</button>
          </div>
        </div>
      ) : (
        <p className="entry-body">{entry.body}</p>
      )}
    </article>
  )
}
