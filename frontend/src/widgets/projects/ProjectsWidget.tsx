import { useState, type FormEvent } from 'react'
import { projectsApi, projectsOrderApi, type Project, type ProjectsData, type ProjectTask } from '../../api'
import type { WidgetProps } from '../types'
import { deadlineLabel } from './deadline'
import { moved } from './order'
import { ProjectDialog } from './ProjectDialog'
import { TaskDialog } from './TaskDialog'
import './projects.css'

// Which projects are collapsed: a per-browser convenience, so it's fine if storage is unavailable
const COLLAPSED_KEY = 'projects.collapsed'
function loadCollapsed(): string[] {
  try {
    return JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '[]') as string[]
  } catch {
    return []
  }
}
function saveCollapsed(ids: string[]) {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(ids))
  } catch {
    // storage blocked: collapsing just isn't remembered
  }
}

// Project tracker: tasks grouped by project, with deadlines, comments and ticks. Projects and tasks keep
// the user's order (⇅ Reorder: ↑ / ↓ or sort by date); new ones are slotted in by deadline on the server.
export function ProjectsWidget({ data, reload }: WidgetProps<ProjectsData>) {
  const [newName, setNewName] = useState('')
  const [newDeadline, setNewDeadline] = useState('')
  const [adding, setAdding] = useState(false)
  const [collapsed, setCollapsed] = useState<string[]>(loadCollapsed)
  const [showCompleted, setShowCompleted] = useState(false)
  const [reordering, setReordering] = useState(false)
  const [editingProject, setEditingProject] = useState<Project | null>(null)
  const [openTask, setOpenTask] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      reload()
      return true
    } catch (err) {
      setError((err as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id: string) => {
    const next = collapsed.includes(id) ? collapsed.filter((c) => c !== id) : [...collapsed, id]
    setCollapsed(next)
    saveCollapsed(next)
  }

  const addProject = async (e: FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    if (await run(() => projectsApi.addProject(newName.trim(), newDeadline || null))) {
      setNewName('')
      setNewDeadline('')
      setAdding(false)
    }
  }

  const openIds = data.projects.map((p) => p.id)
  const moveProject = (id: string, step: -1 | 1) => {
    const ids = moved(openIds, openIds, id, step)
    if (ids) void run(() => projectsOrderApi.projects({ ids }))
  }

  const all = [...data.projects, ...data.completed]
  const task = openTask ? all.flatMap((p) => p.tasks.map((t) => ({ project: p, task: t }))).find((x) => x.task.id === openTask) : undefined
  const overdue = data.projects.flatMap((p) => p.tasks).filter((t) => !t.done && t.deadline && t.deadline < data.today).length

  return (
    <div className="projects-widget">
      <div className="projects-head">
        {overdue > 0 ? <span className="small projects-overdue"><span className="dot" aria-hidden /> {overdue} overdue</span> : <span />}
        <span className="projects-head-actions">
          {data.projects.length + data.completed.length > 0 && (
            <button className={reordering ? 'button primary small-button' : 'button ghost small-button'} aria-pressed={reordering}
              onClick={() => setReordering(!reordering)} title="Change the order of projects and tasks">
              {reordering ? 'Done' : '⇅ Reorder'}
            </button>
          )}
          {!adding && !reordering && <button className="button primary small-button" onClick={() => setAdding(true)}>+ Project</button>}
        </span>
      </div>
      {reordering && (
        <p className="projects-reorder-hint small muted">
          Move projects and tasks with ↑ ↓.{' '}
          {data.projects.length > 1 && (
            <button className="link small" disabled={busy} onClick={() => run(() => projectsOrderApi.projects({ by_date: true }))}>Sort projects by date</button>
          )}
        </p>
      )}
      {adding && (
        <form className="projects-add" onSubmit={addProject}>
          <input type="text" placeholder="Project name" value={newName} maxLength={120} autoFocus aria-label="Project name"
            onChange={(e) => setNewName(e.target.value)} />
          <div className="projects-add-row">
            <input type="date" value={newDeadline} onChange={(e) => setNewDeadline(e.target.value)} aria-label="Deadline (optional)" title="Deadline (optional)" />
            <button type="button" className="button ghost small-button" onClick={() => { setAdding(false); setNewName(''); setNewDeadline('') }}>Cancel</button>
            <button type="submit" className="button primary small-button" disabled={busy || !newName.trim()}>Add</button>
          </div>
        </form>
      )}
      {error && <p className="error-text small">{error}</p>}

      {data.projects.length === 0 && !adding && <p className="muted small">No open projects. Add one to start tracking its tasks.</p>}
      {data.projects.map((p, i) => (
        <ProjectCard key={p.id} project={p} today={data.today} open={!collapsed.includes(p.id)} busy={busy} run={run}
          onToggle={() => toggle(p.id)} onEdit={() => setEditingProject(p)} onOpenTask={setOpenTask}
          reorder={reordering ? { up: i > 0 ? () => moveProject(p.id, -1) : null, down: i < openIds.length - 1 ? () => moveProject(p.id, 1) : null } : null} />
      ))}

      {data.completed.length > 0 && (
        <>
          <button className="link projects-completed-link" onClick={() => setShowCompleted(!showCompleted)}>
            {showCompleted ? 'Hide' : 'Show'} completed projects ({data.completed.length})
          </button>
          {showCompleted && data.completed.map((p) => (
            <ProjectCard key={p.id} project={p} today={data.today} open={false} busy={busy} run={run}
              onToggle={() => toggle(p.id)} onEdit={() => setEditingProject(p)} onOpenTask={setOpenTask} />
          ))}
        </>
      )}

      {editingProject && <ProjectDialog project={editingProject} onSaved={reload} onClose={() => setEditingProject(null)} />}
      {task && (
        <TaskDialog task={task.task} project={task.project} projects={all}
          onChanged={reload} onClose={() => setOpenTask(null)} />
      )}
    </div>
  )
}

type Mover = { up: (() => void) | null; down: (() => void) | null }

// ↑ / ↓ buttons (a null side is disabled: first or last in the list)
function MoveButtons({ name, mover, busy }: { name: string; mover: Mover; busy: boolean }) {
  return (
    <span className="move-buttons">
      <button className="icon-button" disabled={busy || !mover.up} onClick={mover.up ?? undefined} aria-label={`Move "${name}" up`} title="Move up">↑</button>
      <button className="icon-button" disabled={busy || !mover.down} onClick={mover.down ?? undefined} aria-label={`Move "${name}" down`} title="Move down">↓</button>
    </span>
  )
}

function ProjectCard({ project, today, open, busy, run, onToggle, onEdit, onOpenTask, reorder = null }: {
  project: Project
  today: string
  open: boolean
  busy: boolean
  run: (action: () => Promise<unknown>) => Promise<boolean>
  onToggle: () => void
  onEdit: () => void
  onOpenTask: (id: string) => void
  reorder?: Mover | null // shown while reordering (open projects)
}) {
  const [title, setTitle] = useState('')
  const [deadline, setDeadline] = useState('')
  const [showDone, setShowDone] = useState(false)
  const [expanded, setExpanded] = useState(open)
  const isOpen = project.done ? expanded : open
  const label = project.done ? null : deadlineLabel(project.deadline, today)
  const openTasks = project.tasks.filter((t) => !t.done)
  const doneTasks = project.tasks.filter((t) => t.done)
  const { done, total } = project.progress
  const visible = showDone ? [...openTasks, ...doneTasks] : openTasks
  const moveTask = (id: string, step: -1 | 1) => {
    const ids = moved(project.tasks.map((t) => t.id), visible.map((t) => t.id), id, step)
    if (ids) void run(() => projectsOrderApi.tasks(project.id, { ids }))
  }

  const addTask = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    if (await run(() => projectsApi.addTask(project.id, title.trim(), deadline || null))) {
      setTitle('')
      setDeadline('')
    }
  }

  return (
    <section className={project.done ? 'project done' : 'project'}>
      <div className="project-head">
        <input type="checkbox" checked={project.done} disabled={busy}
          aria-label={project.done ? `Reopen project "${project.name}"` : `Mark project "${project.name}" as completed`}
          title={project.done ? 'Reopen project' : 'Mark project as completed'}
          onChange={() => run(() => projectsApi.updateProject(project.id, { done: !project.done }))} />
        <button className="project-title" aria-expanded={isOpen} onClick={project.done ? () => setExpanded(!expanded) : onToggle}>
          <span className="project-caret" aria-hidden>{isOpen ? '▾' : '▸'}</span>
          <span className="project-name" title={project.name}>{project.name}</span>
        </button>
        {label && <span className={`deadline ${label.tone}`} title="Project deadline">{label.text}</span>}
        <span className="project-progress muted small" title={`${done} of ${total} tasks completed`}>{done}/{total}</span>
        {reorder ? <MoveButtons name={project.name} mover={reorder} busy={busy} />
          : <button className="icon-button" disabled={busy} onClick={onEdit} aria-label={`Edit project "${project.name}"`} title="Edit project">✎</button>}
      </div>
      {total > 0 && (
        <div className="project-bar" aria-hidden><span style={{ width: `${(done / total) * 100}%` }} /></div>
      )}

      {isOpen && (
        <div className="project-body">
          {openTasks.length === 0 && <p className="muted small">{total === 0 ? 'No tasks yet.' : 'All tasks completed.'}</p>}
          {reorder && openTasks.length > 1 && (
            <button className="link small project-sort" disabled={busy}
              onClick={() => run(() => projectsOrderApi.tasks(project.id, { by_date: true }))}>Sort tasks by date</button>
          )}
          <ul className="task-list">
            {visible.map((t, i) => (
              <TaskRow key={t.id} task={t} today={today} busy={busy} run={run} onOpen={() => onOpenTask(t.id)}
                mover={reorder ? { up: i > 0 ? () => moveTask(t.id, -1) : null, down: i < visible.length - 1 ? () => moveTask(t.id, 1) : null } : null} />
            ))}
          </ul>
          {doneTasks.length > 0 && (
            <button className="link small" onClick={() => setShowDone(!showDone)}>
              {showDone ? 'Hide' : 'Show'} completed tasks ({doneTasks.length})
            </button>
          )}
          {!project.done && (
            <form className="task-add" onSubmit={addTask}>
              <input type="text" placeholder="Add a task…" value={title} maxLength={200} aria-label={`New task in ${project.name}`}
                onChange={(e) => setTitle(e.target.value)} />
              <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} aria-label="Task deadline (optional)" title="Deadline (optional)" />
              <button type="submit" className="button ghost small-button" disabled={busy || !title.trim()}>Add</button>
            </form>
          )}
        </div>
      )}
    </section>
  )
}

function TaskRow({ task, today, busy, run, onOpen, mover }: {
  task: ProjectTask
  today: string
  busy: boolean
  run: (action: () => Promise<unknown>) => Promise<boolean>
  onOpen: () => void
  mover: Mover | null // ↑ / ↓ while reordering
}) {
  const label = task.done ? null : deadlineLabel(task.deadline, today)
  return (
    <li className={task.done ? 'task done' : 'task'}>
      <input type="checkbox" checked={task.done} disabled={busy}
        aria-label={task.done ? `Mark "${task.title}" as not completed` : `Mark "${task.title}" as completed`}
        onChange={() => run(() => projectsApi.updateTask(task.id, { done: !task.done }))} />
      <button className="task-title" onClick={onOpen} title="Open: edit, comments">
        <span>{task.title}</span>
        <span className="task-meta">
          {label && <span className={`deadline ${label.tone}`}>{label.text}</span>}
          {task.comments.length > 0 && <span className="muted" aria-label={`${task.comments.length} comments`}>💬 {task.comments.length}</span>}
        </span>
      </button>
      {mover && <MoveButtons name={task.title} mover={mover} busy={busy} />}
    </li>
  )
}
