// Notes & reminders widget
import { json, request } from './client'

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
