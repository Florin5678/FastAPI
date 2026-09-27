import { useState } from 'react'
import { nutritionApi, type FoodEntry, type NutrientKey } from '../api'
import type { WidgetProps } from './types'
import { AddFoodDialog } from './AddFoodDialog'

type Nutrient = {
  key: NutrientKey
  label: string
  unit: string
  kind: 'goal' | 'limit'
  goal: number
  actual: number
}

export type NutritionData = {
  day: string
  nutrients: Nutrient[]
  entries: FoodEntry[]
  personal_food_key: boolean
}

function fmt(n: number): string {
  return n >= 100 ? String(Math.round(n)) : String(Math.round(n * 10) / 10)
}

function barState(n: Nutrient): { percent: number; tone: string; hint: string } {
  const ratio = n.goal > 0 ? n.actual / n.goal : 0
  const percent = Math.min(ratio * 100, 100)
  if (n.kind === 'limit') {
    // Limits (sugar, saturated fat): fine while under, red once exceeded
    return ratio > 1
      ? { percent, tone: 'over', hint: `${fmt(n.actual - n.goal)} ${n.unit} over the limit` }
      : { percent, tone: 'under-limit', hint: `${fmt(n.goal - n.actual)} ${n.unit} left before the limit` }
  }
  return ratio >= 1
    ? { percent, tone: 'done', hint: 'Goal reached' }
    : { percent, tone: 'progress', hint: `${fmt(n.goal - n.actual)} ${n.unit} to go` }
}

export function NutritionWidget({ data, reload }: WidgetProps<NutritionData>) {
  const [adding, setAdding] = useState(false)
  const [showLog, setShowLog] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)

  const remove = async (id: string) => {
    setRemoving(id)
    try {
      await nutritionApi.deleteEntry(id)
      reload()
    } finally {
      setRemoving(null)
    }
  }

  return (
    <div className="nutrition-widget">
      <div className="nutrition-head">
        <span className="muted small">Today</span>
        <button className="button primary small-button" onClick={() => setAdding(true)}>+ Add food</button>
      </div>

      <ul className="nutrient-list">
        {data.nutrients.map((n) => {
          const state = barState(n)
          return (
            <li key={n.key} className="nutrient" title={state.hint}>
              <span className="nutrient-label">
                {n.label}
                {n.kind === 'limit' && <span className="nutrient-max">max</span>}
              </span>
              <span
                className="bar"
                role="progressbar"
                aria-label={n.label}
                aria-valuemin={0}
                aria-valuemax={n.goal}
                aria-valuenow={n.actual}
              >
                <span className={`bar-fill ${state.tone}`} style={{ width: `${state.percent}%` }} />
              </span>
              <span className={state.tone === 'over' ? 'nutrient-value over' : 'nutrient-value'}>
                {fmt(n.actual)} / {fmt(n.goal)} {n.unit}
              </span>
            </li>
          )
        })}
      </ul>

      <button className="link" onClick={() => setShowLog(!showLog)}>
        {showLog ? 'Hide' : 'Show'} today's food ({data.entries.length})
      </button>
      {showLog && (
        data.entries.length === 0 ? (
          <p className="muted small">Nothing logged yet today.</p>
        ) : (
          <ul className="food-log">
            {data.entries.map((e) => (
              <li key={e.id}>
                <span className="food-name">
                  {e.name}
                  <span className="muted small">
                    {e.grams ? ` · ${fmt(e.grams)} g` : ''} · {fmt(e.nutrients.calories)} kcal · {fmt(e.nutrients.protein)} g protein
                  </span>
                </span>
                <button
                  className="icon-button"
                  onClick={() => remove(e.id)}
                  disabled={removing === e.id}
                  aria-label={`Remove ${e.name}`}
                  title="Remove"
                >✕</button>
              </li>
            ))}
          </ul>
        )
      )}

      {adding && (
        <AddFoodDialog
          personalKey={data.personal_food_key}
          onAdded={() => { setAdding(false); setShowLog(true); reload() }}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  )
}
