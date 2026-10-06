import { useState, type FormEvent } from 'react'
import { nutritionApi, type SavedFood } from '../../api'
import { Dialog } from '../../components/Dialog'
import { FIELDS, toValues } from './nutrients'

// Change a food in "My foods": its name, usual amount and values per 100 g (food already
// logged keeps its values)
export function EditSavedFoodDialog({ food, onSaved, onClose }: { food: SavedFood; onSaved: (food: SavedFood) => void; onClose: () => void }) {
  const [name, setName] = useState(food.name)
  const [grams, setGrams] = useState(food.grams ? String(food.grams) : '')
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(FIELDS.map(({ key }) => [key, String(food.per_100g[key] ?? 0)])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      const amount = Number(grams.replace(',', '.'))
      onSaved(await nutritionApi.updateSavedFood(food.id, { name: name.trim(), grams: amount > 0 ? amount : null, per_100g: toValues(values) }))
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <Dialog title="Edit saved food" onClose={onClose}>
      <form className="settings-form food-form" onSubmit={save}>
        <label className="field">
          <span>Name</span>
          <input type="text" value={name} maxLength={200} autoFocus onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>Usual amount (grams) <span className="muted">(optional)</span></span>
          <input type="number" min={1} max={5000} step="any" value={grams} onChange={(e) => setGrams(e.target.value)} />
        </label>
        <p className="food-group-title">Per 100 g</p>
        <div className="manual-grid">
          {FIELDS.map(({ key, label, unit }) => (
            <label key={key} className="field">
              <span>{label} ({unit})</span>
              <input type="number" min={0} step="any" aria-label={`${label} per 100 g (${unit})`} value={values[key] ?? ''}
                onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))} />
            </label>
          ))}
        </div>
        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy || !name.trim()}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}
