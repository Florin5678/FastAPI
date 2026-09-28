import { useState } from 'react'
import { localDate, nutritionApi, type FoodEntry, type NutritionDayData } from '../../api'
import type { WidgetProps } from '../types'
import { AddFoodDialog } from './AddFoodDialog'
import { EditFoodDialog } from './EditFoodDialog'
import { FoodLog, NutrientBars } from './NutritionParts'
import './nutrition.css'

export type NutritionData = NutritionDayData

export function NutritionWidget({ data, reload, actions }: WidgetProps<NutritionData>) {
  const [adding, setAdding] = useState(false)
  const [showLog, setShowLog] = useState(false)
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
        <button className="link" onClick={() => actions.goTo('nutrition')}>Today · history →</button>
        <button className="button primary small-button" onClick={() => setAdding(true)}>+ Add food</button>
      </div>

      <NutrientBars nutrients={data.nutrients} />

      <button className="link" onClick={() => setShowLog(!showLog)}>
        {showLog ? 'Hide' : 'Show'} today's food ({data.entries.length})
      </button>
      {showLog && (
        data.entries.length === 0
          ? <p className="muted small">Nothing logged yet today.</p>
          : <FoodLog entries={data.entries} removing={removing} onRemove={remove} onEdit={setEditing} />
      )}

      {editing && (
        <EditFoodDialog entry={editing} onSaved={() => { setEditing(null); reload() }} onClose={() => setEditing(null)} />
      )}
      {adding && (
        <AddFoodDialog
          day={localDate()}
          personalKey={data.personal_food_key}
          onAdded={() => { setAdding(false); setShowLog(true); reload() }}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  )
}
