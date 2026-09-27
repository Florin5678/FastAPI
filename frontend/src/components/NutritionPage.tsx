import { useCallback, useEffect, useState } from 'react'
import {
  localDate, nutritionApi, shiftDay,
  type NutrientRow, type NutritionDayData, type NutritionHistory,
} from '../api'
import { AddFoodDialog } from '../widgets/AddFoodDialog'
import { barState, fmt, FoodLog, NutrientBars } from '../widgets/NutritionParts'

const RANGES = [7, 14, 30, 90]

function dayTitle(day: string): string {
  const today = localDate()
  if (day === today) return 'Today'
  if (day === shiftDay(today, -1)) return 'Yesterday'
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'long' })
}

function longDate(day: string): string {
  return new Date(day + 'T12:00').toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' })
}

function shortDate(day: string): string {
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}

// Full view of the Nutrition widget: any day's intake + food log, and a history table
export function NutritionPage() {
  const today = localDate()
  const [day, setDay] = useState(today)
  const [data, setData] = useState<NutritionDayData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<number | null>(null)

  const [range, setRange] = useState(14)
  const [history, setHistory] = useState<NutritionHistory | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)

  const loadDay = useCallback(() => {
    setError(null)
    nutritionApi.getDay(day).then(setData).catch((err) => setError(err.message))
  }, [day])

  const loadHistory = useCallback(() => {
    setHistoryError(null)
    nutritionApi.history(today, range).then(setHistory).catch((err) => setHistoryError(err.message))
  }, [today, range])

  useEffect(loadDay, [loadDay])
  useEffect(loadHistory, [loadHistory])

  const changed = () => {
    loadDay()
    loadHistory()
  }

  const remove = async (id: number) => {
    setRemoving(id)
    try {
      await nutritionApi.deleteEntry(id)
      changed()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setRemoving(null)
    }
  }

  const goTo = (next: string) => {
    if (next > today) return
    setData(null)
    setDay(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <section className="nutrition-page">
      <div className="section-head">
        <h2>Nutrition</h2>
      </div>

      <div className="day-nav">
        <button className="button" onClick={() => goTo(shiftDay(day, -1))} aria-label="Previous day">‹</button>
        <div className="day-nav-label">
          <strong>{dayTitle(day)}</strong>
          <span className="muted small">{longDate(day)}</span>
        </div>
        <button className="button" onClick={() => goTo(shiftDay(day, 1))} disabled={day >= today} aria-label="Next day">›</button>
        <input
          type="date"
          className="day-picker"
          value={day}
          max={today}
          onChange={(e) => e.target.value && goTo(e.target.value)}
          aria-label="Pick a day"
        />
        {day !== today && <button className="button ghost" onClick={() => goTo(today)}>Today</button>}
      </div>

      <div className="nutrition-day card">
        {error && <p className="error-text">{error}</p>}
        {!data && !error && <p className="muted">Loading…</p>}
        {data && (
          <>
            <div className="nutrition-day-head">
              <h3>Intake</h3>
              <button className="button primary small-button" onClick={() => setAdding(true)}>+ Add food</button>
            </div>
            <NutrientBars nutrients={data.nutrients} />
            <h3>Food ({data.entries.length})</h3>
            {data.entries.length === 0
              ? <p className="muted small">Nothing logged {day === today ? 'yet today' : 'on this day'}.</p>
              : <FoodLog entries={data.entries} removing={removing} onRemove={remove} />}
          </>
        )}
      </div>

      <div className="section-head history-head">
        <h2>History</h2>
        <div className="segmented" role="group" aria-label="Range">
          {RANGES.map((r) => (
            <button key={r} className={range === r ? 'active' : ''} onClick={() => setRange(r)}>{r} days</button>
          ))}
        </div>
      </div>

      {historyError && <p className="error-text">{historyError}</p>}
      {history && <HistoryTable history={history} selected={day} onPick={goTo} />}

      {adding && data && (
        <AddFoodDialog
          day={day}
          personalKey={data.personal_food_key}
          onAdded={() => { setAdding(false); changed() }}
          onClose={() => setAdding(false)}
        />
      )}
    </section>
  )
}

function Cell({ n }: { n: NutrientRow }) {
  const tone = barState(n).tone
  const cls = tone === 'done' ? 'met' : tone === 'over' ? 'over' : ''
  return <td className={cls} title={`${fmt(n.actual)} / ${fmt(n.goal)} ${n.unit}`}>{fmt(n.actual)}</td>
}

function HistoryTable({ history, selected, onPick }: { history: NutritionHistory; selected: string; onPick: (day: string) => void }) {
  const columns = history.days[0]?.nutrients ?? []
  const logged = history.days.filter((d) => d.entries > 0)

  if (logged.length === 0) {
    return <div className="empty">No food logged in this period yet.</div>
  }

  // Averages over logged days only (a day you didn't log isn't a day you ate nothing)
  const averages = columns.map((c, i) => ({
    ...c,
    actual: logged.reduce((sum, d) => sum + d.nutrients[i].actual, 0) / logged.length,
    goal: logged.reduce((sum, d) => sum + d.nutrients[i].goal, 0) / logged.length,
  }))

  return (
    <div className="table-scroll">
      <table className="history-table">
        <thead>
          <tr>
            <th scope="col">Day</th>
            {columns.map((c) => (
              <th key={c.key} scope="col">
                {c.label}
                <span className="unit">{c.kind === 'limit' ? `max ${c.unit}` : c.unit}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="averages">
            <th scope="row">Average <span className="unit">{logged.length} logged day{logged.length === 1 ? '' : 's'}</span></th>
            {averages.map((n) => <Cell key={n.key} n={n} />)}
          </tr>
          {history.days.map((d) => (
            <tr
              key={d.day}
              className={[d.day === selected ? 'selected' : '', d.entries === 0 ? 'empty-day' : ''].join(' ')}
              onClick={() => onPick(d.day)}
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && onPick(d.day)}
            >
              <th scope="row">{shortDate(d.day)}</th>
              {d.entries === 0
                ? columns.map((c) => <td key={c.key} className="none">–</td>)
                : d.nutrients.map((n) => <Cell key={n.key} n={n} />)}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Green = goal reached, red = over a limit. Click a day to open it.</p>
    </div>
  )
}
