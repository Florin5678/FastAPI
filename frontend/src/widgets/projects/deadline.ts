// "Overdue · 18 Oct" / "Today" / "Tomorrow" / "Fri 24 Oct", counted from the widget's local today
export function deadlineLabel(deadline: string | null, today: string): { text: string; tone: string } | null {
  if (!deadline) return null
  const day = new Date(deadline + 'T12:00')
  const days = Math.round((day.getTime() - new Date(today + 'T12:00').getTime()) / 86400000)
  const short = day.toLocaleDateString([], { day: 'numeric', month: 'short' })
  if (days < 0) return { text: `Overdue · ${short}`, tone: 'overdue' }
  if (days === 0) return { text: 'Today', tone: 'today' }
  if (days === 1) return { text: 'Tomorrow', tone: 'soon' }
  if (days < 7) return { text: day.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }), tone: 'soon' }
  return { text: day.getFullYear() === new Date(today + 'T12:00').getFullYear() ? short : day.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }), tone: 'later' }
}
