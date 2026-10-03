// Weight widget: body weight entries (one per day)
import { json, request } from './client'

export type WeightEntry = { day: string; kg: number }

export const weightApi = {
  log: (day: string, kg: number) => request<WeightEntry>('/widgets/weight/entries', { method: 'POST', ...json({ day, kg }) }),
  remove: (day: string) => request<unknown>(`/widgets/weight/entries/${day}`, { method: 'DELETE' }),
}
