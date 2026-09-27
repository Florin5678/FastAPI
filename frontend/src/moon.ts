// Moon phase from the mean synodic month (no API). Accurate to within about half a
// day, which is plenty for "full moon tonight" / "full moon in 3 days".
const SYNODIC_DAYS = 29.530588853
const KNOWN_NEW_MOON = Date.UTC(2000, 0, 6, 18, 14)
const FULL_AGE = SYNODIC_DAYS / 2

const PHASES: [maxAge: number, name: string, icon: string][] = [
  [1.85, 'New moon', '🌑'],
  [5.54, 'Waxing crescent', '🌒'],
  [9.23, 'First quarter', '🌓'],
  [FULL_AGE, 'Waxing gibbous', '🌔'],
  [20.3, 'Waning gibbous', '🌖'],
  [23.99, 'Last quarter', '🌗'],
  [27.68, 'Waning crescent', '🌘'],
  [SYNODIC_DAYS, 'New moon', '🌑'],
]

export type MoonInfo = { icon: string; text: string; illumination: number }

function days(n: number): string {
  return n === 1 ? 'a day' : `${n} days`
}

export function moonPhase(date: Date = new Date()): MoonInfo {
  const age = ((((date.getTime() - KNOWN_NEW_MOON) / 86400000) % SYNODIC_DAYS) + SYNODIC_DAYS) % SYNODIC_DAYS
  const illumination = Math.round(((1 - Math.cos((2 * Math.PI * age) / SYNODIC_DAYS)) / 2) * 100)
  const toFull = FULL_AGE - age // > 0 before full, < 0 after
  const toNew = SYNODIC_DAYS - age

  if (Math.abs(toFull) <= 1) return { icon: '🌕', text: 'Full moon tonight', illumination }
  if (age <= 1 || toNew <= 1) return { icon: '🌑', text: 'New moon tonight', illumination }

  const [, name, icon] = PHASES.find(([maxAge]) => age < maxAge) ?? PHASES[PHASES.length - 1]
  let hint = `${illumination}% lit`
  if (toFull > 1 && toFull <= 4) hint += ` · full moon in ${days(Math.round(toFull))}`
  else if (toFull < -1 && toFull >= -3) hint += Math.round(-toFull) === 1 ? ' · full moon was yesterday' : ` · full moon was ${days(Math.round(-toFull))} ago`
  else if (toNew > 1 && toNew <= 3) hint += ` · new moon in ${days(Math.round(toNew))}`
  return { icon, text: `${name}, ${hint}`, illumination }
}
