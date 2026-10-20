import { useState, type FormEvent } from 'react'
import { projectsApi, type Project, type ProjectComment, type ProjectTask } from '../../api'
import { Dialog } from '../../components/Dialog'

function when(iso: string): string {
  return new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// One task: edit its title, deadline, project and completed tick; read, add, edit and delete its comments.
// Changes are saved straight away (the dialog stays open), so the widget behind it stays in sync.
export function TaskDialog({ task, project, projects, onChanged, onClose }: {
  task: ProjectTask
  project: Project
  projects: Project[]
  onChanged: () => void
  onClose: () => void
}) {
  const [title, setTitle] = useState(task.title)
  const [deadline, setDeadline] = useState(task.deadline ?? '')
  const [projectId, setProjectId] = useState(project.id)
  const [comment, setComment] = useState('')
  const [editing, setEditing] = useState<ProjectComment | null>(null)
  const [editText, setEditText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onChanged()
      return true
    } catch (err) {
      setError((err as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const changed = title.trim() !== task.title || (deadline || null) !== task.deadline || projectId !== project.id
  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !changed) return
    await act(() => projectsApi.updateTask(task.id, {
      title: title.trim(), deadline: deadline || null, ...(projectId !== project.id ? { project_id: projectId } : {}),
    }))
  }

  const addComment = async (e: FormEvent) => {
    e.preventDefault()
    if (comment.trim() && await act(() => projectsApi.addComment(task.id, comment.trim()))) setComment('')
  }

  const saveComment = async (e: FormEvent) => {
    e.preventDefault()
    if (editing && editText.trim() && await act(() => projectsApi.updateComment(editing.id, editText.trim()))) setEditing(null)
  }

  const remove = () => {
    if (confirm(`Delete the task "${task.title}"${task.comments.length ? ' and its comments' : ''}?`)) {
      void act(() => projectsApi.deleteTask(task.id)).then((ok) => ok && onClose())
    }
  }

  return (
    <Dialog title="Task" onClose={onClose} wide>
      <form className="settings-form projects-form" onSubmit={save}>
        <label className="field">
          <span>Task</span>
          <input type="text" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <div className="task-fields">
          <label className="field">
            <span>Deadline <span className="muted">(optional)</span></span>
            <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
          </label>
          <label className="field">
            <span>Project</span>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}{p.done ? ' (completed)' : ''}</option>)}
            </select>
          </label>
        </div>
        <label className="task-done">
          <input type="checkbox" checked={task.done} disabled={busy}
            onChange={() => act(() => projectsApi.updateTask(task.id, { done: !task.done }))} />
          <span>Completed{task.done && task.done_at && <span className="muted"> · {when(task.done_at)}</span>}</span>
        </label>
        <div className="dialog-actions">
          <button type="button" className="button ghost danger-text projects-delete" disabled={busy} onClick={remove}>Delete task</button>
          <button type="submit" className="button primary" disabled={busy || !title.trim() || !changed}>Save changes</button>
        </div>
      </form>

      <h3 className="task-comments-title">Comments{task.comments.length > 0 && ` (${task.comments.length})`}</h3>
      {task.comments.length === 0 && <p className="muted small">No comments yet.</p>}
      <ul className="task-comments">
        {task.comments.map((c) => (
          <li key={c.id} className="task-comment">
            {editing?.id === c.id ? (
              <form className="task-comment-edit" onSubmit={saveComment}>
                <textarea value={editText} maxLength={2000} rows={3} autoFocus aria-label="Edit comment"
                  onChange={(e) => setEditText(e.target.value)} />
                <div className="dialog-actions">
                  <button type="button" className="button ghost small-button" onClick={() => setEditing(null)}>Cancel</button>
                  <button type="submit" className="button primary small-button" disabled={busy || !editText.trim()}>Save</button>
                </div>
              </form>
            ) : (
              <>
                <p className="task-comment-text">{c.text}</p>
                <div className="task-comment-meta">
                  <span className="muted small">{when(c.created_at)}{c.edited_at && ' · edited'}</span>
                  <span>
                    <button className="icon-button" disabled={busy} title="Edit comment" aria-label="Edit comment"
                      onClick={() => { setEditing(c); setEditText(c.text) }}>✎</button>
                    <button className="icon-button" disabled={busy} title="Delete comment" aria-label="Delete comment"
                      onClick={() => { if (confirm('Delete this comment?')) void act(() => projectsApi.deleteComment(c.id)) }}>✕</button>
                  </span>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
      <form className="task-comment-add" onSubmit={addComment}>
        <textarea placeholder="Add a comment…" value={comment} maxLength={2000} rows={2} aria-label="New comment"
          onChange={(e) => setComment(e.target.value)} />
        <button type="submit" className="button primary small-button" disabled={busy || !comment.trim()}>Comment</button>
      </form>
      {error && <p className="error-text small">{error}</p>}
    </Dialog>
  )
}
