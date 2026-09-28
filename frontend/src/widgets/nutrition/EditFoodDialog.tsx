import { useState, type FormEvent } from 'react'
import { localDate, nutritionApi, type FoodEntry } from '../../api'
import { Dialog } from '../../components/Dialog'
import { FIELDS, fmt, per100g, scale, summary, toValues } from './nutrients'

type Props = { entry: FoodEntry; onSaved: () => void; onClose: () => void }

// Edit a logged food. Entries with an amount are edited per 100 g + amount eaten
// (like adding one); older entries without an amount are edited as totals.
export function EditFoodDialog({ entry, onSaved, onClose }: Props) {
  const hasGrams = entry.grams !== null && entry.grams > 0
  const start = hasGrams ? per100g(entry.nutrients, entry.grams as number) : entry.nutrients
  const [name, setName] = useState(entry.name)
  const [day, setDay] = useState(entry.day)
  const [grams, setGrams] = useState(hasGrams ? String(entry.grams) : '')
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(FIELDS.map(({ key }) => [key, String(start[key])])),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const parsed = toValues(values)
  const gramsNumber = Number(grams.replace(',', '.'))
  const totals = hasGrams ? (gramsNumber > 0 ? scale(parsed, gramsNumber) : null) : parsed
  const valid = name.trim() !== '' && totals !== null && day <= localDate()

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!valid || !totals) return
    setSaving(true)
    setError(null)
    try {
      await nutritionApi.updateEntry(entry.id, {
        name: name.trim(), day, nutrients: totals, ...(hasGrams ? { grams: gramsNumber } : {}),
      })
      onSaved()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!confirm(`Remove ${entry.name}?`)) return
    setSaving(true)
    try {
      await nutritionApi.deleteEntry(entry.id)
      onSaved()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <Dialog title="Edit food" onClose={onClose}>
      <form className="settings-form food-form" onSubmit={save}>
        <label className="field">
          <span>Name</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </label>
        <div className="manual-grid">
          <label className="field">
            <span>Day</span>
            <input type="date" value={day} max={localDate()} onChange={(e) => e.target.value && setDay(e.target.value)} />
          </label>
          {hasGrams && (
            <label className="field">
              <span>Amount eaten (grams)</span>
              <input type="number" min={1} max={5000} step="any" value={grams} onChange={(e) => setGrams(e.target.value)} />
            </label>
          )}
        </div>
        <p className="food-group-title">
          {hasGrams ? <>Nutrition per 100 g</> : <>Nutrition for this entry <span className="muted small">(logged without an amount)</span></>}
        </p>
        <div className="manual-grid">
          {FIELDS.map(({ key, label, unit }) => (
            <label key={key} className="field">
              <span>{label} ({unit})</span>
              <input
                type="number"
                min={0}
                step="any"
                aria-label={`${label} (${unit})`}
                value={values[key] ?? ''}
                onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
              />
            </label>
          ))}
        </div>
        {hasGrams && totals && <p className="muted small">For {fmt(gramsNumber)} g: {summary(totals)}</p>}

        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost danger-text food-remove" onClick={remove} disabled={saving}>Remove</button>
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={!valid || saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}
