// Dashboard widgets: registry, per-user layout/settings, data envelope
import { json, request } from './client'
import { localMidnightIso } from '../lib/dates'

export type ConfigField = {
  key: string
  label: string
  type: 'number' | 'boolean' | 'select' | 'text'
  default: unknown
  min?: number
  max?: number
  options?: string[]
}

export type WidgetManifest = {
  id: string
  name: string
  description: string
  default_size: { w: number; h: number }
  min_size: { w: number; h: number }
  refresh_seconds: number
  config_fields: ConfigField[]
}

export type GridPosition = { x: number; y: number; w: number; h: number }

export type Widget = WidgetManifest & {
  settings: Record<string, unknown>
  layout: GridPosition
}

export type CatalogEntry = WidgetManifest & { enabled: boolean }

export type WidgetEnvelope<T> =
  | { status: 'ok'; data: T; last_updated: string }
  | { status: 'error'; error: string; data: null; last_updated: string }

function widgetContext(): string {
  const q = new URLSearchParams({ since: localMidnightIso() })
  try {
    q.set('tz', Intl.DateTimeFormat().resolvedOptions().timeZone)
  } catch {
    // older browsers: the server falls back to `since` alone
  }
  return q.toString()
}

export const widgetsApi = {
  list: () => request<Widget[]>('/widgets'),
  catalog: () => request<CatalogEntry[]>('/widgets/catalog'),
  add: (id: string) => request<Widget>(`/widgets/${id}`, { method: 'POST' }),
  remove: (id: string) => request<unknown>(`/widgets/${id}`, { method: 'DELETE' }),
  saveSettings: (id: string, settings: Record<string, unknown>) =>
    request<Widget>(`/widgets/${id}/settings`, { method: 'PATCH', ...json({ settings }) }),
  saveLayout: (items: ({ i: string } & GridPosition)[]) =>
    request<unknown>('/widgets/layout', { method: 'PUT', ...json(items) }),
  data: <T,>(id: string) => request<WidgetEnvelope<T>>(`/widgets/${id}/data?${widgetContext()}`),
}
