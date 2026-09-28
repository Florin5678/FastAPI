import { monthTitle } from './budgetUtils'

type MonthTotals = { month: string; income: number; expenses: number }

// Income vs spending per month as paired columns (the report page and the dashboard tile)
export function MonthChart({ history, current, lastMonth, money, onPick, compact = false }: {
  history: MonthTotals[]
  current: string // highlighted month (YYYY-MM)
  lastMonth: string // months after this can't be picked
  money: (value: number) => string
  onPick: (month: string) => void
  compact?: boolean
}) {
  const max = Math.max(1, ...history.flatMap((h) => [h.income, h.expenses]))
  return (
    <div className={compact ? 'budget-history compact' : 'budget-history'}>
      {history.map((h) => (
        <button key={h.month} className={h.month === current ? 'current' : ''} onClick={() => onPick(h.month)}
          disabled={h.month > lastMonth} title={`${monthTitle(h.month)}: income ${money(h.income)}, spent ${money(h.expenses)}`}>
          <span className="budget-history-bars">
            <span className="budget-history-income" style={{ height: `${(h.income / max) * 100}%` }} />
            <span className="budget-history-expenses" style={{ height: `${(h.expenses / max) * 100}%` }} />
          </span>
          <span className="budget-history-label">
            {new Date(h.month + '-01T12:00').toLocaleDateString([], { month: 'short' })}
          </span>
        </button>
      ))}
    </div>
  )
}
