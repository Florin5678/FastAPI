import { useCallback, useEffect, useState } from 'react'
import { journalApi, type JournalEntry, type JournalPrompt } from '../api'
import { JournalComposer, QUICK_MOODS } from '../widgets/JournalComposer'

function dayHeading(day: string): string {
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

function timeOf(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
}

// Full view of the Journal widget: write, and read back / edit / delete past entries
export function JournalPage() {
  const [prompt, setPrompt] = useState<JournalPrompt | null | undefined>(undefined)
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadFirstPage = useCallback(() => {
    setLoading(true)
    journalApi.list()
      .then((page) => { setEntries(page.entries); setHasMore(page.has_more); setTotal(page.total) })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    journalApi.prompt().then(setPrompt).catch(() => setPrompt(null))
    loadFirstPage()
  }, [loadFirstPage])

  const loadMore = () => {
    setLoading(true)
    journalApi.list(entries[entries.length - 1]?.id)
      .then((page) => { setEntries((prev) => [...prev, ...page.entries]); setHasMore(page.has_more) })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  const replace = (entry: JournalEntry) => setEntries((prev) => prev.map((e) => (e.id === entry.id ? entry : e)))
  const drop = (id: number) => { setEntries((prev) => prev.filter((e) => e.id !== id)); setTotal((t) => t - 1) }

  // Group consecutive entries by day (they come newest first)
  const groups: { day: string; items: JournalEntry[] }[] = []
  for (const entry of entries) {
    const last = groups[groups.length - 1]
    if (last && last.day === entry.day) last.items.push(entry)
    else groups.push({ day: entry.day, items: [entry] })
  }

  return (
    <section className="journal-page">
      <div className="section-head">
        <h2>Journal</h2>
        <span className="muted">{total} entr{total === 1 ? 'y' : 'ies'} · private and encrypted</span>
      </div>

      <div className="card">
        {prompt === undefined
          ? <p className="muted">Loading…</p>
          : <JournalComposer initialPrompt={prompt} onSaved={() => loadFirstPage()} />}
      </div>

      {error && <p className="error-text">{error}</p>}
      {!loading && entries.length === 0 && !error && (
        <div className="empty journal-empty">No entries yet. Your first one will appear here.</div>
      )}

      {groups.map((group) => (
        <div key={group.day} className="journal-day">
          <h3>{dayHeading(group.day)}</h3>
          {group.items.map((entry) => (
            <EntryCard key={entry.id} entry={entry} onChanged={replace} onDeleted={drop} />
          ))}
        </div>
      ))}

      {loading && <p className="muted">Loading…</p>}
      {!loading && hasMore && <button className="button load-more" onClick={loadMore}>Older entries</button>}

      <p className="muted small crisis-note">
        Journaling isn't a substitute for professional help. In a crisis: 112 · Livslinien 70 201 201 (DK) · 0800 801 200 (RO).
      </p>
    </section>
  )
}

function EntryCard({ entry, onChanged, onDeleted }: { entry: JournalEntry; onChanged: (e: JournalEntry) => void; onDeleted: (id: number) => void }) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(entry.body)
  const [mood, setMood] = useState(entry.mood ?? '')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      onChanged(await journalApi.update(entry.id, { body, mood: mood.trim() || null }))
      setEditing(false)
    } catch (err) {
      setError((err as Error).message)
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
      setError((err as Error).message)
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
      {error && <p className="error-text small">{error}</p>}
    </article>
  )
}
