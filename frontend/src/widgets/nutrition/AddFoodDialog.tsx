import { useEffect, useState, type FormEvent } from 'react'
import { localDate, nutritionApi, type FoodResult, type NutrientValues, type SavedFood } from '../../api'
import { Dialog } from '../../components/Dialog'
import { FIELDS, fmt, scale, summary, toValues } from './nutrients'

// What was picked in the search tab: a USDA food or one of "My foods"
type Picked =
  | { kind: 'usda'; name: string; per_100g: NutrientValues; fdc_id: number }
  | { kind: 'saved'; name: string; per_100g: NutrientValues; id: string }

type Props = { day: string; personalKey: boolean; onAdded: () => void; onClose: () => void }

export function AddFoodDialog({ day, personalKey, onAdded, onClose }: Props) {
  const [mode, setMode] = useState<'search' | 'manual'>('search')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // "My foods" (foods entered by hand before)
  const [saved, setSaved] = useState<SavedFood[] | null>(null)

  // Search mode
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<FoodResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<Picked | null>(null)
  const [grams, setGrams] = useState('100')

  // Manual mode: values per 100 g + the amount eaten
  const [name, setName] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [manualGrams, setManualGrams] = useState('100')
  const [saveFood, setSaveFood] = useState(true)

  useEffect(() => {
    let cancelled = false
    nutritionApi.savedFoods()
      .then((r) => { if (!cancelled) setSaved(r.foods) })
      .catch(() => { if (!cancelled) setSaved([]) })
    return () => { cancelled = true }
  }, [])

  // Search USDA as you type, after a short pause
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

  const q = query.trim().toLowerCase()
  const myFoods = (saved ?? []).filter((f) => !q || f.name.toLowerCase().includes(q)).slice(0, q ? 20 : 8)

  const pickSaved = (f: SavedFood) => {
    setPicked({ kind: 'saved', name: f.name, per_100g: f.per_100g, id: f.id })
    setGrams(String(f.grams ?? 100))
  }

  const removeSaved = async (f: SavedFood) => {
    if (!confirm(`Remove "${f.name}" from My foods? (Logged entries stay.)`)) return
    try {
      await nutritionApi.deleteSavedFood(f.id)
      setSaved((list) => (list ?? []).filter((x) => x.id !== f.id))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const gramsNumber = Number(grams)
  const preview = picked && gramsNumber > 0 ? scale(picked.per_100g, gramsNumber) : null

  const manualPer100 = toValues(values)
  const manualGramsNumber = Number(manualGrams.replace(',', '.'))
  const manualTotals = manualGramsNumber > 0 ? scale(manualPer100, manualGramsNumber) : null
  const manualValid = manualTotals !== null && FIELDS.some(({ key }) => manualPer100[key] > 0)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (mode === 'search') {
        if (!picked || !preview) return
        await nutritionApi.addEntry(day, picked.kind === 'usda'
          ? { name: picked.name, grams: gramsNumber, nutrients: preview, source: 'usda', fdc_id: picked.fdc_id }
          : { name: picked.name, grams: gramsNumber, nutrients: preview, source: 'manual', saved_food_id: picked.id })
      } else {
        if (!manualTotals) return
        await nutritionApi.addEntry(day, {
          name: name.trim() || 'Food', grams: manualGramsNumber, nutrients: manualTotals, source: 'manual',
          per_100g: manualPer100, save: saveFood && name.trim() !== '',
        })
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
                    placeholder="e.g. protein bar, salmon cooked, greek yogurt"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>

                {myFoods.length > 0 && (
                  <>
                    <p className="food-group-title">My foods</p>
                    <ul className="food-results">
                      {myFoods.map((f) => (
                        <li key={f.id} className="saved-food">
                          <button type="button" onClick={() => pickSaved(f)}>
                            <span>{f.name}</span>
                            <span className="muted small">
                              per 100 g: {fmt(f.per_100g.calories)} kcal · {fmt(f.per_100g.protein)} g protein
                              {f.grams ? ` · usually ${fmt(f.grams)} g` : ''}
                            </span>
                          </button>
                          <button type="button" className="icon-button" onClick={() => removeSaved(f)} aria-label={`Remove ${f.name} from My foods`} title="Remove from My foods">✕</button>
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                {q.length >= 2 && <p className="food-group-title">Food database (USDA)</p>}
                {searching && <p className="muted small">Searching…</p>}
                {results && results.length === 0 && !searching && (
                  <p className="muted small">No matches. Try simpler words, or enter it manually.</p>
                )}
                {results && results.length > 0 && (
                  <ul className="food-results">
                    {results.map((r) => (
                      <li key={r.fdc_id}>
                        <button type="button" onClick={() => { setPicked({ kind: 'usda', name: r.name, per_100g: r.per_100g, fdc_id: r.fdc_id }); setGrams('100') }}>
                          <span>{r.name}</span>
                          <span className="muted small">
                            per 100 g: {Math.round(r.per_100g.calories)} kcal · {r.per_100g.protein} g protein
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {!personalKey && q.length >= 2 && (
                  <p className="muted small">Using the shared USDA demo key (about 10 searches an hour).</p>
                )}
              </>
            ) : (
              <>
                <div className="picked">
                  <strong>{picked.name}{picked.kind === 'saved' && <span className="muted small"> · My foods</span>}</strong>
                  <button type="button" className="link" onClick={() => setPicked(null)}>Change</button>
                </div>
                <label className="field">
                  <span>Amount eaten (grams)</span>
                  <input type="number" min={1} max={5000} step="any" value={grams} onChange={(e) => setGrams(e.target.value)} autoFocus />
                </label>
                {preview && <p className="muted small">{summary(preview)}</p>}
              </>
            )}
          </>
        ) : (
          <>
            <label className="field">
              <span>Name</span>
              <input type="text" autoFocus placeholder="e.g. Protein bar" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              <span>Amount eaten (grams)</span>
              <input type="number" min={1} max={5000} step="any" value={manualGrams} onChange={(e) => setManualGrams(e.target.value)} />
            </label>
            <p className="food-group-title">Nutrition per 100 g <span className="muted small">(as on the label)</span></p>
            <div className="manual-grid">
              {FIELDS.map(({ key, label, unit }) => (
                <label key={key} className="field">
                  <span>{label} ({unit})</span>
                  <input
                    type="number"
                    aria-label={`${label} per 100 g (${unit})`}
                    min={0}
                    step="any"
                    value={values[key] ?? ''}
                    onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                  />
                </label>
              ))}
            </div>
            {manualValid && manualTotals && (
              <p className="muted small">For {fmt(manualGramsNumber)} g: {summary(manualTotals)}</p>
            )}
            <label className="field checkbox">
              <input type="checkbox" checked={saveFood} onChange={(e) => setSaveFood(e.target.checked)} />
              <span>Save to My foods, to pick it again next time</span>
            </label>
          </>
        )}

        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving || (mode === 'search' ? !preview : !manualValid)}>
            {saving ? 'Adding…' : 'Add'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
