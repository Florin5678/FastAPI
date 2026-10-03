import { useState, type FormEvent } from 'react'
import { localDate, weightApi, type WeightEntry } from '../../api'
import type { WidgetProps } from '../types'
import './weight.css'

export type WeightData = {
  today: string
  latest: WeightEntry | null
  change_week: { kg: number; since: string } | null // vs the newest entry at least 7 days older
  change_month: { kg: number; since: string } | null // ... at least 30 days older
  goal_kg: number | null
  to_goal: number | null
  days_since_last: number | null
  chart: WeightEntry[] // last 3 months, oldest first
  recent: WeightEntry[] // newest first
}

const signed = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(v).toFixed(1)} kg`
const shortDay = (day: string) => new Date(day + 'T12:00').toLocaleDateString([], { day: 'numeric', month: 'short' })

export function WeightWidget({ data, reload }: WidgetProps<WeightData>) {
  const [kg, setKg] = useState('')
  const [day, setDay] = useState(localDate())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      reload()
      return true
    } catch (err) {
      setError((err as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const value = Number(kg.replace(',', '.'))
  const log = async (e: FormEvent) => {
    e.preventDefault()
    if (await run(() => weightApi.log(day, value))) {
      setKg('')
      setDay(localDate())
    }
  }

  return (
    <div className="weight-widget">
      {data.latest ? (
        <div className="weight-summary">
          <span className="weight-latest">{data.latest.kg.toFixed(1)} <small>kg</small></span>
          <span className="muted small">
            {data.days_since_last === 0 ? 'today' : `${shortDay(data.latest.day)}`}
            {(data.change_month ?? data.change_week) && (() => {
              const c = (data.change_month ?? data.change_week)!
              return <> · {signed(c.kg)} since {shortDay(c.since)}</>
            })()}
          </span>
          {data.goal_kg && data.to_goal !== null && (
            <span className="small weight-goal">
              Goal {data.goal_kg} kg · {Math.abs(data.to_goal) < 0.05 ? 'reached 🎉' : `${signed(data.to_goal)} to go`}
            </span>
          )}
        </div>
      ) : (
        <p className="muted small">Log your weight now and then (e.g. twice a week, same time of day) to see the trend.</p>
      )}

      <WeightChart points={data.chart} goal={data.goal_kg} />

      <form className="weight-log" onSubmit={log}>
        <input type="text" inputMode="decimal" placeholder="kg" value={kg} onChange={(e) => setKg(e.target.value)} aria-label="Weight in kg" />
        <input type="date" value={day} max={data.today} onChange={(e) => setDay(e.target.value || localDate())} aria-label="Day" />
        <button type="submit" className="button primary small-button" disabled={busy || !(value > 20 && value < 400)}>Log</button>
      </form>
      {error && <p className="error-text small">{error}</p>}

      {data.recent.length > 0 && (
        <ul className="weight-recent">
          {data.recent.map((e) => (
            <li key={e.day}>
              <span className="muted small">{shortDay(e.day)}</span>
              <span className="small">{e.kg.toFixed(1)} kg</span>
              <button className="icon-button" disabled={busy} onClick={() => run(() => weightApi.remove(e.day))}
                aria-label={`Remove ${e.kg} kg on ${shortDay(e.day)}`} title="Remove">✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// One series (weight over the last 3 months): 2px line, dots with a hover tooltip, and the
// goal as a dashed reference line. Time on the x axis is proportional to the dates.
function WeightChart({ points, goal }: { points: WeightEntry[]; goal: number | null }) {
  if (points.length < 2) return null
  const width = 300
  const height = 110
  const pad = { top: 10, right: 8, bottom: 16, left: 30 }
  const values = points.map((p) => p.kg).concat(goal ? [goal] : [])
  const lo = Math.floor(Math.min(...values) - 0.5)
  const hi = Math.ceil(Math.max(...values) + 0.5)
  const t0 = new Date(points[0].day).getTime()
  const t1 = new Date(points[points.length - 1].day).getTime()
  const x = (day: string) => pad.left + ((new Date(day).getTime() - t0) / Math.max(t1 - t0, 1)) * (width - pad.left - pad.right)
  const y = (kg: number) => pad.top + (1 - (kg - lo) / (hi - lo)) * (height - pad.top - pad.bottom)
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.day).toFixed(1)},${y(p.kg).toFixed(1)}`).join(' ')
  return (
    <svg className="weight-chart" viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={`Weight from ${points[0].kg} kg on ${shortDay(points[0].day)} to ${points[points.length - 1].kg} kg on ${shortDay(points[points.length - 1].day)}`}>
      {[lo, hi].map((v) => (
        <g key={v}>
          <line x1={pad.left} x2={width - pad.right} y1={y(v)} y2={y(v)} className="weight-grid" />
          <text x={pad.left - 4} y={y(v) + 3} textAnchor="end" className="weight-axis">{v}</text>
        </g>
      ))}
      {goal && goal >= lo && goal <= hi && (
        <g>
          <line x1={pad.left} x2={width - pad.right} y1={y(goal)} y2={y(goal)} className="weight-goal-line" />
          <text x={width - pad.right} y={y(goal) - 3} textAnchor="end" className="weight-axis">goal</text>
        </g>
      )}
      <path d={line} className="weight-line" />
      {points.map((p) => (
        <circle key={p.day} cx={x(p.day)} cy={y(p.kg)} r={3.5} className="weight-dot">
          <title>{`${shortDay(p.day)}: ${p.kg.toFixed(1)} kg`}</title>
        </circle>
      ))}
      <text x={pad.left} y={height - 3} className="weight-axis">{shortDay(points[0].day)}</text>
      <text x={width - pad.right} y={height - 3} textAnchor="end" className="weight-axis">{shortDay(points[points.length - 1].day)}</text>
    </svg>
  )
}
