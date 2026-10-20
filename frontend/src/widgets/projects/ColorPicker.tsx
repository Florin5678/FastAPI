import { PROJECT_COLORS, type ProjectColor } from '../../api'

const NAMES: Record<ProjectColor, string> = {
  blue: 'Blue', teal: 'Teal', green: 'Green', yellow: 'Yellow', orange: 'Orange', red: 'Red', pink: 'Pink', purple: 'Purple', gray: 'Grey',
}

// Swatches for a project's background colour (or none)
export function ColorPicker({ value, onChange }: { value: ProjectColor | null; onChange: (color: ProjectColor | null) => void }) {
  return (
    <div className="color-picker" role="radiogroup" aria-label="Project colour">
      <button type="button" role="radio" aria-checked={value === null} className={value === null ? 'swatch none on' : 'swatch none'}
        title="No colour" aria-label="No colour" onClick={() => onChange(null)} />
      {PROJECT_COLORS.map((c) => (
        <button key={c} type="button" role="radio" aria-checked={value === c} className={`swatch project-color-${c}${value === c ? ' on' : ''}`}
          title={NAMES[c]} aria-label={NAMES[c]} onClick={() => onChange(c)} />
      ))}
    </div>
  )
}
