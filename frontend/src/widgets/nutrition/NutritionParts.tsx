// Pieces shared by the Nutrition widget and the full Nutrition page
import type { FoodEntry, NutrientRow } from '../../api'
import { barState, fmt } from './nutrients'

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

export function FoodLog({ entries, removing, onRemove, onEdit }: {
  entries: FoodEntry[]
  removing: number | null
  onRemove: (id: number) => void
  onEdit: (entry: FoodEntry) => void
}) {
  return (
    <ul className="item-list">
      {entries.map((e) => (
        <li key={e.id}>
          <button className="item-name food-edit" onClick={() => onEdit(e)} title="Edit">
            {e.name}
            <span className="muted small">
              {e.grams ? ` · ${fmt(e.grams)} g` : ''} · {fmt(e.nutrients.calories)} kcal · {fmt(e.nutrients.protein)} g protein
            </span>
          </button>
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
