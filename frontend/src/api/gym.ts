// Gym widget: log / delete workouts
import { json, request } from './client'

export type Workout = { id: number; day: string; kind: string; minutes: number; note: string | null }

export type GymMonth = {
  month: string // YYYY-MM
  days: Record<string, Workout[]> // YYYY-MM-DD -> workouts that day
  // Every Monday–Sunday week touching the month, counted in full; kinds = sessions per type
  weeks: { week_start: string; week: number; sessions: number; minutes: number; kinds: Record<string, number> }[]
  goal_workouts: number
  goal_minutes: number
  totals: { kind: string; sessions: number; minutes: number }[]
  sessions: number
  minutes: number
  days_trained: number
  first_month: string | null
}

export const gymApi = {
  month: (month: string) => request<GymMonth>(`/widgets/gym/month?month=${month}`),
  log: (workout: { day: string; kind: string; minutes: number; note?: string }) =>
    request<Workout>('/widgets/gym/workouts', { method: 'POST', ...json(workout) }),
  remove: (id: number) => request<unknown>(`/widgets/gym/workouts/${id}`, { method: 'DELETE' }),
}
