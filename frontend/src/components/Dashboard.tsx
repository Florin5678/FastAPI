import { useEffect, useMemo, useRef, useState } from 'react'
import ReactGridLayout, { useContainerWidth, type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { widgetsApi, type Widget } from '../api'
import type { DashboardActions } from '../widgets/types'
import { WidgetFrame } from './WidgetFrame'
import { AddWidgetDialog } from './AddWidgetDialog'
import { WidgetSettingsDialog } from './WidgetSettingsDialog'

const COLS = 12
const ROW_HEIGHT = 40
const MARGIN = 16
// Below this width widgets stack in one column (drag/resize is off on phones)
const STACK_BELOW = 720

type Props = {
  refreshKey: number
  actions: DashboardActions
  onNotice: (text: string, error?: boolean) => void
}

export function Dashboard({ refreshKey, actions, onNotice }: Props) {
  const [widgets, setWidgets] = useState<Widget[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [settingsFor, setSettingsFor] = useState<Widget | null>(null)
  const { width, containerRef, mounted } = useContainerWidth()
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    widgetsApi.list().then(setWidgets).catch((err) => setLoadError(err.message))
  }, [])

  const stacked = width < STACK_BELOW

  const layout: Layout = useMemo(
    () => (widgets ?? []).map((w) => ({
      i: w.id,
      ...w.layout,
      minW: w.min_size.w,
      minH: w.min_size.h,
    })),
    [widgets],
  )

  const onLayoutChange = (next: Layout) => {
    if (!editing || !widgets) return
    const changed = next.some((item) => {
      const w = widgets.find((x) => x.id === item.i)
      return w && (w.layout.x !== item.x || w.layout.y !== item.y || w.layout.w !== item.w || w.layout.h !== item.h)
    })
    if (!changed) return

    setWidgets(widgets.map((w) => {
      const item = next.find((x) => x.i === w.id)
      return item ? { ...w, layout: { x: item.x, y: item.y, w: item.w, h: item.h } } : w
    }))
    // Save once the user pauses, not on every pixel of a drag
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      widgetsApi.saveLayout(next.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })))
        .catch((err) => onNotice(`Couldn't save layout: ${err.message}`, true))
    }, 600)
  }

  const remove = async (widget: Widget) => {
    try {
      await widgetsApi.remove(widget.id)
      setWidgets((ws) => (ws ?? []).filter((w) => w.id !== widget.id))
    } catch (err) {
      onNotice(`Couldn't remove ${widget.name}: ${(err as Error).message}`, true)
    }
  }

  const added = (widget: Widget) => {
    setWidgets((ws) => [...(ws ?? []).filter((w) => w.id !== widget.id), widget])
    setAdding(false)
  }

  const saved = (widget: Widget) => {
    setWidgets((ws) => (ws ?? []).map((w) => (w.id === widget.id ? widget : w)))
    setSettingsFor(null)
  }

  const frame = (w: Widget) => (
    <WidgetFrame
      widget={w}
      refreshKey={refreshKey}
      editing={editing}
      actions={actions}
      onRemove={() => remove(w)}
      onSettings={() => setSettingsFor(w)}
    />
  )

  // Reading order for the stacked (phone) layout
  const ordered = [...(widgets ?? [])].sort((a, b) => a.layout.y - b.layout.y || a.layout.x - b.layout.x)

  return (
    <section className="dashboard">
      <div className="section-head">
        <h2>Home</h2>
        <div className="head-actions">
          {editing && <button className="button" onClick={() => setAdding(true)}>+ Add widget</button>}
          <button className={editing ? 'button primary' : 'button'} onClick={() => setEditing(!editing)}>
            {editing ? 'Done' : 'Edit'}
          </button>
        </div>
      </div>
      {editing && !stacked && (
        <p className="muted small edit-hint">Drag widgets by their title bar, resize from the bottom-right corner.</p>
      )}

      {loadError && <p className="error-text">Couldn't load your dashboard: {loadError}</p>}
      {widgets && widgets.length === 0 && (
        <div className="empty">
          Your dashboard is empty.{' '}
          <button className="link" onClick={() => { setEditing(true); setAdding(true) }}>Add a widget</button>
        </div>
      )}

      <div ref={containerRef}>
        {mounted && widgets && widgets.length > 0 && (stacked ? (
          <div className="widget-stack">
            {ordered.map((w) => <div key={w.id}>{frame(w)}</div>)}
          </div>
        ) : (
          <ReactGridLayout
            layout={layout}
            width={width}
            gridConfig={{ cols: COLS, rowHeight: ROW_HEIGHT, margin: [MARGIN, MARGIN], containerPadding: [0, 0] }}
            dragConfig={{ enabled: editing, handle: '.widget-drag', cancel: '.icon-button' }}
            resizeConfig={{ enabled: editing }}
            onLayoutChange={onLayoutChange}
          >
            {widgets.map((w) => <div key={w.id}>{frame(w)}</div>)}
          </ReactGridLayout>
        ))}
      </div>

      {adding && <AddWidgetDialog onAdded={added} onClose={() => setAdding(false)} />}
      {settingsFor && <WidgetSettingsDialog widget={settingsFor} onSaved={saved} onClose={() => setSettingsFor(null)} />}
    </section>
  )
}
