import type { MoodMonth } from '../../api'
import { monthTitle, shortDate } from '../../lib/dates'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// One card per month: a calendar placing each day's mood (when moods cluster), and
// a bar per emoji sized by how often it was used (the month's mood mix).
export function MoodMonths({ months, today, onPickDay }: { months: MoodMonth[]; today: string; onPickDay: (day: string) => void }) {
  // Months come newest first; drop the empty ones from before the first entry
  // (the current month always stays, so there's somewhere to start)
  let oldestWithEntries = 0
  months.forEach((m, i) => { if (m.entries > 0) oldestWithEntries = i })
  const shown = months.slice(0, oldestWithEntries + 1)

  return (
    <div className="mood-months">
      {shown.map((m) => <MonthCard key={m.month} month={m} today={today} onPickDay={onPickDay} />)}
    </div>
  )
}

function MonthCard({ month, today, onPickDay }: { month: MoodMonth; today: string; onPickDay: (day: string) => void }) {
  const [y, m] = month.month.split('-').map(Number)
  const daysInMonth = new Date(y, m, 0).getDate()
  const leadingBlanks = (new Date(y, m - 1, 1).getDay() + 6) % 7 // weeks start on Monday
  const max = Math.max(1, ...month.moods.map((x) => x.count))
  const moodTotal = month.moods.reduce((sum, x) => sum + x.count, 0)

  return (
    <article className="mood-month card">
      <div className="mood-month-head">
        <strong>{monthTitle(month.month)}</strong>
        <span className="muted small">
          {month.entries} entr{month.entries === 1 ? 'y' : 'ies'} · {month.days_logged} day{month.days_logged === 1 ? '' : 's'}
        </span>
      </div>

      <div className="mood-calendar" role="grid" aria-label={`Moods in ${monthTitle(month.month)}`}>
        {WEEKDAYS.map((d) => <span key={d} className="cal-weekday" aria-hidden>{d[0]}</span>)}
        {Array.from({ length: leadingBlanks }, (_, i) => <span key={`b${i}`} className="cal-blank" />)}
        {Array.from({ length: daysInMonth }, (_, i) => {
          const day = `${month.month}-${String(i + 1).padStart(2, '0')}`
          const moods = month.days[day]
          const future = day > today
          const label = moods
            ? `${shortDate(day)}: ${moods.length ? moods.join(' ') : 'entry without a mood'}`
            : `${shortDate(day)}: no entry`
          return (
            <button
              key={day}
              className={['cal-day', moods ? 'has-entry' : '', day === today ? 'is-today' : ''].join(' ')}
              title={label}
              aria-label={label}
              disabled={!moods || future}
              onClick={() => onPickDay(day)}
            >
              {moods && moods.length > 0 && <span className="cal-mood">{moods[0]}</span>}
              {moods && moods.length > 1 && <span className="cal-more">+{moods.length - 1}</span>}
              {moods && moods.length === 0 && <span className="cal-dot" />}
              {!moods && <span className="cal-num">{i + 1}</span>}
            </button>
          )
        })}
      </div>

      {month.moods.length === 0 ? (
        <p className="muted small">{month.entries ? 'No moods picked this month.' : 'No entries this month.'}</p>
      ) : (
        <ul className="mood-bars" aria-label="How often each mood was picked">
          {month.moods.map((x) => (
            <li key={x.emoji} title={`${x.emoji} ${x.count} time${x.count === 1 ? '' : 's'} (${Math.round((x.count / moodTotal) * 100)}%)`}>
              <span className="mood-bar-emoji">{x.emoji}</span>
              <span className="mood-bar-track">
                <span className="mood-bar-fill" style={{ width: `${(x.count / max) * 100}%` }} />
              </span>
              <span className="mood-bar-count">{x.count}</span>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}
