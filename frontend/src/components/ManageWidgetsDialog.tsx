import { useEffect, useState } from 'react'
import { widgetsApi, type CatalogEntry, type Widget } from '../api'
import { WIDGET_UI } from '../widgets'
import { Dialog } from './Dialog'

type Props = {
  onAdded: (widget: Widget) => void
  onRemoved: (id: string) => void
  onClose: () => void
}

// Every available widget with an Add or Remove button; stays open so several can be toggled
export function ManageWidgetsDialog({ onAdded, onRemoved, onClose }: Props) {
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    widgetsApi.catalog().then(setCatalog).catch((err) => setError(err.message))
  }, [])

  const toggle = async (entry: CatalogEntry) => {
    setBusy(entry.id)
    setError(null)
    try {
      if (entry.enabled) {
        await widgetsApi.remove(entry.id)
        onRemoved(entry.id)
      } else {
        onAdded(await widgetsApi.add(entry.id))
      }
      setCatalog((c) => (c ?? []).map((w) => (w.id === entry.id ? { ...w, enabled: !entry.enabled } : w)))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  // Only offer widgets this version of the frontend can render
  const available = (catalog ?? []).filter((w) => WIDGET_UI[w.id])

  return (
    <Dialog title="Add or remove widgets" onClose={onClose}>
      {error && <p className="error-text">{error}</p>}
      {!catalog && !error && <p className="muted">Loading…</p>}
      <ul className="catalog">
        {available.map((w) => (
          <li key={w.id} className={w.enabled ? 'catalog-item on' : 'catalog-item'}>
            <span className="catalog-icon" aria-hidden>{WIDGET_UI[w.id].icon}</span>
            <span className="catalog-text">
              <strong>{w.name}</strong>
              <span className="muted small">{w.description}</span>
            </span>
            <button
              className={w.enabled ? 'button ghost' : 'button primary'}
              disabled={busy !== null}
              onClick={() => toggle(w)}
              aria-label={`${w.enabled ? 'Remove' : 'Add'} ${w.name}`}
            >
              {busy === w.id ? (w.enabled ? 'Removing…' : 'Adding…') : w.enabled ? 'Remove' : 'Add'}
            </button>
          </li>
        ))}
      </ul>
      <div className="dialog-actions">
        <button className="button primary" onClick={onClose}>Done</button>
      </div>
    </Dialog>
  )
}
