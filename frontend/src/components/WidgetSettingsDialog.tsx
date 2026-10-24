import { useState, type FormEvent } from 'react'
import { widgetsApi, type ConfigField, type Widget } from '../api'
import { Dialog } from './Dialog'

type Props = { widget: Widget; onSaved: (widget: Widget) => void; onClose: () => void }

// Generic settings form, built from the widget's config_fields
export function WidgetSettingsDialog({ widget, onSaved, onClose }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(widget.settings)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const set = (key: string, value: unknown) => setValues((v) => ({ ...v, [key]: value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      onSaved(await widgetsApi.saveSettings(widget.id, values))
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <Dialog title={`${widget.name} settings`} onClose={onClose}>
      <form className="settings-form" onSubmit={submit}>
        {widget.config_fields.map((field) => (
          <Field key={field.key} field={field} value={values[field.key]} onChange={(v) => set(field.key, v)} />
        ))}
        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}

// Checkboxes: any of the options (labels: categoryLabel-style capitalised)
export function MultiField({ field, value, onChange, label = (o) => o.charAt(0).toUpperCase() + o.slice(1) }: {
  field: ConfigField
  value: unknown
  onChange: (v: string[]) => void
  label?: (option: string) => string
}) {
  const chosen = Array.isArray(value) ? (value as string[]) : []
  const options = field.options ?? []
  const toggle = (o: string) => onChange(chosen.includes(o) ? chosen.filter((c) => c !== o) : options.filter((x) => x === o || chosen.includes(x)))
  return (
    <fieldset className="field multi-field">
      <legend>{field.label}</legend>
      <div className="multi-options">
        {options.map((o) => (
          <label key={o} className="multi-option">
            <input type="checkbox" checked={chosen.includes(o)} onChange={() => toggle(o)} />
            {label(o)}
          </label>
        ))}
      </div>
      <span className="multi-actions">
        <button type="button" className="link small" onClick={() => onChange(options)}>All</button>
        <button type="button" className="link small" onClick={() => onChange([])}>None</button>
      </span>
    </fieldset>
  )
}

function Field({ field, value, onChange }: { field: ConfigField; value: unknown; onChange: (v: unknown) => void }) {
  const id = `setting-${field.key}`
  if (field.type === 'multi') return <MultiField field={field} value={value} onChange={onChange} />
  if (field.type === 'boolean') {
    return (
      <label className="field checkbox" htmlFor={id}>
        <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {field.label}
      </label>
    )
  }
  return (
    <label className="field" htmlFor={id}>
      <span>{field.label}</span>
      {field.type === 'number' && (
        <input
          id={id}
          type="number"
          min={field.min}
          max={field.max}
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        />
      )}
      {field.type === 'select' && (
        <select id={id} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          {field.options?.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      )}
      {field.type === 'text' && (
        <input id={id} type="text" value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
      )}
      {field.type === 'number' && field.min !== undefined && field.max !== undefined && (
        <span className="muted small">Between {field.min} and {field.max}</span>
      )}
    </label>
  )
}
