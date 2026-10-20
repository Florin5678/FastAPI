import { useState, type FormEvent } from 'react'
import { projectsApi, type Project, type ProjectColor } from '../../api'
import { Dialog } from '../../components/Dialog'
import { ColorPicker } from './ColorPicker'

// Rename a project, change its deadline or colour, or delete it (with its tasks and comments)
export function ProjectDialog({ project, onSaved, onClose }: { project: Project; onSaved: () => void; onClose: () => void }) {
  const [name, setName] = useState(project.name)
  const [deadline, setDeadline] = useState(project.deadline ?? '')
  const [color, setColor] = useState<ProjectColor | null>(project.color ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onSaved()
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  const save = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) void act(() => projectsApi.updateProject(project.id, { name: name.trim(), deadline: deadline || null, color }))
  }

  const remove = () => {
    const tasks = project.tasks.length
    if (confirm(`Delete "${project.name}"${tasks ? ` and its ${tasks} task${tasks === 1 ? '' : 's'}` : ''}?`)) {
      void act(() => projectsApi.deleteProject(project.id))
    }
  }

  return (
    <Dialog title="Edit project" onClose={onClose}>
      <form className="settings-form projects-form" onSubmit={save}>
        <label className="field">
          <span>Name</span>
          <input type="text" value={name} maxLength={120} autoFocus onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>Deadline <span className="muted">(optional)</span></span>
          <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
        </label>
        <div className="field">
          <span>Colour</span>
          <ColorPicker value={color} onChange={setColor} />
        </div>
        {error && <p className="error-text small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button ghost danger-text projects-delete" disabled={busy} onClick={remove}>Delete project</button>
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy || !name.trim()}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Dialog>
  )
}
