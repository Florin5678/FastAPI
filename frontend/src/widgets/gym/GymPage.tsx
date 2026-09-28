import { useEffect, useState } from 'react'
import { gymApi, localDate, type GymMonth } from '../../api'
import './gym.css'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function monthTitle(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString([], { month: 'long', year: 'numeric' })
}

function duration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`
}

// Full view of the Gym widget: a month calendar of workouts plus the month's totals
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
  const maxMinutes = Math.max(1, ...(data?.totals ?? []).map((t) => t.minutes))
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
            <h2>Month totals</h2>
          </div>
          {data.totals.length === 0 ? (
            <div className="empty">No workouts logged in {monthTitle(month)}.</div>
          ) : (
            <ul className="gym-totals card">
              {data.totals.map((t) => (
                <li key={t.kind}>
                  <span className="gym-totals-kind">{t.kind}</span>
                  <span className="bar">
                    <span className="bar-fill done" style={{ width: `${(t.minutes / maxMinutes) * 100}%` }} />
                  </span>
                  <span className="muted small gym-totals-value">
                    {t.sessions}× · {duration(t.minutes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
