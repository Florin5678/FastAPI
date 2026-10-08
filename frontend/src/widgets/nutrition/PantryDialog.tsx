import { useEffect, useState, type FormEvent } from 'react'
import { localDate, nutritionApi, type PantryItem, type ShoppingItem } from '../../api'
import { Dialog } from '../../components/Dialog'

export type PantryTab = 'pantry' | 'shopping'
type Draft = { name: string; amount: string; expires: string | null }
const EMPTY: Draft = { name: '', amount: '', expires: null }

// "Best before 12 Oct" / "Best before tomorrow" / "Expired 3 days ago"
function expiryLabel(expires: string | null): { text: string; tone: string } | null {
  if (!expires) return null
  const days = Math.round((new Date(expires + 'T12:00').getTime() - new Date(localDate() + 'T12:00').getTime()) / 86400000)
  if (days < 0) return { text: `Expired ${-days === 1 ? 'yesterday' : `${-days} days ago`}`, tone: 'expired' }
  if (days === 0) return { text: 'Best before today', tone: 'soon' }
  if (days <= 3) return { text: `Best before ${days === 1 ? 'tomorrow' : `in ${days} days`}`, tone: 'soon' }
  return { text: `Best before ${new Date(expires + 'T12:00').toLocaleDateString([], { day: 'numeric', month: 'short' })}`, tone: '' }
}

// The food at home and the shopping list (the Nutrition tile opens either tab). Pantry items can be
// starred (★ use first: close to expiring, opened cans...), which pins them at the top and meal
// plans prioritise. Kept out of the briefing; Claude reads and changes both lists through the connector.
export function PantryDialog({ initialTab = 'pantry', onClose }: { initialTab?: PantryTab; onClose: () => void }) {
  const [tab, setTab] = useState<PantryTab>(initialTab)
  const [pantry, setPantry] = useState<PantryItem[] | null>(null)
  const [shopping, setShopping] = useState<ShoppingItem[]>([])
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [editing, setEditing] = useState<string | null>(null) // id being edited, or null = adding
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    nutritionApi.pantry()
      .then((r) => { if (!cancelled) { setPantry(r.items); setShopping(r.shopping) } })
      .catch((err) => { if (!cancelled) setError((err as Error).message) })
    return () => { cancelled = true }
  }, [])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      const r = await nutritionApi.pantry()
      setPantry(r.items)
      setShopping(r.shopping)
      return true
    } catch (err) {
      setError((err as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const switchTab = (next: PantryTab) => { setTab(next); setEditing(null); setDraft(EMPTY) }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!draft.name.trim()) return
    const name = draft.name.trim()
    const amount = draft.amount.trim()
    const ok = await run(() => {
      if (tab === 'pantry') {
        const item = { name, amount, expires: draft.expires }
        return editing ? nutritionApi.updatePantryItem(editing, item) : nutritionApi.addPantryItem(item)
      }
      return editing ? nutritionApi.updateShoppingItem(editing, { name, amount }) : nutritionApi.addShoppingItem({ name, amount })
    })
    if (ok) {
      setDraft(EMPTY)
      setEditing(null)
    }
  }

  const starred = (pantry ?? []).filter((i) => i.priority).length

  return (
    <Dialog title={tab === 'shopping' ? 'Shopping list' : 'Pantry'} onClose={onClose}>
      <div className="segmented plain" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'pantry'} className={tab === 'pantry' ? 'active' : ''} onClick={() => switchTab('pantry')}>
          Pantry{pantry && pantry.length > 0 && ` (${pantry.length})`}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'shopping'} className={tab === 'shopping' ? 'active' : ''} onClick={() => switchTab('shopping')}>
          Shopping list{shopping.length > 0 && ` (${shopping.length})`}
        </button>
      </div>
      <p className="muted small pantry-intro">
        {tab === 'pantry'
          ? <>Food you have at home. ★ marks items to use first{starred > 0 && ` (${starred} starred)`}: they stay at the top and meal plans include them where they fit. Not part of your briefing.</>
          : <>What you plan to buy. ✓ moves an item to the pantry once bought.</>}
      </p>

      <form className={tab === 'pantry' ? 'settings-form pantry-form' : 'settings-form pantry-form shopping'} onSubmit={submit}>
        <input type="text" placeholder={tab === 'pantry' ? 'e.g. Red lentils' : 'e.g. Oat milk'} value={draft.name} maxLength={120} autoFocus aria-label="Food"
          onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input type="text" placeholder="Amount (e.g. 500 g)" value={draft.amount} maxLength={60} aria-label="Amount"
          onChange={(e) => setDraft({ ...draft, amount: e.target.value })} />
        {tab === 'pantry' && (
          <label className="pantry-expires">
            <span className="muted small">Best before</span>
            <input type="date" value={draft.expires ?? ''} aria-label="Best before (optional)"
              onChange={(e) => setDraft({ ...draft, expires: e.target.value || null })} />
          </label>
        )}
        <div className="pantry-form-actions">
          {editing && <button type="button" className="button ghost small-button" onClick={() => { setEditing(null); setDraft(EMPTY) }}>Cancel</button>}
          <button type="submit" className="button primary small-button" disabled={busy || !draft.name.trim()}>{editing ? 'Save' : 'Add'}</button>
        </div>
      </form>

      {error && <p className="error-text small">{error}</p>}
      {pantry === null && !error && <p className="muted small">Loading…</p>}

      {pantry && tab === 'pantry' && (pantry.length === 0 ? <p className="muted small">Nothing in the pantry yet.</p> : (
        <ul className="pantry-list">
          {pantry.map((item) => {
            const expiry = expiryLabel(item.expires)
            return (
              <li key={item.id} className={editing === item.id ? 'editing' : ''}>
                <button type="button" className={item.priority ? 'pantry-star on' : 'pantry-star'} disabled={busy}
                  aria-pressed={item.priority} aria-label={item.priority ? `Unstar ${item.name}` : `Star ${item.name} (use first)`}
                  title={item.priority ? 'Priority: used first in meal plans (click to unstar)' : 'Star: use first'}
                  onClick={() => run(() => nutritionApi.updatePantryItem(item.id, { priority: !item.priority }))}>
                  {item.priority ? '★' : '☆'}
                </button>
                <button type="button" className="pantry-item" title="Edit"
                  onClick={() => { setEditing(item.id); setDraft({ name: item.name, amount: item.amount, expires: item.expires }) }}>
                  <span className="pantry-name">{item.name}{item.amount && <span className="muted"> · {item.amount}</span>}</span>
                  {expiry && <span className={`small pantry-expiry ${expiry.tone}`}>{expiry.text}</span>}
                </button>
                <button type="button" className="icon-button" disabled={busy} title="Used up: move to the shopping list"
                  aria-label={`Move ${item.name} to the shopping list`} onClick={() => run(() => nutritionApi.pantryToShopping(item.id))}>🛒</button>
                <button type="button" className="icon-button" disabled={busy} title="Remove"
                  aria-label={`Remove ${item.name}`} onClick={() => run(() => nutritionApi.deletePantryItem(item.id))}>✕</button>
              </li>
            )
          })}
        </ul>
      ))}

      {pantry && tab === 'shopping' && (shopping.length === 0 ? <p className="muted small">The shopping list is empty.</p> : (
        <ul className="pantry-list">
          {shopping.map((item) => (
            <li key={item.id} className={editing === item.id ? 'editing' : ''}>
              <button type="button" className="icon-button pantry-bought" disabled={busy} title="Bought: move to the pantry"
                aria-label={`Bought ${item.name}: move to the pantry`} onClick={() => run(() => nutritionApi.shoppingToPantry(item.id))}>✓</button>
              <button type="button" className="pantry-item" title="Edit"
                onClick={() => { setEditing(item.id); setDraft({ name: item.name, amount: item.amount, expires: null }) }}>
                <span className="pantry-name">{item.name}{item.amount && <span className="muted"> · {item.amount}</span>}</span>
                {item.note && <span className="small muted">{item.note}</span>}
              </button>
              <button type="button" className="icon-button" disabled={busy} title="Remove"
                aria-label={`Remove ${item.name}`} onClick={() => run(() => nutritionApi.deleteShoppingItem(item.id))}>✕</button>
            </li>
          ))}
        </ul>
      ))}
    </Dialog>
  )
}
