import { useEffect, useState } from 'react'
import { moonPhase } from '../moon'

function ordinal(n: number): string {
  const rem100 = n % 100
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`
  return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`
}

// "Hi Florin" + "It's Sunday, September 27th · 21:07 · 🌕 Full moon tonight"
export function IntroHeader({ name }: { name: string }) {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    // Tick on the minute so the clock (and date/moon at midnight) stays current
    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      timer = setTimeout(() => { setNow(new Date()); schedule() }, 60000 - (Date.now() % 60000) + 50)
    }
    schedule()
    return () => clearTimeout(timer)
  }, [])

  const weekday = now.toLocaleDateString('en-GB', { weekday: 'long' })
  const month = now.toLocaleDateString('en-GB', { month: 'long' })
  const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const moon = moonPhase(now)

  return (
    <div className="intro">
      <h1 className="intro-hello">Hi {name}</h1>
      <p className="intro-line">
        <span>It's {weekday}, {month} {ordinal(now.getDate())}</span>
        <span className="intro-sep" aria-hidden>·</span>
        <time dateTime={now.toISOString()}>{time}</time>
        <span className="intro-sep" aria-hidden>·</span>
        <span title={`${moon.illumination}% of the moon is lit`}>
          <span aria-hidden>{moon.icon}</span> {moon.text}
        </span>
      </p>
    </div>
  )
}
