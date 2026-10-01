import { useEffect, useState } from 'react'
import { budgetApi, localDate, type BudgetEntry, type BudgetMonth } from '../../api'
import { Dialog } from '../../components/Dialog'
import { EntryDialog } from './EntryDialog'
import { MonthChart } from './MonthChart'
import { buildTree, formatMoney, isIncome, monthTitle, shiftMonth, type TreeNode } from './budgetUtils'
import './budget.css'

type Editing =
  | { kind: 'add'; path: string[] }
  | { kind: 'edit'; entry: BudgetEntry }
  | { kind: 'import' }

const key = (path: string[]) => path.join('\u0000')

// Full view of the Budget widget: one month's report (totals, category tree, budgets)
// plus the last 12 months. Every number is editable: entries (amount, category path,
// month) and budgets; the log can be imported/exported as CSV.
export function BudgetPage() {
  const thisMonth = localDate().slice(0, 7)
  const [month, setMonth] = useState(thisMonth)
  const [report, setReport] = useState<{ month: string; data?: BudgetMonth; error?: string } | null>(null)
  const [version, setVersion] = useState(0) // bump to reload after a change
  const [editing, setEditing] = useState<Editing | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([key(['Income']), key(['Expenses'])]))

  useEffect(() => {
    let cancelled = false
    budgetApi.month(month)
      .then((data) => { if (!cancelled) setReport({ month, data }) })
      .catch((err) => { if (!cancelled) setReport({ month, error: (err as Error).message }) })
    return () => { cancelled = true }
  }, [month, version])

  const reload = () => setVersion((v) => v + 1)
  const current = report?.month === month ? report : null
  const data = current?.data
  const money = (value: number, decimals = 0) => formatMoney(value, data?.currency ?? '', decimals)
  const canGoBack = !data?.first_month || month > data.first_month
  const toggle = (path: string[]) => setExpanded((prev) => {
    const next = new Set(prev)
    if (next.has(key(path))) next.delete(key(path))
    else next.add(key(path))
    return next
  })

  const removeGroup = async (node: TreeNode) => {
    const count = countEntries(node)
    if (!confirm(`Delete "${node.path.join(' › ')}" in ${monthTitle(month)} (${count} entr${count === 1 ? 'y' : 'ies'})?`)) return
    await budgetApi.removeGroup(node.path, month)
    reload()
  }

  return (
    <section className="budget-page">
      <div className="section-head">
        <h2>Budget</h2>
        <div className="budget-page-actions">
          <button className="button primary" onClick={() => setEditing({ kind: 'add', path: ['Expenses'] })}>+ Add entry</button>
          <button className="button ghost" onClick={() => setEditing({ kind: 'import' })}>Import CSV</button>
          <a className="button ghost" href={budgetApi.exportUrl} download>Export CSV</a>
        </div>
      </div>

      <div className="day-nav">
        <button className="button" onClick={() => setMonth(shiftMonth(month, -1))} disabled={!canGoBack} aria-label="Previous month">‹</button>
        <div className="day-nav-label">
          <strong>{monthTitle(month)}</strong>
          {data && <span className="muted small">{data.entries.length} entr{data.entries.length === 1 ? 'y' : 'ies'}</span>}
        </div>
        <button className="button" onClick={() => setMonth(shiftMonth(month, 1))} disabled={month >= thisMonth} aria-label="Next month">›</button>
        {month !== thisMonth && <button className="button ghost" onClick={() => setMonth(thisMonth)}>This month</button>}
      </div>

      {current?.error && <p className="error-text">{current.error}</p>}
      {!current && <p className="muted">Loading…</p>}

      {data && (
        <>
          <Stats data={data} money={money} />

          <div className="card budget-card">
            <div className="budget-card-head">
              <h3>Categories</h3>
              <span className="muted small">Tap an entry or ✎ to edit it · ＋ add · 🗑 delete (this month)</span>
            </div>
            {data.entries.length === 0 ? (
              <div className="empty">Nothing logged in {monthTitle(month)}.</div>
            ) : (
              <Tree
                nodes={buildTree(data.entries)}
                level={0}
                data={data}
                money={money}
                expanded={expanded}
                onToggle={toggle}
                onEdit={(entry) => setEditing({ kind: 'edit', entry })}
                onAdd={(path) => setEditing({ kind: 'add', path })}
                onDelete={removeGroup}
              />
            )}
          </div>

          <Budgets data={data} money={money} onSaved={reload} />
          <History data={data} money={money} onPick={setMonth} thisMonth={thisMonth} />
        </>
      )}

      {data && editing?.kind === 'add' && (
        <EntryDialog
          title="Add entry"
          initial={{ month, path: editing.path }}
          paths={data.paths}
          onSave={async (entry) => { await budgetApi.add(entry); reload() }}
          onClose={() => setEditing(null)}
        />
      )}
      {data && editing?.kind === 'edit' && (
        <EntryDialog
          title="Edit entry"
          initial={editing.entry}
          paths={data.paths}
          onSave={async (entry) => { await budgetApi.update(editing.entry.id, entry); reload() }}
          onDelete={async () => { await budgetApi.remove(editing.entry.id); reload() }}
          onClose={() => setEditing(null)}
        />
      )}
      {editing?.kind === 'import' && (
        <ImportDialog hasEntries={Boolean(data?.first_month)} onDone={reload} onClose={() => setEditing(null)} />
      )}
    </section>
  )
}

function countEntries(node: TreeNode): number {
  return node.own.length + node.children.reduce((sum, c) => sum + countEntries(c), 0)
}

type Money = (value: number, decimals?: number) => string

function Stats({ data, money }: { data: BudgetMonth; money: Money }) {
  const net = data.income - data.expenses
  const prev = data.previous.expenses
  const change = prev ? Math.round(((data.expenses - prev) / prev) * 100) : null
  const withData = data.history.filter((h) => h.income || h.expenses)
  const average = withData.length ? withData.reduce((s, h) => s + h.expenses, 0) / withData.length : 0
  return (
    <div className="budget-stats">
      <div className="card budget-stat">
        <span className="budget-stat-label">Income</span>
        <span className="budget-stat-value">{money(data.income)}</span>
      </div>
      <div className="card budget-stat">
        <span className="budget-stat-label">Spent</span>
        <span className="budget-stat-value">{money(data.expenses)}</span>
        {change !== null && <span className="muted small">{change > 0 ? '+' : ''}{change}% vs {monthTitle(data.previous.month, false)}</span>}
      </div>
      <div className="card budget-stat">
        <span className="budget-stat-label">Net</span>
        <span className={`budget-stat-value ${net < 0 ? 'budget-neg' : 'budget-pos'}`}>{net < 0 ? '−' : '+'}{money(Math.abs(net))}</span>
        {data.income > 0 && (
          <span className="muted small">
            {net >= 0 ? `${Math.round((net / data.income) * 100)}% of income saved` : `spent ${Math.round((-net / data.income) * 100)}% more than income`}
          </span>
        )}
      </div>
      <div className="card budget-stat">
        <span className="budget-stat-label">Avg. monthly spending</span>
        <span className="budget-stat-value">{money(average)}</span>
        <span className="muted small">over {withData.length} month{withData.length === 1 ? '' : 's'}</span>
      </div>
    </div>
  )
}

function Tree({ nodes, level, data, money, expanded, onToggle, onEdit, onAdd, onDelete }: {
  nodes: TreeNode[]
  level: number
  data: BudgetMonth
  money: Money
  expanded: Set<string>
  onToggle: (path: string[]) => void
  onEdit: (entry: BudgetEntry) => void
  onAdd: (path: string[]) => void
  onDelete: (node: TreeNode) => void
}) {
  return (
    <ul className="budget-tree">
      {nodes.map((node) => {
        const isLeaf = node.children.length === 0 && node.own.length === 1
        const open = expanded.has(key(node.path))
        // A spending category (Expenses › Rent): compare with last month and its budget
        const spending = node.path.length === 2 && !isIncome(node.path[0])
        const budget = spending ? data.budgets[node.name] : undefined
        const previous = spending ? data.previous.categories[node.name] : undefined
        return (
          <li key={node.name} className={`budget-level-${level}`}>
            <div className="budget-node-row">
              <span className="budget-node-name">
                {isLeaf ? (
                  <button className="budget-leaf" onClick={() => onEdit(node.own[0])} title="Edit">
                    <span className="budget-caret" aria-hidden>·</span><span>{node.name}</span>
                  </button>
                ) : (
                  <button className="budget-toggle" onClick={() => onToggle(node.path)} aria-expanded={open}>
                    <span className="budget-caret" aria-hidden>{open ? '▾' : '▸'}</span><span>{node.name}</span>
                  </button>
                )}
              </span>
              <span className="budget-node-total">
                {isLeaf ? (
                  <button className="budget-leaf" onClick={() => onEdit(node.own[0])}>{money(node.total, 2)}</button>
                ) : money(node.total, 2)}
                {(budget !== undefined || previous !== undefined) && (
                  <small>
                    {budget !== undefined && <>of {money(budget)}</>}
                    {budget !== undefined && previous !== undefined && ' · '}
                    {previous !== undefined && <>last month {money(previous)}</>}
                  </small>
                )}
              </span>
              <span className="budget-node-tools">
                {node.path.length < 4 && <button className="icon-button" onClick={() => onAdd(node.path)} title="Add under this" aria-label={`Add under ${node.name}`}>＋</button>}
                {isLeaf && <button className="icon-button" onClick={() => onEdit(node.own[0])} title="Edit" aria-label={`Edit ${node.name}`}>✎</button>}
                <button className="icon-button" onClick={() => onDelete(node)} title="Delete (this month)" aria-label={`Delete ${node.name}`}>🗑</button>
              </span>
            </div>
            {!isLeaf && open && (
              <>
                {node.own.length > 0 && (
                  <ul className="budget-tree">
                    {node.own.map((entry) => (
                      <li key={entry.id}>
                        <div className="budget-node-row">
                          <span className="budget-node-name">
                            <button className="budget-leaf budget-own" onClick={() => onEdit(entry)}>
                              <span className="budget-caret" aria-hidden>·</span><span>(no sub-category)</span>
                            </button>
                          </span>
                          <span className="budget-node-total">
                            <button className="budget-leaf" onClick={() => onEdit(entry)}>{money(entry.amount, 2)}</button>
                          </span>
                          <span className="budget-node-tools">
                            <button className="icon-button" onClick={() => onEdit(entry)} title="Edit" aria-label={`Edit ${node.name} (no sub-category)`}>✎</button>
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                {node.children.length > 0 && (
                  <Tree nodes={node.children} level={level + 1} data={data} money={money} expanded={expanded}
                    onToggle={onToggle} onEdit={onEdit} onAdd={onAdd} onDelete={onDelete} />
                )}
              </>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function Budgets({ data, money, onSaved }: { data: BudgetMonth; money: Money; onSaved: () => void }) {
  const spent: Record<string, number> = {}
  for (const e of data.entries) {
    if (isIncome(e.path[0])) continue
    const name = e.path[1] ?? e.path[0]
    spent[name] = (spent[name] ?? 0) + e.amount
  }
  const names = [...new Set([...Object.keys(data.budgets), ...Object.keys(spent)])]
    .sort((a, b) => (spent[b] ?? 0) - (spent[a] ?? 0) || a.localeCompare(b))
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(data.budgets).map(([k, v]) => [k, String(v)])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const changed = names.some((n) => (values[n] ?? '') !== (data.budgets[n] !== undefined ? String(data.budgets[n]) : ''))

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const budgets: Record<string, number | null> = {}
      for (const n of names) {
        const v = (values[n] ?? '').trim()
        budgets[n] = v ? Number(v.replace(',', '.')) : null
      }
      await budgetApi.setBudgets(budgets)
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const total = Object.values(data.budgets).reduce((s, v) => s + v, 0)
  return (
    <div className="card budget-card">
      <div className="budget-card-head">
        <h3>Monthly budgets</h3>
        {total > 0 && <span className="muted small">{money(total)} per month in total</span>}
      </div>
      {names.length === 0 ? (
        <div className="empty">Add spending entries first, then set a budget per category.</div>
      ) : (
        <ul className="budget-limits">
          {names.map((n) => {
            const budget = data.budgets[n]
            const ratio = budget ? (spent[n] ?? 0) / budget : null
            return (
              <li key={n}>
                <span className="budget-name">{n}</span>
                <input type="text" inputMode="decimal" value={values[n] ?? ''} placeholder="no budget" aria-label={`Budget for ${n}`}
                  onChange={(e) => setValues({ ...values, [n]: e.target.value })} />
                <span className="muted small budget-value budget-limit-spent">{money(spent[n] ?? 0)} spent</span>
                {ratio !== null && (
                  <span className="bar">
                    <span className={`bar-fill ${ratio > 1 ? 'over' : ratio > 0.85 ? 'progress' : 'done'}`} style={{ width: `${Math.min(ratio, 1) * 100}%` }} />
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {error && <p className="error-text small">{error}</p>}
      {names.length > 0 && (
        <div className="dialog-actions">
          <button className="button primary" onClick={save} disabled={!changed || busy}>{busy ? 'Saving…' : 'Save budgets'}</button>
        </div>
      )}
    </div>
  )
}

function History({ data, money, onPick, thisMonth }: { data: BudgetMonth; money: Money; onPick: (m: string) => void; thisMonth: string }) {
  return (
    <div className="card budget-card">
      <h3>Last 12 months</h3>
      <MonthChart history={data.history} current={data.month} lastMonth={thisMonth} money={money} onPick={onPick} />
      <div className="budget-legend"><span><i className="budget-history-income" />Income</span><span><i className="budget-history-expenses" />Spent</span><span>Tap a month to open it</span></div>
    </div>
  )
}

function ImportDialog({ hasEntries, onDone, onClose }: { hasEntries: boolean; onDone: () => void; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [replace, setReplace] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!file) return
    if (replace && hasEntries && !confirm('Replace your whole budget log with this file? Entries not in the file are deleted.')) return
    setBusy(true)
    setError(null)
    try {
      const r = await budgetApi.importCsv(await file.text(), replace)
      setResult(`Imported ${r.imported} entr${r.imported === 1 ? 'y' : 'ies'}` +
        (r.skipped ? `; skipped ${r.skipped} unreadable row${r.skipped === 1 ? '' : 's'}: ${r.problems.join('; ')}` : '.'))
      onDone()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Import CSV" onClose={onClose}>
      <div className="budget-import">
        <p>
          Columns: <b>Month</b> (2026-09), <b>Category</b>, <b>Sub-category</b>, <b>Sub-sub-category</b>,{' '}
          <b>Sub-sub-sub-category</b>, <b>Amount</b>. From Google Sheets: File → Download → Comma-separated values (.csv).
        </p>
        <input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null) }} />
        {hasEntries && (
          <label><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace everything already in the budget (otherwise the rows are added)</label>
        )}
        {result && <p className="budget-pos">{result}</p>}
        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button className="button ghost" onClick={onClose}>{result ? 'Done' : 'Cancel'}</button>
          {!result && <button className="button primary" onClick={run} disabled={!file || busy}>{busy ? 'Importing…' : 'Import'}</button>}
        </div>
      </div>
    </Dialog>
  )
}
