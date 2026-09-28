import { useEffect, useState } from 'react'
import { coursesApi, type DriveFolder, type PickedFile } from '../../api'
import { Dialog } from '../../components/Dialog'

const MAX_FILES = 40
type Place = { folder: string; name: string }

// Browse Google Drive (My Drive, Shared with me, search) and tick the Docs and PDFs the
// Courses widget should read. A file's "course" is the folder it was picked from.
export function FilePicker({ onSaved, onClose }: { onSaved: () => void; onClose: () => void }) {
  const [trail, setTrail] = useState<Place[]>([{ folder: 'root', name: 'My Drive' }])
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('') // the submitted search
  const [listing, setListing] = useState<{ key: string; data?: DriveFolder; error?: string } | null>(null)
  const [selected, setSelected] = useState<Map<string, PickedFile> | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const here = trail[trail.length - 1]
  const key = search ? `q:${search}` : here.folder

  useEffect(() => {
    let cancelled = false
    coursesApi.picked()
      .then((r) => { if (!cancelled) setSelected(new Map(r.files.map((f) => [f.id, f]))) })
      .catch((err) => { if (!cancelled) setError((err as Error).message) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    coursesApi.browse(search ? 'root' : here.folder, search)
      .then((data) => { if (!cancelled) setListing({ key, data }) })
      .catch((err) => { if (!cancelled) setListing({ key, error: (err as Error).message }) })
    return () => { cancelled = true }
  }, [key, here.folder, search])

  const current = listing?.key === key ? listing : null
  // Files picked inside a real folder get that folder's name as their course
  const course = search || here.folder === 'root' || here.folder === 'shared' ? '' : here.name

  const open = (place: Place, fromTop = false) => {
    setSearch('')
    setQuery('')
    setTrail(fromTop ? [place] : [...trail, place])
  }

  const toggle = (id: string, name: string) => {
    if (!selected) return
    const next = new Map(selected)
    if (next.has(id)) next.delete(id)
    else if (next.size < MAX_FILES) next.set(id, { id, name, course })
    setSelected(next)
  }

  const save = async () => {
    if (!selected) return
    setSaving(true)
    setError(null)
    try {
      await coursesApi.pick([...selected.values()].map((f) => ({ id: f.id, course: f.course })))
      onSaved()
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <Dialog title="Choose course files" onClose={onClose}>
      <div className="picker">
        <div className="segmented plain picker-tabs">
          <button className={!search && trail[0].folder === 'root' ? 'active' : ''} onClick={() => open({ folder: 'root', name: 'My Drive' }, true)}>My Drive</button>
          <button className={!search && trail[0].folder === 'shared' ? 'active' : ''} onClick={() => open({ folder: 'shared', name: 'Shared with me' }, true)}>Shared with me</button>
        </div>
        <form className="picker-search" onSubmit={(e) => { e.preventDefault(); setSearch(query.trim()) }}>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by file name" aria-label="Search Drive" />
          <button className="button ghost small-button" type="submit" disabled={!query.trim()}>Search</button>
        </form>

        <div className="picker-trail">
          {search ? (
            <>Results for "{search}" · <button className="link-button" onClick={() => { setSearch(''); setQuery('') }}>back</button></>
          ) : trail.map((place, i) => (
            <span key={place.folder}>
              {i > 0 && ' › '}
              {i < trail.length - 1
                ? <button className="link-button" onClick={() => setTrail(trail.slice(0, i + 1))}>{place.name}</button>
                : <b>{place.name}</b>}
            </span>
          ))}
        </div>

        <ul className="picker-list">
          {!current && <li className="muted small">Loading…</li>}
          {current?.error && <li className="error-text small">{current.error}</li>}
          {current?.data?.items.length === 0 && <li className="muted small">No folders, Docs or PDFs here.</li>}
          {current?.data?.items.map((item) => item.kind === 'folder' ? (
            <li key={item.id}>
              <button className="picker-folder" onClick={() => open({ folder: item.id, name: item.name })}>
                <span aria-hidden>📁</span> <span>{item.name}</span> <span className="muted" aria-hidden>›</span>
              </button>
            </li>
          ) : (
            <li key={item.id}>
              <label className="picker-file">
                <input type="checkbox" checked={selected?.has(item.id) ?? false} disabled={!selected || (!selected.has(item.id) && selected.size >= MAX_FILES)}
                  onChange={() => toggle(item.id, item.name)} />
                <span aria-hidden>{item.kind === 'pdf' ? '📄' : '📝'}</span>
                <span className="picker-name">{item.name}</span>
              </label>
            </li>
          ))}
        </ul>

        {selected && selected.size > 0 && (
          <details className="picker-chosen">
            <summary>{selected.size} file{selected.size === 1 ? '' : 's'} chosen{selected.size >= MAX_FILES && ' (the maximum)'}</summary>
            <ul>
              {[...selected.values()].map((f) => (
                <li key={f.id}>
                  <span className="picker-name">{f.name}{f.course && <span className="muted"> · {f.course}</span>}</span>
                  <button className="icon-button" onClick={() => toggle(f.id, f.name)} aria-label={`Remove ${f.name}`}>✕</button>
                </li>
              ))}
            </ul>
          </details>
        )}

        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button className="button ghost" onClick={onClose}>Cancel</button>
          <button className="button primary" onClick={save} disabled={!selected || saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </Dialog>
  )
}
