import type { Repeat } from '../../api'

// 1 -> "1st", 22 -> "22nd", 13 -> "13th"
export function ordinal(n: number): string {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'
  return `${n}${suffix}`
}

export function repeatText(repeat: Repeat, day: number | null): string {
  if (repeat === 'daily') return 'Every day'
  if (repeat === 'weekly') return 'Every week'
  return day ? `Every month on the ${ordinal(day)}` : 'Every month'
}
