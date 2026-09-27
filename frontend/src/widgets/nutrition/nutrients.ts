// Nutrient formatting and progress-bar state, shared by the widget and the Nutrition page
import type { NutrientRow } from '../../api'

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
