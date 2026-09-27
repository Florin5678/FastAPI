import { localDate, shiftDay } from '../../api'
import type { WidgetProps } from '../types'
import './calendar.css'

type CalendarEvent = {
  id: string
  title: string
  all_day: boolean
  start: string // all-day: YYYY-MM-DD; timed: ISO with offset
  end: string
  location: string | null
  link: string | null
  calendar: string | null
  color: string | null
}

export type CalendarData = {
  needs_setup: 'permission' | 'api_disabled' | null
  days: number
  today?: string
  calendars?: number
  events: CalendarEvent[]
}

const CLOUD_CONSOLE_CALENDAR_API =
  'https://console.cloud.google.com/apis/library/calendar-json.googleapis.com?project=660269344051'

function eventDay(e: CalendarEvent): string {
  return e.all_day ? e.start : localDate(new Date(e.start))
}

function dayHeading(day: string): string {
  const today = localDate()
  if (day === today) return 'Today'
  if (day === shiftDay(today, 1)) return 'Tomorrow'
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })
}

function timeRange(e: CalendarEvent): string {
  if (e.all_day) return 'All day'
  const fmt = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return `${fmt(e.start)}–${fmt(e.end)}`
}

export function CalendarWidget({ data }: WidgetProps<CalendarData>) {
  if (data.needs_setup === 'permission') {
    return (
      <div className="calendar-setup">
        <p>Allow the dashboard to read your Google Calendar (read-only).</p>
        <a className="button primary" href="/auth/google/login">Connect Google Calendar</a>
        <p className="muted small">You'll sign in with Google once more and tick the Calendar permission.</p>
      </div>
    )
  }
  if (data.needs_setup === 'api_disabled') {
    return (
      <div className="calendar-setup">
        <p>The Google Calendar API is switched off for this app's Google Cloud project.</p>
        <a className="button primary" href={CLOUD_CONSOLE_CALENDAR_API} target="_blank" rel="noopener noreferrer">Turn it on (one time)</a>
        <p className="muted small">Click <b>Enable</b> on that page, wait a minute, then refresh this widget.</p>
      </div>
    )
  }

  // Group by local day (events arrive sorted, all-day first within a day)
  const groups: { day: string; events: CalendarEvent[] }[] = []
  for (const e of data.events) {
    const day = eventDay(e)
    const last = groups[groups.length - 1]
    if (last && last.day === day) last.events.push(e)
    else groups.push({ day, events: [e] })
  }

  if (groups.length === 0) {
    return <p className="muted calendar-empty">Nothing in the next {data.days} day{data.days === 1 ? '' : 's'} 🎉</p>
  }

  return (
    <div className="calendar-widget">
      {groups.map((g) => (
        <section key={g.day} className="calendar-day">
          <h4 className={g.day === localDate() ? 'today' : ''}>{dayHeading(g.day)}</h4>
          <ul>
            {g.events.map((e) => (
              <li key={`${e.id}-${e.start}`}>
                <a className="calendar-event" href={e.link ?? undefined} target="_blank" rel="noopener noreferrer" title={e.calendar ?? undefined}>
                  <span className="event-dot" style={{ background: e.color ?? 'var(--accent)' }} aria-hidden />
                  <span className="event-text">
                    <span className="event-title">{e.title}</span>
                    <span className="event-meta">
                      <span className="event-time">{timeRange(e)}</span>
                      {e.location && <span className="event-location"> · {e.location}</span>}
                    </span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
