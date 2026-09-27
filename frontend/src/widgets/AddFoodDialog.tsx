import { useEffect, useState, type FormEvent } from 'react'
import { localDate, nutritionApi, type FoodResult, type NutrientKey, type NutrientValues } from '../api'
import { Dialog } from '../components/Dialog'

const FIELDS: { key: NutrientKey; label: string; unit: string }[] = [
  { key: 'calories', label: 'Calories', unit: 'kcal' },
  { key: 'protein', label: 'Protein', unit: 'g' },
  { key: 'carbs', label: 'Carbs', unit: 'g' },
  { key: 'fat', label: 'Fat', unit: 'g' },
  { key: 'fiber', label: 'Fiber', unit: 'g' },
  { key: 'sugar', label: 'Sugar', unit: 'g' },
  { key: 'sat_fat', label: 'Saturated fat', unit: 'g' },
]

function scale(per100: NutrientValues, grams: number): NutrientValues {
  return Object.fromEntries(
    FIELDS.map(({ key }) => [key, Math.round((per100[key] * grams) / 10) / 10]),
  ) as NutrientValues
}

type Props = { day: string; personalKey: boolean; onAdded: () => void; onClose: () => void }

export function AddFoodDialog({ day, personalKey, onAdded, onClose }: Props) {
  const [mode, setMode] = useState<'search' | 'manual'>('search')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Search mode
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<FoodResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<FoodResult | null>(null)
  const [grams, setGrams] = useState('100')

  // Manual mode
  const [name, setName] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})

  // Search as you type, after a short pause
  useEffect(() => {
    const q = query.trim()
    if (mode !== 'search' || q.length < 2) {
      setResults(null)
      return
    }
    setSearching(true)
    const timer = setTimeout(() => {
      nutritionApi.searchFoods(q)
        .then((r) => { setResults(r); setError(null) })
        .catch((err) => setError(err.message))
        .finally(() => setSearching(false))
    }, 450)
    return () => { clearTimeout(timer); setSearching(false) }
  }, [query, mode])

  const gramsNumber = Number(grams)
  const preview = picked && gramsNumber > 0 ? scale(picked.per_100g, gramsNumber) : null

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (mode === 'search') {
        if (!picked || !preview) return
        await nutritionApi.addEntry(day, { name: picked.name, grams: gramsNumber, nutrients: preview, source: 'usda', fdc_id: picked.fdc_id })
      } else {
        const nutrients = Object.fromEntries(FIELDS.map(({ key }) => [key, Number(values[key] || 0)]))
        await nutritionApi.addEntry(day, { name: name.trim() || 'Food', nutrients, source: 'manual' })
      }
      onAdded()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      title={day === localDate() ? 'Add food' : `Add food · ${new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}`}
      onClose={onClose}
    >
      <div className="segmented plain" role="tablist">
        <button type="button" className={mode === 'search' ? 'active' : ''} onClick={() => setMode('search')}>Search foods</button>
        <button type="button" className={mode === 'manual' ? 'active' : ''} onClick={() => setMode('manual')}>Enter manually</button>
      </div>

      <form className="settings-form food-form" onSubmit={save}>
        {mode === 'search' ? (
          <>
            {!picked ? (
              <>
                <label className="field">
                  <span>What did you eat?</span>
                  <input
                    type="text"
                    autoFocus
                    placeholder="e.g. salmon cooked, rice white cooked, greek yogurt"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                {searching && <p className="muted small">Searching…</p>}
                {results && results.length === 0 && !searching && (
                  <p className="muted small">No matches. Try simpler words, or enter it manually.</p>
                )}
                {results && results.length > 0 && (
                  <ul className="food-results">
                    {results.map((r) => (
                      <li key={r.fdc_id}>
                        <button type="button" onClick={() => setPicked(r)}>
                          <span>{r.name}</span>
                          <span className="muted small">
                            per 100 g: {Math.round(r.per_100g.calories)} kcal · {r.per_100g.protein} g protein
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {!personalKey && (
                  <p className="muted small">Using the shared USDA demo key (about 10 searches an hour).</p>
                )}
              </>
            ) : (
              <>
                <div className="picked">
                  <strong>{picked.name}</strong>
                  <button type="button" className="link" onClick={() => setPicked(null)}>Change</button>
                </div>
                <label className="field">
                  <span>Amount (grams)</span>
                  <input type="number" min={1} max={5000} value={grams} onChange={(e) => setGrams(e.target.value)} autoFocus />
                </label>
                {preview && (
                  <p className="muted small">
                    {FIELDS.map(({ key, label, unit }) => `${label} ${preview[key]} ${unit}`).join(' · ')}
                  </p>
                )}
              </>
            )}
          </>
        ) : (
          <>
            <label className="field">
              <span>Name</span>
              <input type="text" autoFocus placeholder="e.g. Protein bar" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <div className="manual-grid">
              {FIELDS.map(({ key, label, unit }) => (
                <label key={key} className="field">
                  <span>{label} ({unit})</span>
                  <input
                    type="number"
                    aria-label={`${label} (${unit})`}
                    min={0}
                    step="any"
                    value={values[key] ?? ''}
                    onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                  />
                </label>
              ))}
            </div>
          </>
        )}

        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button
            type="submit"
            className="button primary"
            disabled={saving || (mode === 'search' ? !preview : !FIELDS.some(({ key }) => Number(values[key]) > 0))}
          >
            {saving ? 'Adding…' : 'Add'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
