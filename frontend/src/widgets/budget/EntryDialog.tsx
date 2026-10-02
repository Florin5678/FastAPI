import { useMemo, useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { LEVEL_NAMES } from './budgetUtils'

const TOP_LEVELS = ['Expenses', 'Income']

// Add or edit one entry: month, up to four category levels and the amount. The category is
// Expenses or Income; an expense's sub-category is one of the fixed list (the server checks
// too); lower levels and income sub-categories are free text, with suggestions from the log.
export function EntryDialog({ title, initial, paths, expenseCategories, onSave, onDelete, onClose }: {
  title: string
  initial: { month: string; path: string[]; amount?: number }
  paths: string[][]
  expenseCategories: string[]
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
  const isExpense = levels[0] === 'Expenses'
  const subMissing = isExpense && !expenseCategories.includes(levels[1])
  const valid = /^\d{4}-(0[1-9]|1[0-2])$/.test(month) && TOP_LEVELS.includes(levels[0]) && !subMissing &&
    !gap && amount.trim() !== '' && Number.isFinite(value)
  const setLevel = (i: number, text: string) => setLevels(levels.map((l, j) => (j === i ? text : l)))

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
        <label>
          <span>{LEVEL_NAMES[0]}</span>
          <select value={levels[0]} required
            onChange={(e) => setLevels([e.target.value, ...levels.slice(1).map((l) => (e.target.value === levels[0] ? l : ''))])}>
            {!TOP_LEVELS.includes(levels[0]) && <option value="">Choose…</option>}
            {TOP_LEVELS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        {LEVEL_NAMES.slice(1).map((name, k) => {
          const i = k + 1
          if (i === 1 && isExpense) {
            return (
              <label key={name}>
                <span>{name}</span>
                <select value={expenseCategories.includes(levels[1]) ? levels[1] : ''} required onChange={(e) => setLevel(1, e.target.value)}>
                  <option value="" disabled>Choose…</option>
                  {expenseCategories.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            )
          }
          return (
            <label key={name}>
              <span>{name} <span className="muted">(optional)</span></span>
              <input
                list={`budget-level-${i}`}
                value={levels[i]}
                onChange={(e) => setLevel(i, e.target.value)}
                maxLength={120}
                disabled={!levels[i - 1].trim() && !levels[i].trim()}
              />
              <datalist id={`budget-level-${i}`}>
                {suggestions[i].map((s) => <option key={s} value={s} />)}
              </datalist>
            </label>
          )
        })}
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
