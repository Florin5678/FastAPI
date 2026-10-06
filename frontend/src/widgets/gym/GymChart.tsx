import { useEffect, useState } from 'react'
import { gymApi, localDate, type GymStats, type GymStatsLevel } from '../../api'
import { seriesSlot } from './colors'
import { duration } from '../../lib/format'

// Minutes per workout type for a week, month or year, as a pie (each type's share) or
// columns (minutes per type, types on the x axis). Level and chart type
// are remembered in this browser. Each type keeps one colour (its place in the routine
// list -> the validated categorical palette in gym.css), so colours never shift.
const STORE_KEY = 'gym-chart'
type View = 'pie' | 'columns'
type Prefs = { level: GymStatsLevel; view: View }

function savedPrefs(): Prefs {
  try {
    const p = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') as Partial<Prefs>
    return {
      level: p.level === 'week' || p.level === 'year' ? p.level : 'month',
      view: p.view === 'columns' ? 'columns' : 'pie',
    }
  } catch {
    return { level: 'month', view: 'pie' }
  }
}

// Move the anchor day one period back or forward
function shift(anchor: string, level: GymStatsLevel, delta: number): string {
  const d = new Date(anchor + 'T12:00')
  if (level === 'week') d.setDate(d.getDate() + 7 * delta)
  else if (level === 'month') d.setMonth(d.getMonth() + delta, 1)
  else d.setFullYear(d.getFullYear() + delta, 0, 1)
  return localDate(d)
}

export function GymChart() {
  const today = localDate()
  const [prefs, setPrefs] = useState<Prefs>(savedPrefs)
  const [anchor, setAnchor] = useState(today)
  const [result, setResult] = useState<{ key: string; data?: GymStats; error?: string } | null>(null)
  const key = `${prefs.level}:${anchor}`

  useEffect(() => {
    let cancelled = false
    gymApi.stats(prefs.level, anchor)
      .then((data) => { if (!cancelled) setResult({ key, data }) })
      .catch((err) => { if (!cancelled) setResult({ key, error: (err as Error).message }) })
    return () => { cancelled = true }
  }, [prefs.level, anchor, key])

  const update = (changes: Partial<Prefs>) => {
    const next = { ...prefs, ...changes }
    setPrefs(next)
    try { localStorage.setItem(STORE_KEY, JSON.stringify(next)) } catch { /* not remembered */ }
  }

  const current = result?.key === key ? result : null
  const data = current?.data
  const atLatest = data ? data.end >= today : false
  const total = data ? data.totals.reduce((s, t) => s + t.minutes, 0) : 0
  const sessions = data ? data.totals.reduce((s, t) => s + t.sessions, 0) : 0
  // Colour slot by the type's place in the routine list (unknown types after it)
  const slot = (kind: string) => seriesSlot(kind, data?.kinds ?? [])

  return (
    <div className="card gym-chart">
      <div className="gym-chart-controls">
        <div className="segmented" role="radiogroup" aria-label="Period">
          {(['week', 'month', 'year'] as const).map((l) => (
            <button key={l} type="button" role="radio" aria-checked={prefs.level === l} className={prefs.level === l ? 'active' : ''}
              onClick={() => { update({ level: l }); setAnchor(today) }}>
              {l[0].toUpperCase() + l.slice(1)}
            </button>
          ))}
        </div>
        <div className="gym-chart-nav">
          <button type="button" className="icon-button" onClick={() => setAnchor(shift(anchor, prefs.level, -1))} aria-label={`Previous ${prefs.level}`}>‹</button>
          <span className="gym-chart-label">{data?.label ?? '…'}</span>
          <button type="button" className="icon-button" onClick={() => setAnchor(shift(anchor, prefs.level, 1))} disabled={atLatest} aria-label={`Next ${prefs.level}`}>›</button>
        </div>
        <div className="segmented" role="radiogroup" aria-label="Chart type">
          <button type="button" role="radio" aria-checked={prefs.view === 'pie'} className={prefs.view === 'pie' ? 'active' : ''} onClick={() => update({ view: 'pie' })}>Pie</button>
          <button type="button" role="radio" aria-checked={prefs.view === 'columns'} className={prefs.view === 'columns' ? 'active' : ''} onClick={() => update({ view: 'columns' })}>Columns</button>
        </div>
      </div>

      {current?.error && <p className="error-text small">{current.error}</p>}
      {!current && <p className="muted small">Loading…</p>}
      {data && total === 0 && <div className="empty">No workouts logged in this {prefs.level}.</div>}
      {data && total > 0 && (
        <>
          <p className="muted small gym-chart-summary">
            {duration(total)} · {sessions} workout{sessions === 1 ? '' : 's'} · {data.active_days} active day{data.active_days === 1 ? '' : 's'}
          </p>
          <div className={prefs.view === 'pie' ? 'gym-chart-body pie' : 'gym-chart-body'}>
            {prefs.view === 'pie' ? <Pie data={data} total={total} slot={slot} /> : <Columns data={data} total={total} slot={slot} />}
            <ul className="gym-legend">
              {data.totals.map((t) => (
                <li key={t.kind}>
                  <span className={`gym-swatch gym-series-${slot(t.kind)}`} aria-hidden />
                  <span className="gym-legend-kind">{t.kind}</span>
                  <span className="muted small gym-totals-value">{t.sessions}× · {duration(t.minutes)} · {Math.round((t.minutes / total) * 100)}%</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  )
}

type Slot = (kind: string) => number

function Pie({ data, total, slot }: { data: GymStats; total: number; slot: Slot }) {
  const size = 180
  const r = 70
  const circumference = 2 * Math.PI * r
  const gap = data.totals.length > 1 ? 2 : 0 // 2px surface gap between slices
  // Where each slice starts along the ring
  const starts = data.totals.map((_, i) => data.totals.slice(0, i).reduce((s, t) => s + (t.minutes / total) * circumference, 0))
  return (
    <svg className="gym-pie" viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label="Share of minutes per workout type">
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        {data.totals.map((t, i) => (
          <circle key={t.kind} cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={34}
            className={`gym-series-${slot(t.kind)}`}
            strokeDasharray={`${Math.max((t.minutes / total) * circumference - gap, 0.5)} ${circumference}`} strokeDashoffset={-starts[i]}>
            <title>{`${t.kind}: ${duration(t.minutes)} (${Math.round((t.minutes / total) * 100)}%), ${t.sessions}×`}</title>
          </circle>
        ))}
      </g>
      <text x="50%" y="51%" textAnchor="middle" dominantBaseline="middle" className="gym-pie-total">{duration(total)}</text>
    </svg>
  )
}

function Columns({ data, total, slot }: { data: GymStats; total: number; slot: Slot }) {
  // One column per workout type done in the period (types with no time are left out)
  const shown = data.totals.filter((t) => t.minutes > 0)
  const max = Math.max(1, ...shown.map((t) => t.minutes))
  return (
    <div className="gym-columns" role="img" aria-label="Minutes per workout type">
      {shown.map((t) => (
        <div key={t.kind} className="gym-column"
          title={`${t.kind}: ${duration(t.minutes)} (${Math.round((t.minutes / total) * 100)}%), ${t.sessions}×`}>
          <span className="gym-column-track">
            <span className="gym-column-stack" style={{ height: `${(t.minutes / max) * 100}%` }}>
              <span className={`gym-column-seg gym-series-${slot(t.kind)}`} style={{ flexGrow: 1 }} />
              <span className="gym-column-value">{duration(t.minutes)}</span>
            </span>
          </span>
          <span className="gym-column-label">{t.kind}</span>
        </div>
      ))}
    </div>
  )
}
