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
  id: number
  day: string
  name: string
  grams: number | null
  source: 'manual' | 'usda'
  nutrients: NutrientValues
  added_at: string | null
}

export type NutrientRow = {
  key: NutrientKey
  label: string
  unit: string
  kind: 'goal' | 'limit'
  goal: number
  actual: number
}

export type NutritionDayData = {
  day: string
  nutrients: NutrientRow[]
  entries: FoodEntry[]
  personal_food_key: boolean
}

export type NutritionHistory = {
  days: { day: string; entries: number; nutrients: NutrientRow[] }[]
  first_logged_day: string | null
}

// YYYY-MM-DD in the browser's timezone (optionally shifted by whole days)
export function localDate(d: Date = new Date(), shiftDays = 0): string {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate() + shiftDays)
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
}

export function shiftDay(day: string, days: number): string {
  const [y, m, d] = day.split('-').map(Number)
  return localDate(new Date(y, m - 1, d), days)
}

export const nutritionApi = {
  searchFoods: (q: string) => request<FoodResult[]>(`/widgets/nutrition/foods?q=${encodeURIComponent(q)}`),
  addEntry: (day: string, entry: { name: string; grams?: number; nutrients: Partial<NutrientValues>; source: 'manual' | 'usda'; fdc_id?: number }) =>
    request<FoodEntry>('/widgets/nutrition/entries', { method: 'POST', ...json({ ...entry, day }) }),
  deleteEntry: (id: number) => request<unknown>(`/widgets/nutrition/entries/${id}`, { method: 'DELETE' }),
  getDay: (day: string) => request<NutritionDayData>(`/widgets/nutrition/days/${day}`),
  history: (end: string, days: number) => request<NutritionHistory>(`/widgets/nutrition/history?end=${end}&days=${days}`),
}

// ---- Notes & reminders widget ----

export type Reminder = { id: string; text: string; due: string | null; done: boolean; created_at: string; done_at: string | null }
export type Note = { id: string; text: string; pinned: boolean; created_at: string; updated_at: string }

export const notesApi = {
  addReminder: (text: string, due: string | null) =>
    request<Reminder>('/widgets/notes/reminders', { method: 'POST', ...json({ text, due }) }),
  updateReminder: (id: string, changes: Partial<Pick<Reminder, 'text' | 'due' | 'done'>>) =>
    request<Reminder>(`/widgets/notes/reminders/${id}`, { method: 'PATCH', ...json(changes) }),
  deleteReminder: (id: string) => request<unknown>(`/widgets/notes/reminders/${id}`, { method: 'DELETE' }),
  addNote: (text: string) => request<Note>('/widgets/notes/notes', { method: 'POST', ...json({ text }) }),
  updateNote: (id: string, changes: Partial<Pick<Note, 'text' | 'pinned'>>) =>
    request<Note>(`/widgets/notes/notes/${id}`, { method: 'PATCH', ...json(changes) }),
  deleteNote: (id: string) => request<unknown>(`/widgets/notes/notes/${id}`, { method: 'DELETE' }),
}

// ---- Journal widget ----

export type JournalPrompt = { id: number; text: string; idea: string; source: string }

export type JournalEntry = {
  id: number
  day: string
  prompt_id: number | null
  prompt_text: string | null
  mood: string | null
  body: string
  created_at: string | null
  updated_at: string | null
}

export const journalApi = {
  prompt: (exclude?: number) => request<JournalPrompt>(`/widgets/journal/prompt${exclude ? `?exclude=${exclude}` : ''}`),
  add: (entry: { day: string; body: string; prompt_id: number | null; mood: string | null }) =>
    request<JournalEntry>('/widgets/journal/entries', { method: 'POST', ...json(entry) }),
  list: (beforeId?: number, limit = 20) =>
    request<{ entries: JournalEntry[]; has_more: boolean; total: number }>(
      `/widgets/journal/entries?limit=${limit}${beforeId ? `&before_id=${beforeId}` : ''}`,
    ),
  update: (id: number, changes: { body?: string; mood?: string | null }) =>
    request<JournalEntry>(`/widgets/journal/entries/${id}`, { method: 'PATCH', ...json(changes) }),
  remove: (id: number) => request<unknown>(`/widgets/journal/entries/${id}`, { method: 'DELETE' }),
  // History (locked: needs a fresh Google sign-in, see /auth/google/login?purpose=journal)
  access: () => request<{ unlocked: boolean; expires_at: string | null }>('/widgets/journal/access'),
  lock: () => request<unknown>('/widgets/journal/lock', { method: 'POST' }),
  day: (day: string) => request<{ day: string; entries: JournalEntry[] }>(`/widgets/journal/days/${day}`),
  history: (end: string, days: number) => request<JournalHistory>(`/widgets/journal/history?end=${end}&days=${days}`),
  moods: (end: string, months: number) => request<{ months: MoodMonth[] }>(`/widgets/journal/moods?end=${end}&months=${months}`),
}

export type JournalHistory = {
  days: { day: string; entries: number; moods: string[]; words: number; preview: string }[]
  first_entry_day: string | null
  streak: number
  total: number
}

export type MoodMonth = {
  month: string // YYYY-MM
  entries: number
  days_logged: number
  moods: { emoji: string; count: number }[]
  days: Record<string, string[]> // YYYY-MM-DD -> moods that day ([] = entries without a mood)
}

export const isJournalLocked = (err: unknown) => err instanceof ApiError && err.status === 403 && err.message === 'journal_locked'
