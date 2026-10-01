import { useState } from 'react'
import { budgetApi } from '../../api'
import type { WidgetProps } from '../types'
import { EntryDialog } from './EntryDialog'
import { MonthChart } from './MonthChart'
import { monthTitle } from '../../lib/dates'
import { formatMoney } from './budgetUtils'
import './budget.css'

export type BudgetData = {
  month: string // YYYY-MM
  has_entries: boolean
  currency: string
  income: number
  expenses: number
  history: { month: string; income: number; expenses: number }[] // last 6 months, oldest first
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

  const net = data.income - data.expenses

  return (
    <div className="budget-widget budget-tile">
      <div className="budget-tile-summary">
        <span className="muted small">{monthTitle(data.month, false)}</span>
        <span className="small">
          <span className="budget-dot budget-history-income" />Income <b>{money(data.income)}</b>
          {' · '}
          <span className="budget-dot budget-history-expenses" />Spent <b>{money(data.expenses)}</b>
          {' · '}
          <span className={net < 0 ? 'budget-neg' : 'budget-pos'}>net {net < 0 ? '−' : '+'}{money(Math.abs(net))}</span>
        </span>
      </div>

      <MonthChart history={data.history} current={data.month} lastMonth={data.month} money={money} onPick={openReport} compact />

      <div className="budget-actions">
        <button className="button primary small-button" onClick={() => setAdding(true)}>+ Add</button>
        <button className="button ghost small-button" onClick={openReport}>Monthly report →</button>
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
