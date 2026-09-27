// Gym widget: log / delete workouts
import { json, request } from './client'

export type Workout = { id: number; day: string; kind: string; minutes: number; note: string | null }

export const gymApi = {
  log: (workout: { day: string; kind: string; minutes: number; note?: string }) =>
    request<Workout>('/widgets/gym/workouts', { method: 'POST', ...json(workout) }),
  remove: (id: number) => request<unknown>(`/widgets/gym/workouts/${id}`, { method: 'DELETE' }),
}
