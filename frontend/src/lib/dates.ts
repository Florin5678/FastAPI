// Local-date helpers (the backend keys days by the viewer's local date)

export function localMidnightIso(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString() // UTC instant of the viewer's local midnight
}

// YYYY-MM-DD in the browser's timezone (optionally shifted by whole days)
export function localDate(d: Date = new Date(), shiftDays = 0): string {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate() + shiftDays)
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
}

export function shiftDay(day: string, days: number): string {
  const [y, m, d] = day.split('-').map(Number)
  return localDate(new Date(y, m - 1, d), days)
}

// "Today" / "Yesterday" / weekday name for a YYYY-MM-DD day
export function dayTitle(day: string): string {
  const today = localDate()
  if (day === today) return 'Today'
  if (day === shiftDay(today, -1)) return 'Yesterday'
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'long' })
}

// "1 October 2026"
export function longDate(day: string): string {
  return new Date(day + 'T12:00').toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' })
}

// "Thu, 1 Oct"
export function shortDate(day: string): string {
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}

// "October 2026" (or "October") for a YYYY-MM month
export function monthTitle(month: string, withYear = true): string {
  const [y, m] = month.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString([], withYear ? { month: 'long', year: 'numeric' } : { month: 'long' })
}

// YYYY-MM moved by `delta` months
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}
