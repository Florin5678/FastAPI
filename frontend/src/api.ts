// Thin wrapper around the FastAPI backend (same origin, session cookie auth)

export type Me = {
  email: string
  name: string | null
  summaries_enabled: boolean
}

export type EmailItem = {
  id: number
  gmail_id: string
  subject: string | null
  sender: string | null
  snippet: string | null
  timestamp: string | null
  category: string | null
  summary: string | null
  full_body?: string | null
}

export type EmailList = { total: number; emails: EmailItem[] }

export type Digest = {
  date: string
  total: number
  categories: Record<string, EmailItem[]>
}

export type SyncResult = { synced: number; checked: number }
export type SummaryResult = { summarized: number; failed?: number; remaining?: number; skipped?: string }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // not JSON - keep the status text
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

function localMidnightIso(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString() // UTC instant of the viewer's local midnight
}

export const api = {
  me: () => request<Me>('/api/me'),
  logout: () => request<unknown>('/auth/google/logout', { method: 'POST' }),
  emails: (params: { category?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams()
    if (params.category) q.set('category', params.category)
    q.set('limit', String(params.limit ?? 30))
    q.set('offset', String(params.offset ?? 0))
    return request<EmailList>(`/emails?${q}`)
  },
  email: (id: number) => request<EmailItem>(`/emails/${id}`),
  digest: () => request<Digest>(`/digest/today?since=${encodeURIComponent(localMidnightIso())}`),
  sync: () => request<SyncResult>('/gmail/sync/gmail?max_results=20', { method: 'POST' }),
  summarize: () => request<SummaryResult>('/summaries/run?limit=10', { method: 'POST' }),
}

// ---- Dashboard widgets ----

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

const json = (body: unknown): RequestInit => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

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

// ---- Nutrition widget ----

export type NutrientKey = 'calories' | 'protein' | 'carbs' | 'fat' | 'fiber' | 'sugar' | 'sat_fat'
export type NutrientValues = Record<NutrientKey, number>

export type FoodResult = { fdc_id: number; name: string; data_type: string; per_100g: NutrientValues }

export type FoodEntry = {
  id: string
  name: string
  grams: number | null
  source: 'manual' | 'usda'
  nutrients: NutrientValues
  added_at: string
}

export function localDate(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export const nutritionApi = {
  searchFoods: (q: string) => request<FoodResult[]>(`/widgets/nutrition/foods?q=${encodeURIComponent(q)}`),
  addEntry: (entry: { name: string; grams?: number; nutrients: Partial<NutrientValues>; source: 'manual' | 'usda'; fdc_id?: number }) =>
    request<FoodEntry>('/widgets/nutrition/entries', { method: 'POST', ...json({ ...entry, day: localDate() }) }),
  deleteEntry: (id: string) =>
    request<unknown>(`/widgets/nutrition/entries/${id}?day=${localDate()}`, { method: 'DELETE' }),
}
