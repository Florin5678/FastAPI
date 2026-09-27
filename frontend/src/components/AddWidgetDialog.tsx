import { useEffect, useState } from 'react'
import { widgetsApi, type CatalogEntry, type Widget } from '../api'
import { WIDGET_UI } from '../widgets'
import { Dialog } from './Dialog'

type Props = { onAdded: (widget: Widget) => void; onClose: () => void }

export function AddWidgetDialog({ onAdded, onClose }: Props) {
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    widgetsApi.catalog().then(setCatalog).catch((err) => setError(err.message))
  }, [])

  const add = async (id: string) => {
    setBusy(id)
    try {
      onAdded(await widgetsApi.add(id))
    } catch (err) {
      setError((err as Error).message)
      setBusy(null)
    }
  }

  // Only offer widgets this version of the frontend can render
  const available = (catalog ?? []).filter((w) => WIDGET_UI[w.id])

  return (
    <Dialog title="Add a widget" onClose={onClose}>
      {error && <p className="error-text">{error}</p>}
      {!catalog && !error && <p className="muted">Loading…</p>}
      <ul className="catalog">
        {available.map((w) => (
          <li key={w.id} className="catalog-item">
            <span className="catalog-icon" aria-hidden>{WIDGET_UI[w.id].icon}</span>
            <span className="catalog-text">
              <strong>{w.name}</strong>
              <span className="muted small">{w.description}</span>
            </span>
            {w.enabled ? (
              <span className="muted small">On dashboard</span>
            ) : (
              <button className="button primary" disabled={busy !== null} onClick={() => add(w.id)}>
                {busy === w.id ? 'Adding…' : 'Add'}
              </button>
            )}
          </li>
        ))}
      </ul>
      {catalog && available.every((w) => w.enabled) && (
        <p className="muted small">All available widgets are already on your dashboard. More are coming.</p>
      )}
    </Dialog>
  )
}
