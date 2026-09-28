import { useMemo, useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { LEVEL_NAMES } from './budgetUtils'

// Add or edit one entry: month, up to four category levels (with suggestions from the
// existing log) and the amount
export function EntryDialog({ title, initial, paths, onSave, onDelete, onClose }: {
  title: string
  initial: { month: string; path: string[]; amount?: number }
  paths: string[][]
  onSave: (entry: { month: string; path: string[]; amount: number }) => Promise<void>
  onDelete?: () => Promise<void>
  onClose: () => void
}) {
  const [month, setMonth] = useState(initial.month)
  const [levels, setLevels] = useState(() => LEVEL_NAMES.map((_, i) => initial.path[i] ?? ''))
  const [amount, setAmount] = useState(initial.amount !== undefined ? String(initial.amount) : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Suggestions for each level: names used under the levels chosen above it
  const suggestions = useMemo(() => LEVEL_NAMES.map((_, i) => {
    const names = new Set<string>()
    for (const p of paths) {
      if (p.length > i && levels.slice(0, i).every((l, j) => l.trim() === p[j])) names.add(p[i])
    }
    return [...names].sort((a, b) => a.localeCompare(b))
  }), [paths, levels])

  const path = levels.map((l) => l.trim())
  while (path.length && !path[path.length - 1]) path.pop()
  const gap = path.some((l) => !l)
  const value = Number(amount.replace(',', '.'))
  const valid = /^\d{4}-(0[1-9]|1[0-2])$/.test(month) && path.length > 0 && !gap && amount.trim() !== '' && Number.isFinite(value)

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <Dialog title={title} onClose={onClose}>
      <form className="budget-form" onSubmit={(e) => { e.preventDefault(); if (valid) void run(() => onSave({ month, path, amount: value })) }}>
        <label>
          <span>Month</span>
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} required />
        </label>
        {LEVEL_NAMES.map((name, i) => (
          <label key={name}>
            <span>{name}{i > 0 && <span className="muted"> (optional)</span>}</span>
            <input
              list={`budget-level-${i}`}
              value={levels[i]}
              onChange={(e) => setLevels(levels.map((l, j) => (j === i ? e.target.value : l)))}
              placeholder={i === 0 ? 'Expenses or Income' : ''}
              maxLength={120}
              disabled={i > 0 && !levels[i - 1].trim() && !levels[i].trim()}
            />
            <datalist id={`budget-level-${i}`}>
              {suggestions[i].map((s) => <option key={s} value={s} />)}
            </datalist>
          </label>
        ))}
        <label>
          <span>Amount</span>
          <input type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required />
        </label>
        {gap && <p className="error-text small">Fill in the levels in order (no empty level in between).</p>}
        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          {onDelete && (
            <button type="button" className="button ghost danger-text" disabled={busy}
              onClick={() => { if (confirm('Delete this entry?')) void run(onDelete) }}>Delete</button>
          )}
          <span className="spacer" />
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={!valid || busy}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}
