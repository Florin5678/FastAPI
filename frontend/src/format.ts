// "Jane Doe <jane@x.com>" -> "Jane Doe"; bare addresses are kept as-is
export function senderName(sender: string | null): string {
  if (!sender) return 'Unknown sender'
  const match = sender.match(/^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$/)
  return match ? match[1] : sender
}

export function formatTime(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const sameYear = date.getFullYear() === now.getFullYear()
  return date.toLocaleDateString([], sameYear ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatFullDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

export const CATEGORIES = [
  'personal', 'work', 'school', 'finance', 'shopping',
  'travel', 'social', 'newsletter', 'promotion', 'notification', 'other',
] as const

export function categoryLabel(category: string | null): string {
  if (!category || category === 'unsummarized') return 'Not summarized'
  return category.charAt(0).toUpperCase() + category.slice(1)
}

// "just now", "12 min ago", "3 h ago", "yesterday", "12 Sep"
export function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  if (hours < 48) return 'yesterday'
  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' })
}
