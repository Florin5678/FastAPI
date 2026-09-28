// Courses widget: pick Drive files, and a picked file's text for "Summarize with Claude"
import { json, request } from './client'

export type CourseFileText = { name: string; course: string; text: string }
export type PickedFile = { id: string; name: string; course: string }
export type DriveItem = { id: string; name: string; kind: 'folder' | 'doc' | 'pdf'; modified: string | null }
export type DriveFolder = { folder: string; name: string; items: DriveItem[] }

export const coursesApi = {
  text: (fileId: string) => request<CourseFileText>(`/widgets/courses/files/${encodeURIComponent(fileId)}/text`),
  // folder: "root" (My Drive), "shared" (Shared with me) or a folder id; q: search by name
  browse: (folder: string, q = '') =>
    request<DriveFolder>(`/widgets/courses/browse?folder=${encodeURIComponent(folder)}&q=${encodeURIComponent(q)}`),
  picked: () => request<{ files: PickedFile[] }>('/widgets/courses/files'),
  pick: (files: { id: string; course: string }[]) =>
    request<{ files: PickedFile[] }>('/widgets/courses/files', { method: 'PUT', ...json({ files }) }),
}
