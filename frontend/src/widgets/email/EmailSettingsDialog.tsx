import { useState, type FormEvent } from 'react'
import { Dialog } from '../../components/Dialog'
import { MultiField } from '../../components/WidgetSettingsDialog'
import { categoryLabel } from '../../lib/format'

// The categories the Email tile shows: email categories in briefing order, then not-yet-summarized
const CATEGORIES = ['personal', 'work', 'school', 'finance', 'travel', 'social', 'shopping', 'other',
  'notification', 'newsletter', 'promotion', 'unsummarized']

// The Email tile's own settings (also in Edit mode's ⚙): which categories it shows
export function EmailSettingsDialog({ settings, onSave, onClose }: {
  settings: Record<string, unknown>
  onSave: (changes: Record<string, unknown>) => Promise<void>
  onClose: () => void
}) {
  const [categories, setCategories] = useState<string[]>(Array.isArray(settings.categories) ? settings.categories as string[] : CATEGORIES)
  const [saving, setSaving] = useState(false)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    await onSave({ categories })  // errors are shown by the dashboard
    onClose()
  }

  return (
    <Dialog title="Email settings" onClose={onClose}>
      <form className="settings-form" onSubmit={save}>
        <MultiField field={{ key: 'categories', label: 'Categories to show', type: 'multi', default: CATEGORIES, options: CATEGORIES }}
          value={categories} onChange={setCategories} label={categoryLabel} />
        <p className="muted small">Hidden categories are left out of the tile's count, chips and latest emails (the
          Assistant's briefing has its own email filters in its settings).</p>
        <div className="dialog-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}
