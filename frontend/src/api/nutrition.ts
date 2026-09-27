// Nutrition widget: food log, day view, history, USDA food search
import { json, request } from './client'

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

export const nutritionApi = {
  searchFoods: (q: string) => request<FoodResult[]>(`/widgets/nutrition/foods?q=${encodeURIComponent(q)}`),
  addEntry: (day: string, entry: { name: string; grams?: number; nutrients: Partial<NutrientValues>; source: 'manual' | 'usda'; fdc_id?: number }) =>
    request<FoodEntry>('/widgets/nutrition/entries', { method: 'POST', ...json({ ...entry, day }) }),
  deleteEntry: (id: number) => request<unknown>(`/widgets/nutrition/entries/${id}`, { method: 'DELETE' }),
  getDay: (day: string) => request<NutritionDayData>(`/widgets/nutrition/days/${day}`),
  history: (end: string, days: number) => request<NutritionHistory>(`/widgets/nutrition/history?end=${end}&days=${days}`),
}
