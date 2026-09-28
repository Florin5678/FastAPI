import { GoogleSetup, LinkSetup } from '../../components/GoogleSetup'
import type { WidgetProps } from '../types'
import './budget.css'

type Category = { category: string; spent: number; budget: number | null }

export type BudgetData =
  | { needs_setup: 'no_file' | 'bad_link' | 'permission' | 'api_disabled' }
  | {
      needs_setup: null
      title: string | null
      link: string
      month: string // YYYY-MM
      last_month: string
      currency: string
      total: number
      last_month_total: number
      budget_total: number | null
      has_budget_tab: boolean
      categories: Category[]
      skipped_rows: number
    }

function monthName(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString([], { month: 'long' })
}

export function BudgetWidget({ data, updateSettings }: WidgetProps<BudgetData>) {
  if (data.needs_setup === 'permission' || data.needs_setup === 'api_disabled') {
    return <GoogleSetup reason={data.needs_setup} service="Google Sheets" api="sheets.googleapis.com" />
  }
  if (data.needs_setup) {
    return (
      <LinkSetup
        prompt="Paste the link to your budget spreadsheet (one row per transaction, with Date, Amount and Category columns)."
        placeholder="https://docs.google.com/spreadsheets/d/…"
        invalid={data.needs_setup === 'bad_link'}
        onSave={(sheet) => updateSettings({ sheet })}
      />
    )
  }

  const money = (value: number) =>
    `${value.toLocaleString([], { maximumFractionDigits: 0 })}${data.currency ? ` ${data.currency}` : ''}`
  const change = data.last_month_total ? Math.round(((data.total - data.last_month_total) / data.last_month_total) * 100) : null
  const left = data.budget_total !== null ? data.budget_total - data.total : null

  return (
    <div className="budget-widget">
      <div className="budget-summary">
        <span className="budget-total">{money(data.total)}</span>
        <span className="muted small">
          spent in {monthName(data.month)}
          {data.budget_total !== null && <> of {money(data.budget_total)}</>}
        </span>
        {left !== null && (
          <span className={left < 0 ? 'budget-left over' : 'budget-left'}>
            {left < 0 ? `${money(-left)} over budget` : `${money(left)} left`}
          </span>
        )}
        <span className="muted small">
          {monthName(data.last_month)}: {money(data.last_month_total)}
          {change !== null && <> · {change > 0 ? '+' : ''}{change}% so far</>}
        </span>
      </div>

      {data.categories.length === 0 ? (
        <p className="muted small">No spending yet this month.</p>
      ) : (
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

      <div className="budget-foot muted small">
        {!data.has_budget_tab && <span>No budget tab found, so only spending is shown. </span>}
        {data.skipped_rows > 0 && <span>{data.skipped_rows} row{data.skipped_rows === 1 ? '' : 's'} skipped (no date or amount). </span>}
        <a href={data.link} target="_blank" rel="noopener noreferrer">Open sheet ↗</a>
      </div>
    </div>
  )
}
