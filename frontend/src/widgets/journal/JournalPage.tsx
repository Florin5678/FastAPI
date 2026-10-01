import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  isJournalLocked, journalApi, localDate, shiftDay,
  type JournalAccess, type JournalEntry, type JournalHistory, type JournalPrompt, type MoodMonth,
} from '../../api'
import { JournalComposer } from './JournalComposer'
import { QUICK_MOODS } from './moods'
import { MoodMonths } from './MoodMonths'
import { dayTitle, longDate } from '../../lib/dates'

const RANGES: { label: string; days: number }[] = [
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: 'Year', days: 365 },
  { label: 'All', days: 3660 },
]
const MONTH_RANGES = [3, 6, 12]

function timeOf(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
}

const GOOGLE_CONFIRM = '/auth/google/login?purpose=journal'
const digitsOnly = (value: string) => value.replace(/\D/g, '')

// The journal's history is locked (server-enforced): unlock with the PIN. Setting one up
// the first time, or after "Forgot PIN?", takes a one-time Google confirmation.
export function JournalPage() {
  const [access, setAccess] = useState<JournalAccess | null>(null)
  const [error, setError] = useState<string | null>(null)

  const check = useCallback(() => {
    journalApi.access().then(setAccess).catch((err) => setError(err.message))
  }, [])
  useEffect(check, [check])

  // Re-check (and so lock the page) when the unlock window ends
  useEffect(() => {
    if (!access?.unlocked || !access.expires_at) return
    const ms = new Date(access.expires_at).getTime() - Date.now()
    const timer = setTimeout(check, Math.max(ms, 0) + 500)
    return () => clearTimeout(timer)
  }, [access, check])

  const lock = async () => {
    await journalApi.lock().catch(() => undefined)
    check()
  }

  if (error) return <p className="error-text">{error}</p>
  if (!access) return <p className="muted">Loading…</p>
  if (!access.unlocked) return <LockScreen access={access} onUnlocked={setAccess} />
  return <JournalHistoryView access={access} onAccess={setAccess} onLock={lock} onLocked={check} />
}

function LockScreen({ access, onUnlocked }: { access: JournalAccess; onUnlocked: (a: JournalAccess) => void }) {
  const [pin, setPin] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onUnlocked(await journalApi.unlock(pin))
    } catch (err) {
      setError((err as Error).message)
      setPin('')
    } finally {
      setBusy(false)
    }
  }

  let body
  if (!access.has_pin) {
    body = (
      <>
        <h2>Set up your journal PIN</h2>
        <p className="muted">
          Confirm it's you with Google once, then choose a 4–8 digit PIN. After that, your PIN is all you need.
        </p>
        <a className="button primary large" href={GOOGLE_CONFIRM}>Confirm with Google</a>
      </>
    )
  } else if (access.pin_blocked) {
    body = (
      <>
        <h2>PIN blocked</h2>
        <p className="muted">Too many wrong PINs. Confirm it's you with Google, then choose a new PIN.</p>
        <a className="button primary large" href={GOOGLE_CONFIRM}>Confirm with Google</a>
      </>
    )
  } else {
    body = (
      <>
        <h2>Your journal is private</h2>
        <p className="muted">Enter your PIN. It stays open for 15 minutes.</p>
        <form className="pin-form" onSubmit={submit}>
          <input
            className="pin-input"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="off"
            maxLength={8}
            autoFocus
            value={pin}
            onChange={(e) => setPin(digitsOnly(e.target.value))}
            aria-label="PIN"
            placeholder="••••"
          />
          <button type="submit" className="button primary large" disabled={busy || pin.length < 4}>
            {busy ? 'Checking…' : 'Unlock'}
          </button>
        </form>
        {error && <p className="error-text small">{error}</p>}
        <a className="link" href={GOOGLE_CONFIRM}>Forgot your PIN? Confirm with Google</a>
      </>
    )
  }

  return (
    <section className="journal-lock">
      <div className="card lock-card">
        <div className="lock-icon" aria-hidden>🔒</div>
        {body}
        <p className="muted small">You can still write new entries from the Journal widget on your dashboard.</p>
      </div>
    </section>
  )
}

// Choose a new PIN: first time (after Google), after "Forgot PIN?", or to change it
function PinSetup({ title, onDone, onCancel }: { title: string; onDone: (a: JournalAccess) => void; onCancel?: () => void }) {
  const [pin, setPin] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (pin !== repeat) {
      setError("The two PINs don't match.")
      return
    }
    setBusy(true)
    setError(null)
    try {
      onDone(await journalApi.setPin(pin))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card pin-setup" onSubmit={submit}>
      <strong>{title}</strong>
      <p className="muted small">4 to 8 digits. You'll use it to open your journal from now on.</p>
      <div className="pin-setup-row">
        <input className="pin-input" type="password" inputMode="numeric" pattern="[0-9]*" autoComplete="new-password" maxLength={8}
          value={pin} onChange={(e) => setPin(digitsOnly(e.target.value))} aria-label="New PIN" placeholder="New PIN" autoFocus />
        <input className="pin-input" type="password" inputMode="numeric" pattern="[0-9]*" autoComplete="new-password" maxLength={8}
          value={repeat} onChange={(e) => setRepeat(digitsOnly(e.target.value))} aria-label="Repeat the new PIN" placeholder="Repeat" />
        <button type="submit" className="button primary" disabled={busy || pin.length < 4 || repeat.length < 4}>Save PIN</button>
        {onCancel && <button type="button" className="button ghost" onClick={onCancel}>Cancel</button>}
      </div>
      {error && <p className="error-text small">{error}</p>}
    </form>
  )
}

function JournalHistoryView({ access, onAccess, onLock, onLocked }: {
  access: JournalAccess
  onAccess: (a: JournalAccess) => void
  onLock: () => void
  onLocked: () => void
}) {
  const expiresAt = access.expires_at
  const [changingPin, setChangingPin] = useState(false)
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
          {access.has_pin && !access.pin_blocked && !changingPin && (
            <button className="button ghost small-button" onClick={() => setChangingPin(true)}>Change PIN</button>
          )}
          <button className="button ghost small-button" onClick={onLock}>Lock</button>
        </span>
      </div>
      {error && <p className="error-text">{error}</p>}

      {(!access.has_pin || access.pin_blocked) && (
        <PinSetup title={access.pin_blocked ? 'Choose a new PIN' : 'Choose a PIN for your journal'} onDone={onAccess} />
      )}
      {changingPin && (
        <PinSetup
          title="Change your PIN"
          onDone={(a) => { onAccess(a); setChangingPin(false) }}
          onCancel={() => setChangingPin(false)}
        />
      )}

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
