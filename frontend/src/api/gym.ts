// Gym widget: log / delete workouts
import { json, request } from './client'

export type Workout = { id: number; day: string; kind: string; minutes: number; note: string | null }

export type GymMonth = {
  month: string // YYYY-MM
  days: Record<string, Workout[]> // YYYY-MM-DD -> workouts that day
  // Every Monday–Sunday week touching the month, counted in full; kinds = sessions per type
  weeks: { week_start: string; week: number; active_days: number; sessions: number; minutes: number; kinds: Record<string, number> }[]
  goal_active_days: number // days with at least one workout, per week
  goal_minutes: number
  totals: { kind: string; sessions: number; minutes: number }[]
  sessions: number
  minutes: number
  days_trained: number
  first_month: string | null
}

export type GymStatsLevel = 'week' | 'month' | 'year'

// Minutes and sessions per workout type for one week / month / year
export type GymStats = {
  level: GymStatsLevel
  label: string
  start: string
  end: string
  totals: { kind: string; sessions: number; minutes: number }[]
  active_days: number
  kinds: string[] // routine order: fixes each type's colour
}

export const gymApi = {
  stats: (level: GymStatsLevel, anchor: string) => request<GymStats>(`/widgets/gym/stats?level=${level}&anchor=${anchor}`),
  month: (month: string) => request<GymMonth>(`/widgets/gym/month?month=${month}`),
  log: (workout: { day: string; kind: string; minutes: number; note?: string }) =>
    request<Workout>('/widgets/gym/workouts', { method: 'POST', ...json(workout) }),
  remove: (id: number) => request<unknown>(`/widgets/gym/workouts/${id}`, { method: 'DELETE' }),
}
