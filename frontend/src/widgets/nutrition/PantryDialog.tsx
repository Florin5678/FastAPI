import { useEffect, useState, type FormEvent } from 'react'
import { localDate, nutritionApi, type PantryItem, type PantryItemIn } from '../../api'
import { Dialog } from '../../components/Dialog'

const EMPTY: PantryItemIn = { name: '', amount: '', expires: null }

// "Best before 12 Oct" / "Expires today" / "Expired 3 days ago"
function expiryLabel(expires: string | null): { text: string; tone: string } | null {
  if (!expires) return null
  const days = Math.round((new Date(expires + 'T12:00').getTime() - new Date(localDate() + 'T12:00').getTime()) / 86400000)
  if (days < 0) return { text: `Expired ${-days === 1 ? 'yesterday' : `${-days} days ago`}`, tone: 'expired' }
  if (days === 0) return { text: 'Best before today', tone: 'soon' }
  if (days <= 3) return { text: `Best before ${days === 1 ? 'tomorrow' : `in ${days} days`}`, tone: 'soon' }
  return { text: `Best before ${new Date(expires + 'T12:00').toLocaleDateString([], { day: 'numeric', month: 'short' })}`, tone: '' }
}

// The food at home: add, edit and remove items. Kept out of the briefing; Claude reads it
// (get_pantry) for meal suggestions and can update it too.
export function PantryDialog({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<PantryItem[] | null>(null)
  const [draft, setDraft] = useState<PantryItemIn>(EMPTY)
  const [editing, setEditing] = useState<string | null>(null) // id being edited, or null = adding
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    nutritionApi.pantry()
      .then((r) => { if (!cancelled) setItems(r.items) })
      .catch((err) => { if (!cancelled) setError((err as Error).message) })
    return () => { cancelled = true }
  }, [])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      setItems((await nutritionApi.pantry()).items)
      return true
    } catch (err) {
      setError((err as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!draft.name.trim()) return
    const item = { ...draft, name: draft.name.trim(), amount: draft.amount.trim() }
    if (await run(() => (editing ? nutritionApi.updatePantryItem(editing, item) : nutritionApi.addPantryItem(item)))) {
      setDraft(EMPTY)
      setEditing(null)
    }
  }

  const edit = (item: PantryItem) => {
    setEditing(item.id)
    setDraft({ name: item.name, amount: item.amount, expires: item.expires })
  }

  return (
    <Dialog title="Pantry" onClose={onClose}>
      <p className="muted small pantry-intro">Food you have at home. Claude uses it for meal suggestions; it isn't part of your briefing.</p>
      <form className="settings-form pantry-form" onSubmit={submit}>
        <input type="text" placeholder="e.g. Red lentils" value={draft.name} maxLength={120} autoFocus aria-label="Food"
          onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input type="text" placeholder="Amount (e.g. 500 g)" value={draft.amount} maxLength={60} aria-label="Amount"
          onChange={(e) => setDraft({ ...draft, amount: e.target.value })} />
        <label className="pantry-expires">
          <span className="muted small">Best before</span>
          <input type="date" value={draft.expires ?? ''} aria-label="Best before (optional)"
            onChange={(e) => setDraft({ ...draft, expires: e.target.value || null })} />
        </label>
        <div className="pantry-form-actions">
          {editing && <button type="button" className="button ghost small-button" onClick={() => { setEditing(null); setDraft(EMPTY) }}>Cancel</button>}
          <button type="submit" className="button primary small-button" disabled={busy || !draft.name.trim()}>{editing ? 'Save' : 'Add'}</button>
        </div>
      </form>

      {error && <p className="error-text small">{error}</p>}
      {items === null && !error && <p className="muted small">Loading…</p>}
      {items && items.length === 0 && <p className="muted small">Nothing in the pantry yet.</p>}
      {items && items.length > 0 && (
        <ul className="pantry-list">
          {items.map((item) => {
            const expiry = expiryLabel(item.expires)
            return (
              <li key={item.id} className={editing === item.id ? 'editing' : ''}>
                <button type="button" className="pantry-item" onClick={() => edit(item)} title="Edit">
                  <span className="pantry-name">{item.name}{item.amount && <span className="muted"> · {item.amount}</span>}</span>
                  {expiry && <span className={`small pantry-expiry ${expiry.tone}`}>{expiry.text}</span>}
                </button>
                <button type="button" className="icon-button" disabled={busy} title="Remove (used up)"
                  aria-label={`Remove ${item.name}`} onClick={() => run(() => nutritionApi.deletePantryItem(item.id))}>✕</button>
              </li>
            )
          })}
        </ul>
      )}
    </Dialog>
  )
}
