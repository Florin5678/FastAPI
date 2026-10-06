import { useState } from 'react'

// Workout type: one of the routine chips, or "Other" with a free-text name (e.g. Calisthenics)
export function KindPicker({ kinds, value, onChange }: { kinds: string[]; value: string; onChange: (kind: string) => void }) {
  const [other, setOther] = useState(value !== '' && !kinds.includes(value))
  return (
    <>
      <div className="chips compact" role="radiogroup" aria-label="Workout type">
        {kinds.map((k) => (
          <button key={k} type="button" role="radio" aria-checked={!other && value === k} className={!other && value === k ? 'chip active' : 'chip'}
            onClick={() => { setOther(false); onChange(k) }}>{k}</button>
        ))}
        <button type="button" role="radio" aria-checked={other} className={other ? 'chip active' : 'chip'}
          onClick={() => { setOther(true); onChange(kinds.includes(value) ? '' : value) }}>Other…</button>
      </div>
      {other && (
        <input className="gym-note gym-other" type="text" maxLength={32} autoFocus placeholder="Workout type, e.g. Calisthenics"
          value={value} onChange={(e) => onChange(e.target.value)} aria-label="Other workout type" />
      )}
    </>
  )
}
