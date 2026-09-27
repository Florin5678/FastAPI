import { useCallback, useEffect, useState } from 'react'
import { widgetsApi, type Widget, type WidgetEnvelope } from '../api'
import { WIDGET_UI } from '../widgets'
import type { DashboardActions } from '../widgets/types'

type Props = {
  widget: Widget
  refreshKey: number
  editing: boolean
  actions: DashboardActions
  onRemove: () => void
  onSettings: () => void
  onSettingsSaved: (widget: Widget) => void
  onError: (message: string) => void
}

// Shared chrome for every widget: header, loading/error states, auto-refresh.
export function WidgetFrame({ widget, refreshKey, editing, actions, onRemove, onSettings, onSettingsSaved, onError }: Props) {
  const ui = WIDGET_UI[widget.id]
  const [envelope, setEnvelope] = useState<WidgetEnvelope<unknown> | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    widgetsApi.data(widget.id)
      .then((result) => {
        setEnvelope(result)
        setRequestError(null)
      })
      .catch((err) => setRequestError(err.message))
      .finally(() => setLoading(false))
  }, [widget.id])

  // Reload on mount, after a sync, and when settings change
  const settingsKey = JSON.stringify(widget.settings)
  useEffect(load, [load, refreshKey, settingsKey])

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, widget.refresh_seconds * 1000)
    return () => clearInterval(timer)
  }, [load, widget.refresh_seconds])

  const updateSettings = useCallback(async (changes: Record<string, unknown>) => {
    try {
      // Saving changes widget.settings, which triggers the reload effect above
      onSettingsSaved(await widgetsApi.saveSettings(widget.id, { ...widget.settings, ...changes }))
    } catch (err) {
      onError(`Couldn't update ${widget.name}: ${(err as Error).message}`)
    }
  }, [widget.id, widget.name, widget.settings, onSettingsSaved, onError])

  const error = requestError ?? (envelope?.status === 'error' ? envelope.error : null)
  const Body = ui?.component

  return (
    <section className={editing ? 'widget editing' : 'widget'} aria-label={widget.name}>
      <header className={editing ? 'widget-head widget-drag' : 'widget-head'}>
        <span className="widget-title">
          {editing && <span className="grip" aria-hidden>⠿</span>}
          <span aria-hidden>{ui?.icon ?? '▫️'}</span> {widget.name}
        </span>
        <span className="widget-tools">
          {editing ? (
            <>
              {widget.config_fields.length > 0 && (
                <button className="icon-button" onClick={onSettings} aria-label={`${widget.name} settings`} title="Settings">⚙</button>
              )}
              <button className="icon-button" onClick={onRemove} aria-label={`Remove ${widget.name}`} title="Remove">✕</button>
            </>
          ) : (
            <button
              className={loading ? 'icon-button spinning' : 'icon-button'}
              onClick={load}
              aria-label={`Refresh ${widget.name}`}
              title={envelope ? `Updated ${new Date(envelope.last_updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Refresh'}
            >↻</button>
          )}
        </span>
      </header>

      <div className="widget-body">
        {!Body && <p className="error-text small">This widget isn't available in this version of the app.</p>}
        {Body && error && (
          <div className="widget-error">
            <p className="error-text small">{error}</p>
            <button className="button" onClick={load}>Try again</button>
          </div>
        )}
        {Body && !error && !envelope && <p className="muted small">Loading…</p>}
        {Body && !error && envelope?.status === 'ok' && (
          <Body data={envelope.data} settings={widget.settings} actions={actions} updateSettings={updateSettings} reload={load} />
        )}
      </div>
    </section>
  )
}
