// Journal widget: prompts, entries, locked history
import { ApiError, json, request } from './client'

export type JournalPrompt = { id: number; text: string }

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
