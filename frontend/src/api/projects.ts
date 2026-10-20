// Projects widget: projects -> tasks -> comments
import { json, request } from './client'

export type ProjectComment = {
  id: string
  text: string
  created_at: string
  edited_at: string | null
}

export type ProjectTask = {
  id: string
  title: string
  deadline: string | null // a local date, YYYY-MM-DD
  done: boolean
  done_at: string | null
  created_at: string
  comments: ProjectComment[] // oldest first
}

// A project's background tint (projects.css maps each to a light and a dark shade)
export const PROJECT_COLORS = ['blue', 'teal', 'green', 'yellow', 'orange', 'red', 'pink', 'purple', 'gray'] as const
export type ProjectColor = (typeof PROJECT_COLORS)[number]

export type Project = {
  id: string
  name: string
  deadline: string | null
  color?: ProjectColor | null // none: the tile's own background
  done: boolean
  done_at: string | null
  created_at: string
  tasks: ProjectTask[] // in the user's order (new ones are slotted in by deadline)
  progress: { done: number; total: number }
}

export type ProjectsData = {
  today: string
  projects: Project[] // open, in the user's order
  completed: Project[] // most recently completed first
}

const base = '/widgets/projects'

export const projectsApi = {
  addProject: (name: string, deadline: string | null, color: ProjectColor | null) =>
    request<Project>(`${base}/projects`, { method: 'POST', ...json({ name, deadline, color }) }),
  updateProject: (id: string, changes: Partial<Pick<Project, 'name' | 'deadline' | 'color' | 'done'>>) =>
    request<Project>(`${base}/projects/${id}`, { method: 'PATCH', ...json(changes) }),
  deleteProject: (id: string) => request<unknown>(`${base}/projects/${id}`, { method: 'DELETE' }),
  addTask: (projectId: string, title: string, deadline: string | null) =>
    request<ProjectTask>(`${base}/projects/${projectId}/tasks`, { method: 'POST', ...json({ title, deadline }) }),
  updateTask: (id: string, changes: Partial<Pick<ProjectTask, 'title' | 'deadline' | 'done'>> & { project_id?: string }) =>
    request<ProjectTask>(`${base}/tasks/${id}`, { method: 'PATCH', ...json(changes) }),
  deleteTask: (id: string) => request<unknown>(`${base}/tasks/${id}`, { method: 'DELETE' }),
  addComment: (taskId: string, text: string) =>
    request<ProjectComment>(`${base}/tasks/${taskId}/comments`, { method: 'POST', ...json({ text }) }),
  updateComment: (id: string, text: string) =>
    request<ProjectComment>(`${base}/comments/${id}`, { method: 'PATCH', ...json({ text }) }),
  deleteComment: (id: string) => request<unknown>(`${base}/comments/${id}`, { method: 'DELETE' }),
}

// Reorder: ids in the new order (unlisted ones follow), or sort the whole list by deadline
export const projectsOrderApi = {
  projects: (order: { ids?: string[]; by_date?: boolean }) =>
    request<{ order: string[] }>(`${base}/projects/order`, { method: 'PUT', ...json(order) }),
  tasks: (projectId: string, order: { ids?: string[]; by_date?: boolean }) =>
    request<{ order: string[] }>(`${base}/projects/${projectId}/tasks/order`, { method: 'PUT', ...json(order) }),
}

