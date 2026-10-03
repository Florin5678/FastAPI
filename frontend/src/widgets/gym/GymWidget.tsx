import { useState, type FormEvent } from 'react'
import { gymApi, localDate, type Workout } from '../../api'
import type { WidgetProps } from '../types'
import './gym.css'

export type GymData = {
  today: string
  week_start: string
  goal_active_days: number // weekly goal: days with at least one workout
  goal_minutes: number
  active_days: number
  workouts_done: number
  minutes_done: number
  days: { day: string; trained: boolean }[]
  weeks: { week_start: string; active_days: number }[]
  streak_weeks: number
  workouts: Workout[]
  kinds: string[]
}

const WEEKDAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

function GoalBar({ label, done, goal, unit }: { label: string; done: number; goal: number; unit: string }) {
  const met = goal > 0 && done >= goal
  return (
    <div className="gym-goal">
      <div className="gym-goal-top">
        <span>{label}</span>
        <span className={met ? 'gym-goal-value met' : 'gym-goal-value'}>
          {done} / {goal} {unit} {met && '✓'}
        </span>
      </div>
      <span className="bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={goal} aria-valuenow={done}>
        <span className={`bar-fill ${met ? 'done' : 'progress'}`} style={{ width: `${goal ? Math.min(100, (done / goal) * 100) : 0}%` }} />
      </span>
    </div>
  )
}

export function GymWidget({ data, reload, actions }: WidgetProps<GymData>) {
  const [logging, setLogging] = useState(false)
  const [kind, setKind] = useState(data.kinds[0])
  const [minutes, setMinutes] = useState('60')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const log = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await gymApi.log({ day: localDate(), kind, minutes: Number(minutes), note: note.trim() || undefined })
      setLogging(false)
      setNote('')
      reload()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    setBusy(true)
    try {
      await gymApi.remove(id)
      reload()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const maxWeek = Math.max(data.goal_active_days, ...data.weeks.map((w) => w.active_days))

  return (
    <div className="gym-widget">
      <button className="link gym-open" onClick={() => actions.goTo('gym')}>Monthly report →</button>
      <div className="gym-head">
        <span className="muted small">
          This week{data.streak_weeks > 0 && <> · 🔥 {data.streak_weeks} week{data.streak_weeks === 1 ? '' : 's'} on target</>}
        </span>
        {!logging && <button className="button primary small-button" onClick={() => setLogging(true)}>+ Log workout</button>}
      </div>

      {logging && (
        <form className="gym-log" onSubmit={log}>
          <div className="chips compact" role="radiogroup" aria-label="Workout type">
            {data.kinds.map((k) => (
              <button key={k} type="button" role="radio" aria-checked={kind === k} className={kind === k ? 'chip active' : 'chip'} onClick={() => setKind(k)}>{k}</button>
            ))}
          </div>
          <div className="gym-log-row">
            <label className="gym-minutes">
              <input type="number" min={1} max={600} value={minutes} onChange={(e) => setMinutes(e.target.value)} aria-label="Minutes" />
              <span className="muted small">min</span>
            </label>
            <input className="gym-note" type="text" maxLength={300} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note" />
          </div>
          <div className="dialog-actions">
            <button type="button" className="button ghost small-button" onClick={() => setLogging(false)}>Cancel</button>
            <button type="submit" className="button primary small-button" disabled={busy || !(Number(minutes) > 0)}>Save</button>
          </div>
        </form>
      )}
      {error && <p className="error-text small">{error}</p>}

      <GoalBar label="Active days" done={data.active_days} goal={data.goal_active_days} unit="" />
      <GoalBar label="Minutes" done={data.minutes_done} goal={data.goal_minutes} unit="min" />

      <div className="gym-week" aria-label="Days trained this week">
        {data.days.map((d, i) => (
          <span
            key={d.day}
            className={['gym-day', d.trained ? 'trained' : '', d.day === data.today ? 'today' : '', d.day > data.today ? 'future' : ''].join(' ')}
            title={`${new Date(d.day + 'T12:00').toLocaleDateString([], { weekday: 'long' })}${d.trained ? ': trained' : ''}`}
          >
            {WEEKDAY_LETTERS[i]}
          </span>
        ))}
      </div>

      <div className="gym-weeks" aria-label="Active days per week, last 8 weeks">
        {data.weeks.map((w, i) => {
          const met = w.active_days >= data.goal_active_days
          return (
            <span key={w.week_start} className="gym-week-col" title={`Week of ${new Date(w.week_start + 'T12:00').toLocaleDateString([], { day: 'numeric', month: 'short' })}: ${w.active_days} active day${w.active_days === 1 ? '' : 's'}`}>
              <span className="gym-week-bar">
                <span className={met ? 'gym-week-fill met' : 'gym-week-fill'} style={{ height: `${(w.active_days / maxWeek) * 100}%` }} />
              </span>
              <span className="gym-week-label">{i === data.weeks.length - 1 ? 'now' : w.active_days}</span>
            </span>
          )
        })}
      </div>

      {data.workouts.length > 0 && (
        <ul className="item-list gym-list">
          {data.workouts.map((w) => (
            <li key={w.id}>
              <span className="item-name">
                {w.kind} · {w.minutes} min
                <span className="muted small"> · {new Date(w.day + 'T12:00').toLocaleDateString([], { weekday: 'short' })}{w.note ? ` · ${w.note}` : ''}</span>
              </span>
              <button className="icon-button" onClick={() => remove(w.id)} disabled={busy} aria-label={`Delete ${w.kind} workout`} title="Delete">✕</button>
            </li>
          ))}
        </ul>
      )}

    </div>
  )
}
