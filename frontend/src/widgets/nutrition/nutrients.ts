// Nutrient formatting and progress-bar state, shared by the widget and the Nutrition page
import type { NutrientKey, NutrientRow, NutrientValues } from '../../api'

export function fmt(n: number): string {
  return n >= 100 ? String(Math.round(n)) : String(Math.round(n * 10) / 10)
}

// Goals fill yellow, turn green at 100%. Limits (sugar, sat. fat) are green while
// under and red once exceeded.
export function barState(n: NutrientRow): { percent: number; tone: 'progress' | 'done' | 'under-limit' | 'over'; hint: string } {
  const ratio = n.goal > 0 ? n.actual / n.goal : 0
  const percent = Math.min(ratio * 100, 100)
  if (n.kind === 'limit') {
    return ratio > 1
      ? { percent, tone: 'over', hint: `${fmt(n.actual - n.goal)} ${n.unit} over the limit` }
      : { percent, tone: 'under-limit', hint: `${fmt(n.goal - n.actual)} ${n.unit} left before the limit` }
  }
  return ratio >= 1
    ? { percent, tone: 'done', hint: 'Goal reached' }
    : { percent, tone: 'progress', hint: `${fmt(n.goal - n.actual)} ${n.unit} to go` }
}

// The nutrient fields in dialogs, in display order (two per row: calories/protein,
// carbs/sugar, fat/saturated fat, fiber/salt)
export const FIELDS: { key: NutrientKey; label: string; unit: string }[] = [
  { key: 'calories', label: 'Calories', unit: 'kcal' },
  { key: 'protein', label: 'Protein', unit: 'g' },
  { key: 'carbs', label: 'Carbs', unit: 'g' },
  { key: 'sugar', label: 'Sugar', unit: 'g' },
  { key: 'fat', label: 'Fat', unit: 'g' },
  { key: 'sat_fat', label: 'Saturated fat', unit: 'g' },
  { key: 'fiber', label: 'Fiber', unit: 'g' },
  { key: 'salt', label: 'Salt', unit: 'g' },
]

// Values per 100 g -> values for `grams` (one decimal)
export function scale(per100: NutrientValues, grams: number): NutrientValues {
  return Object.fromEntries(
    FIELDS.map(({ key }) => [key, Math.round(((per100[key] ?? 0) * grams) / 10) / 10]),
  ) as NutrientValues
}

// Values for `grams` -> values per 100 g (two decimals)
export function per100g(values: NutrientValues, grams: number): NutrientValues {
  return Object.fromEntries(
    FIELDS.map(({ key }) => [key, Math.round(((values[key] ?? 0) * 10000) / grams) / 100]),
  ) as NutrientValues
}

// Form strings -> numbers (empty = 0)
export function toValues(form: Record<string, string>): NutrientValues {
  return Object.fromEntries(FIELDS.map(({ key }) => [key, Number(String(form[key] ?? '').replace(',', '.')) || 0])) as NutrientValues
}

export function summary(values: NutrientValues): string {
  return FIELDS.map(({ key, label, unit }) => `${label} ${fmt(values[key] ?? 0)} ${unit}`).join(' · ')
}
