import { useEffect, useState } from 'react'
import { gymApi, localDate, type GymMonth } from '../../api'
import { GymChart } from './GymChart'
import './gym.css'
import { monthTitle, shiftMonth } from '../../lib/dates'
import { duration } from '../../lib/format'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Full view of the Gym widget: a month calendar of workouts plus weekly totals vs the goals
export function GymPage() {
  const today = localDate()
  const thisMonth = today.slice(0, 7)
  const [month, setMonth] = useState(thisMonth)
  const [report, setReport] = useState<{ month: string; data?: GymMonth; error?: string } | null>(null)
  const [selected, setSelected] = useState<string | null>(null) // tapped day, shown under the calendar

  useEffect(() => {
    let cancelled = false
    gymApi.month(month)
      .then((data) => { if (!cancelled) setReport({ month, data }) })
      .catch((err) => { if (!cancelled) setReport({ month, error: (err as Error).message }) })
    return () => { cancelled = true }
  }, [month])

  const current = report?.month === month ? report : null
  const data = current?.data
  const [y, m] = month.split('-').map(Number)
  const daysInMonth = new Date(y, m, 0).getDate()
  const leadingBlanks = (new Date(y, m - 1, 1).getDay() + 6) % 7 // weeks start on Monday
  const canGoBack = !data?.first_month || month > data.first_month

  return (
    <section className="gym-page">
      <div className="section-head">
        <h2>Gym</h2>
      </div>

      <div className="day-nav">
        <button className="button" onClick={() => setMonth(shiftMonth(month, -1))} disabled={!canGoBack} aria-label="Previous month">‹</button>
        <div className="day-nav-label">
          <strong>{monthTitle(month)}</strong>
          {data && (
            <span className="muted small">
              {data.sessions} workout{data.sessions === 1 ? '' : 's'} · {data.days_trained} day{data.days_trained === 1 ? '' : 's'} · {duration(data.minutes)}
            </span>
          )}
        </div>
        <button className="button" onClick={() => setMonth(shiftMonth(month, 1))} disabled={month >= thisMonth} aria-label="Next month">›</button>
        {month !== thisMonth && <button className="button ghost" onClick={() => setMonth(thisMonth)}>This month</button>}
      </div>

      {current?.error && <p className="error-text">{current.error}</p>}
      {!current && <p className="muted">Loading…</p>}

      {data && (
        <>
          <div className="gym-month card" role="grid" aria-label={`Workouts in ${monthTitle(month)}`}>
            {WEEKDAYS.map((d) => <span key={d} className="gym-month-weekday" aria-hidden>{d}</span>)}
            {Array.from({ length: leadingBlanks }, (_, i) => <span key={`b${i}`} />)}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const day = `${month}-${String(i + 1).padStart(2, '0')}`
              const workouts = data.days[day] ?? []
              return (
                <button
                  key={day}
                  type="button"
                  className={['gym-month-day', workouts.length ? 'trained' : '', day === today ? 'today' : '', day > today ? 'future' : '', day === selected ? 'selected' : ''].join(' ')}
                  title={workouts.map((w) => `${w.kind} ${duration(w.minutes)}${w.note ? ` (${w.note})` : ''}`).join(', ') || undefined}
                  disabled={!workouts.length}
                  onClick={() => setSelected(day === selected ? null : day)}
                >
                  <span className="gym-month-num">{i + 1}</span>
                  {workouts.map((w) => (
                    <span key={w.id} className="gym-month-entry">{w.kind}<span className="gym-month-time"> · {duration(w.minutes)}</span></span>
                  ))}
                </button>
              )
            })}
          </div>

          {selected?.startsWith(month) && data.days[selected] && (
            <div className="card gym-day-detail">
              <strong>{new Date(selected + 'T12:00').toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })}</strong>
              <ul className="item-list">
                {data.days[selected].map((w) => (
                  <li key={w.id}>
                    <span className="item-name">
                      {w.kind} · {duration(w.minutes)}
                      {w.note && <span className="muted small"> · {w.note}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="section-head history-head">
            <h2>Weekly totals</h2>
            <span className="muted small">Goal: {data.goal_active_days} active days · {duration(data.goal_minutes)} a week</span>
          </div>
          <ul className="gym-weekly card">
            {data.weeks.map((w) => {
              const startDay = new Date(w.week_start + 'T12:00')
              const endDay = new Date(startDay.getTime() + 6 * 86400000)
              const range = `${startDay.toLocaleDateString([], { day: 'numeric', month: 'short' })} – ${endDay.toLocaleDateString([], { day: 'numeric', month: 'short' })}`
              const isCurrent = w.week_start <= today && today < localDate(new Date(endDay.getTime() + 86400000))
              const future = w.week_start > today
              const met = w.active_days >= data.goal_active_days && w.minutes >= data.goal_minutes
              const ratio = data.goal_minutes ? w.minutes / data.goal_minutes : w.active_days / Math.max(1, data.goal_active_days)
              const kinds = Object.entries(w.kinds).sort((a, b) => b[1] - a[1]).map(([k, n]) => (n > 1 ? `${k} ×${n}` : k)).join(', ')
              return (
                <li key={w.week_start} className={future ? 'muted' : ''}>
                  <span className="gym-weekly-label">
                    <span><strong>Week {w.week}</strong>{isCurrent && <span className="gym-weekly-now"> · this week</span>}</span>
                    <span className="muted small">{range}</span>
                  </span>
                  <span className="bar">
                    <span className={`bar-fill ${met ? 'done' : 'progress'}`} style={{ width: `${Math.min(ratio, 1) * 100}%` }} />
                  </span>
                  <span className="small gym-totals-value">
                    {w.active_days}/{data.goal_active_days} active days · {w.sessions} workout{w.sessions === 1 ? '' : 's'} · {duration(w.minutes)}{met && ' ✓'}
                  </span>
                  {kinds && <span className="muted small gym-weekly-kinds">{kinds}</span>}
                </li>
              )
            })}
          </ul>

          <div className="section-head history-head">
            <h2>Totals by type</h2>
          </div>
          <GymChart />
        </>
      )}
    </section>
  )
}
