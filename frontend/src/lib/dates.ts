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
