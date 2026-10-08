import { useState } from 'react'
import { localDate, nutritionApi, type FoodEntry, type NutritionDayData } from '../../api'
import type { WidgetProps } from '../types'
import { AddFoodDialog } from './AddFoodDialog'
import { EditFoodDialog } from './EditFoodDialog'
import { FoodLog, NutrientBars } from './NutritionParts'
import { PantryDialog, type PantryTab } from './PantryDialog'
import './nutrition.css'

export type NutritionData = NutritionDayData & { shopping_count: number }

export function NutritionWidget({ data, reload, actions }: WidgetProps<NutritionData>) {
  const [adding, setAdding] = useState(false)
  const [pantryTab, setPantryTab] = useState<PantryTab | null>(null) // the Pantry dialog, open on this tab
  const [removing, setRemoving] = useState<number | null>(null)
  const [editing, setEditing] = useState<FoodEntry | null>(null)

  const remove = async (id: number) => {
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
        <button className="link" onClick={() => actions.goTo('nutrition')}>History →</button>
        <button className="button primary small-button" onClick={() => setAdding(true)}>+ Add food</button>
      </div>
      <div className="nutrition-lists">
        <button className="button ghost small-button" onClick={() => setPantryTab('pantry')}>🥫 Pantry</button>
        <button className="button ghost small-button" onClick={() => setPantryTab('shopping')}
          aria-label={`Shopping list (${data.shopping_count} items)`}>
          🛒 Shopping list{data.shopping_count > 0 && <span className="nutrition-count">{data.shopping_count}</span>}
        </button>
      </div>

      <NutrientBars nutrients={data.nutrients} />

      <p className="food-group-title">Today's food ({data.entries.length})</p>
      {data.entries.length === 0
        ? <p className="muted small">Nothing logged yet today.</p>
        : <FoodLog entries={data.entries} removing={removing} onRemove={remove} onEdit={setEditing} />}

      {pantryTab && <PantryDialog initialTab={pantryTab} onClose={() => { setPantryTab(null); reload() }} />}
      {editing && (
        <EditFoodDialog entry={editing} onSaved={() => { setEditing(null); reload() }} onClose={() => setEditing(null)} />
      )}
      {adding && (
        <AddFoodDialog
          day={localDate()}
          personalKey={data.personal_food_key}
          onAdded={() => { setAdding(false); reload() }}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  )
}
