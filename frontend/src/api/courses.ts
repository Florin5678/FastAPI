// Courses widget: a course file's text, for "Summarize with Claude"
import { request } from './client'

export type CourseFileText = { name: string; course: string; text: string }

export const coursesApi = {
  text: (fileId: string) => request<CourseFileText>(`/widgets/courses/files/${encodeURIComponent(fileId)}/text`),
}
