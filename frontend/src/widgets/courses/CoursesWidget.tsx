import { useEffect, useState } from 'react'
import { coursesApi, localDate, shiftDay, type CourseFileText } from '../../api'
import { GoogleSetup } from '../../components/GoogleSetup'
import type { WidgetProps } from '../types'
import { FilePicker } from './FilePicker'
import './courses.css'

type CourseFile = {
  id: string
  name: string
  course: string
  kind: 'doc' | 'pdf'
  modified: string | null
  link: string | null
  readable: boolean | null // null: not read yet
}
type Deadline = { date: string; text: string; file: string; course: string; link: string | null }

export type CoursesData =
  | { needs_setup: 'no_file' | 'permission' | 'api_disabled' }
  | {
      needs_setup: null
      days: number
      files: CourseFile[]
      deadlines: Deadline[]
      missing: string[] // picked files that were deleted or can't be opened
      reading: { done: number; total: number } | null // files still being read in the background
    }

const READING_REFRESH_MS = 5000

// "Summarize with Claude": first load the file's text, then one click copies it and
// opens claude.ai (copying needs a fresh click, so it can't happen after the download)
type Summary = { fileId: string; state: 'loading' } | { fileId: string; state: 'ready'; file: CourseFileText } | { fileId: string; state: 'error'; message: string }

function dayLabel(day: string): string {
  const today = localDate()
  if (day === today) return 'Today'
  if (day === shiftDay(today, 1)) return 'Tomorrow'
  return new Date(day + 'T12:00').toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
}

function daysUntil(day: string): number {
  const [y, m, d] = day.split('-').map(Number)
  const [ty, tm, td] = localDate().split('-').map(Number)
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(ty, tm - 1, td)) / 86_400_000)
}

function updated(iso: string | null): string {
  if (!iso) return ''
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return 'updated today'
  if (days === 1) return 'updated yesterday'
  if (days < 30) return `updated ${days} days ago`
  return `updated ${new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' })}`
}

function summaryPrompt(file: CourseFileText): string {
  return `Summarize this course file, "${file.name}"${file.course ? ` (${file.course})` : ''}: the main points, what I should know for the exam, and any deadlines. I'm pasting its text below.\n\n`
}

export function CoursesWidget({ data, reload }: WidgetProps<CoursesData>) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [picking, setPicking] = useState(false)

  // While files are read in the background, refresh to show progress and new deadlines
  const reading = data.needs_setup === null && data.reading !== null
  useEffect(() => {
    if (!reading) return
    const timer = setTimeout(reload, READING_REFRESH_MS)
    return () => clearTimeout(timer)
  }, [reading, data, reload])

  if (data.needs_setup === 'permission' || data.needs_setup === 'api_disabled') {
    return <GoogleSetup reason={data.needs_setup} service="Google Drive" api="drive.googleapis.com" />
  }
  const picker = picking && <FilePicker onSaved={reload} onClose={() => setPicking(false)} />
  if (data.needs_setup) {
    return (
      <div className="courses-setup">
        <p>Pick the course files (Google Docs and PDFs) from your Drive that this widget should read for deadlines and summaries.</p>
        <button className="button primary" onClick={() => setPicking(true)}>Choose files</button>
        {picker}
      </div>
    )
  }

  const prepare = async (file: CourseFile) => {
    setNote(null)
    setSummary({ fileId: file.id, state: 'loading' })
    try {
      setSummary({ fileId: file.id, state: 'ready', file: await coursesApi.text(file.id) })
    } catch (err) {
      setSummary({ fileId: file.id, state: 'error', message: (err as Error).message })
    }
  }

  const openClaude = (file: CourseFileText) => {
    const copying = navigator.clipboard.writeText(file.text)
    // Open synchronously (inside the click) so pop-up blockers allow it
    window.open(`https://claude.ai/new?q=${encodeURIComponent(summaryPrompt(file))}`, '_blank', 'noopener')
    copying.then(
      () => setNote(`"${file.name}" copied. Paste it (Ctrl+V) after the prompt in Claude and send.`),
      () => setNote("Couldn't copy the text (the browser blocked it). Try again."),
    )
    setSummary(null)
  }

  return (
    <div className="courses-widget">
      <section>
        <h4 className="courses-heading">Upcoming deadlines</h4>
        {data.reading && (
          <p className="small courses-reading">
            Reading your files… {data.reading.done} of {data.reading.total} done. Deadlines appear as each file is read.
          </p>
        )}
        {data.deadlines.length === 0 ? (
          !data.reading && <p className="muted small">None found in the next {data.days} days.</p>
        ) : (
          <ul className="courses-deadlines">
            {data.deadlines.map((d) => {
              const days = daysUntil(d.date)
              return (
                <li key={`${d.date}-${d.text}`}>
                  <span className={days <= 3 ? 'deadline-date soon' : 'deadline-date'}>
                    {dayLabel(d.date)}
                    {days > 1 && <span className="deadline-in">in {days} days</span>}
                  </span>
                  <span className="deadline-text">
                    {d.text}
                    <a className="deadline-source" href={d.link ?? undefined} target="_blank" rel="noopener noreferrer">
                      {[d.course, d.file].filter(Boolean).join(' / ')}
                    </a>
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section>
        <h4 className="courses-heading">
          Files <button className="link-button courses-choose" onClick={() => setPicking(true)}>Choose files</button>
        </h4>
        {note && <p className="small courses-note">{note}</p>}
        {data.missing.length > 0 && (
          <p className="small error-text">
            Can't open {data.missing.join(', ')} any more (deleted or no longer shared). Choose files to update the list.
          </p>
        )}
        {data.files.length === 0 ? (
          <p className="muted small">No files picked.</p>
        ) : (
          <ul className="courses-files">
            {data.files.map((f) => {
              const mine = summary?.fileId === f.id ? summary : null
              return (
                <li key={f.id}>
                  <a className="course-file" href={f.link ?? undefined} target="_blank" rel="noopener noreferrer">
                    <span className="course-file-name">{f.kind === 'pdf' ? '📄' : '📝'} {f.name}</span>
                    <span className="muted small">{[f.course, updated(f.modified)].filter(Boolean).join(' · ')}</span>
                  </a>
                  {f.readable === null ? (
                    <span className="muted small">reading…</span>
                  ) : !f.readable ? (
                    <span className="muted small" title="No text could be read (a scanned PDF, or too large)">no text</span>
                  ) : mine?.state === 'ready' ? (
                    <button className="button primary small-button" onClick={() => openClaude(mine.file)}>Copy &amp; open Claude ↗</button>
                  ) : (
                    <button className="button ghost small-button" onClick={() => prepare(f)} disabled={mine?.state === 'loading'}>
                      {mine?.state === 'loading' ? 'Loading…' : 'Summarize'}
                    </button>
                  )}
                  {mine?.state === 'error' && <p className="error-text small course-file-error">{mine.message}</p>}
                </li>
              )
            })}
          </ul>
        )}
      </section>
      {picker}
    </div>
  )
}
