// Pieces shared by the Nutrition widget and the full Nutrition page
import type { FoodEntry, NutrientRow } from '../api'

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

export function NutrientBars({ nutrients }: { nutrients: NutrientRow[] }) {
  return (
    <ul className="nutrient-list">
      {nutrients.map((n) => {
        const state = barState(n)
        return (
          <li key={n.key} className="nutrient" title={state.hint}>
            <span className="nutrient-label">
              {n.label}
              {n.kind === 'limit' && <span className="nutrient-max">max</span>}
            </span>
            <span className="bar" role="progressbar" aria-label={n.label} aria-valuemin={0} aria-valuemax={n.goal} aria-valuenow={n.actual}>
              <span className={`bar-fill ${state.tone}`} style={{ width: `${state.percent}%` }} />
            </span>
            <span className={state.tone === 'over' ? 'nutrient-value over' : 'nutrient-value'}>
              {fmt(n.actual)} / {fmt(n.goal)} {n.unit}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

export function FoodLog({ entries, removing, onRemove }: { entries: FoodEntry[]; removing: number | null; onRemove: (id: number) => void }) {
  return (
    <ul className="food-log">
      {entries.map((e) => (
        <li key={e.id}>
          <span className="food-name">
            {e.name}
            <span className="muted small">
              {e.grams ? ` · ${fmt(e.grams)} g` : ''} · {fmt(e.nutrients.calories)} kcal · {fmt(e.nutrients.protein)} g protein
            </span>
          </span>
          <button
            className="icon-button"
            onClick={() => onRemove(e.id)}
            disabled={removing === e.id}
            aria-label={`Remove ${e.name}`}
            title="Remove"
          >✕</button>
        </li>
      ))}
    </ul>
  )
}
