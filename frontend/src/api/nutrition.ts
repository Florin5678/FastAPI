// Nutrition widget: food log, day view, history, food search (USDA + Open Food Facts)
import { json, request } from './client'

export type NutrientKey = 'calories' | 'protein' | 'carbs' | 'fat' | 'fiber' | 'sugar' | 'sat_fat'
export type NutrientValues = Record<NutrientKey, number>

// A search result: USDA (generic foods) or Open Food Facts ('off', branded products)
export type FoodResult = {
  source: 'usda' | 'off'
  id: string
  fdc_id: number | null
  name: string
  brand: string | null
  data_type: string | null // USDA data type, or the pack size for Open Food Facts
  per_100g: NutrientValues
}

export type FoodEntry = {
  id: number
  day: string
  name: string
  grams: number | null
  source: 'manual' | 'usda' | 'off'
  nutrients: NutrientValues
  added_at: string | null
}

// A food from "My foods": values per 100 g, and the amount used last time
export type SavedFood = { id: string; name: string; per_100g: NutrientValues; grams: number | null; used_at: string; uses: number }

export type NewEntry = {
  name: string
  grams?: number
  nutrients: Partial<NutrientValues> // for the amount eaten
  source: 'manual' | 'usda' | 'off'
  fdc_id?: number
  per_100g?: NutrientValues // with save: store the food in "My foods"
  save?: boolean
  saved_food_id?: string
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
  addEntry: (day: string, entry: NewEntry) =>
    request<FoodEntry>('/widgets/nutrition/entries', { method: 'POST', ...json({ ...entry, day }) }),
  updateEntry: (id: number, changes: { day?: string; name?: string; grams?: number; nutrients?: NutrientValues }) =>
    request<FoodEntry>(`/widgets/nutrition/entries/${id}`, { method: 'PATCH', ...json(changes) }),
  savedFoods: () => request<{ foods: SavedFood[] }>('/widgets/nutrition/saved-foods'),
  deleteSavedFood: (id: string) => request<unknown>(`/widgets/nutrition/saved-foods/${id}`, { method: 'DELETE' }),
  deleteEntry: (id: number) => request<unknown>(`/widgets/nutrition/entries/${id}`, { method: 'DELETE' }),
  getDay: (day: string) => request<NutritionDayData>(`/widgets/nutrition/days/${day}`),
  history: (end: string, days: number) => request<NutritionHistory>(`/widgets/nutrition/history?end=${end}&days=${days}`),
}
