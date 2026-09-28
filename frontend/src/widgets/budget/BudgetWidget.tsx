import { useState } from 'react'
import { budgetApi } from '../../api'
import type { WidgetProps } from '../types'
import { EntryDialog, formatMoney, monthTitle } from './shared'
import './budget.css'

export type BudgetData = {
  month: string // YYYY-MM
  has_entries: boolean
  currency: string
  income: number
  expenses: number
  last_month_expenses: number | null
  budget_total: number | null
  categories: { category: string; spent: number; budget: number | null }[]
  more_categories: number
  paths: string[][]
}

export function BudgetWidget({ data, actions, reload }: WidgetProps<BudgetData>) {
  const [adding, setAdding] = useState(false)
  const money = (value: number) => formatMoney(value, data.currency)
  const openReport = () => actions.goTo('budget')

  if (!data.has_entries) {
    return (
      <div className="budget-widget budget-empty">
        <p>Keep your income and expenses here: import your existing log once (CSV), then add and edit entries from the dashboard.</p>
        <button className="button primary" onClick={openReport}>Open budget →</button>
      </div>
    )
  }

  const change = data.last_month_expenses ? Math.round(((data.expenses - data.last_month_expenses) / data.last_month_expenses) * 100) : null
  const net = data.income - data.expenses
  const maxSpent = Math.max(1, ...data.categories.map((c) => c.spent))

  return (
    <div className="budget-widget">
      <div className="budget-summary">
        <span className="budget-total">{money(data.expenses)}</span>
        <span className="muted small">
          spent in {monthTitle(data.month, false)}
          {data.budget_total !== null && <> of {money(data.budget_total)} budgeted</>}
          {change !== null && <> · {change > 0 ? '+' : ''}{change}% vs last month</>}
        </span>
        <span className="small">
          Income {money(data.income)} · <span className={net < 0 ? 'budget-neg' : 'budget-pos'}>net {net < 0 ? '−' : '+'}{money(Math.abs(net))}</span>
        </span>
      </div>

      <ul className="budget-categories">
        {data.categories.map((c) => {
          const ratio = c.budget ? c.spent / c.budget : null
          return (
            <li key={c.category}>
              <div className="budget-row">
                <span className="budget-name">{c.category}</span>
                <span className="muted small budget-value">
                  {money(c.spent)}{c.budget !== null && <> / {money(c.budget)}</>}
                </span>
              </div>
              <span className="bar">
                {ratio !== null ? (
                  <span className={`bar-fill ${ratio > 1 ? 'over' : ratio > 0.85 ? 'progress' : 'done'}`} style={{ width: `${Math.min(ratio, 1) * 100}%` }} />
                ) : (
                  <span className="bar-fill budget-neutral" style={{ width: `${(c.spent / maxSpent) * 100}%` }} />
                )}
              </span>
            </li>
          )
        })}
      </ul>

      <div className="budget-actions">
        <button className="button primary small-button" onClick={() => setAdding(true)}>+ Add</button>
        <button className="button ghost small-button" onClick={openReport}>
          Monthly report{data.more_categories > 0 && ` (+${data.more_categories} more)`} →
        </button>
      </div>

      {adding && (
        <EntryDialog
          title="Add entry"
          initial={{ month: data.month, path: ['Expenses'] }}
          paths={data.paths}
          onSave={async (entry) => { await budgetApi.add(entry); reload() }}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  )
}
