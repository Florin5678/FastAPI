// Reminders widget (its id is still "notes")
import { json, request } from './client'

export type Repeat = 'daily' | 'weekly' | 'monthly'

export type Reminder = {
  id: string
  text: string
  due: string | null
  repeat: Repeat | null // a repeating reminder moves to its next time when ticked
  repeat_day: number | null // day of the month a monthly one keeps
  done: boolean
  created_at: string
  done_at: string | null
}

// The browser's timezone: the server steps repeating reminders in local time
const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone

export const notesApi = {
  addReminder: (text: string, due: string | null, repeat: Repeat | null) =>
    request<Reminder>('/widgets/notes/reminders', { method: 'POST', ...json({ text, due, repeat, tz: tz() }) }),
  updateReminder: (id: string, changes: Partial<Pick<Reminder, 'text' | 'due' | 'done' | 'repeat'>>) =>
    request<Reminder>(`/widgets/notes/reminders/${id}`, { method: 'PATCH', ...json({ ...changes, tz: tz() }) }),
  deleteReminder: (id: string) => request<unknown>(`/widgets/notes/reminders/${id}`, { method: 'DELETE' }),
}
