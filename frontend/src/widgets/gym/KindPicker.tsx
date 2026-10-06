import { useId, useState } from 'react'

// Workout type: one of the shown types (buttons), or "Other…" with a text field that suggests
// the hidden types and accepts any new name (which the server adds to the end of the list)
export function KindPicker({ kinds, others, value, onChange }: {
  kinds: string[]
  others: string[]
  value: string
  onChange: (kind: string) => void
}) {
  const [other, setOther] = useState(value !== '' && !kinds.includes(value))
  const listId = useId()
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
        <>
          <input className="gym-note gym-other" type="text" maxLength={32} autoFocus list={listId}
            placeholder={others.length ? `e.g. ${others.slice(0, 2).join(', ')} or a new type` : 'Workout type, e.g. Calisthenics'}
            value={value} onChange={(e) => onChange(e.target.value)} aria-label="Other workout type" />
          <datalist id={listId}>{others.map((k) => <option key={k} value={k} />)}</datalist>
        </>
      )}
    </>
  )
}
