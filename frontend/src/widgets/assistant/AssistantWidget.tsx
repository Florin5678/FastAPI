import { useState } from 'react'
import type { WidgetProps } from '../types'
import './assistant.css'

export type AssistantData = {
  sections: { widget: string; name: string; text: string }[]
}

const SUGGESTIONS = [
  'Plan my day',
  'What should I eat to hit my protein goal?',
  'Anything I should not forget today?',
  'Summarize my week so far',
]

// claude.ai pre-fills a new chat from ?q=; beyond this length the prompt goes via the
// clipboard only (long URLs can be cut off)
const MAX_URL_PROMPT = 6000
const DEFAULT_QUESTION = 'Give me a short overview of my day and three practical suggestions.'

function buildPrompt(data: AssistantData, question: string): string {
  const now = new Date()
  const when = now.toLocaleString([], { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
  const briefing = data.sections.map((s) => `## ${s.name}\n${s.text}`).join('\n\n')
  return `Here is my personal dashboard briefing for ${when}. Use it as context.\n\n${briefing}\n\nMy question: ${question.trim() || DEFAULT_QUESTION}`
}

export function AssistantWidget({ data }: WidgetProps<AssistantData>) {
  const [question, setQuestion] = useState('')
  const [note, setNote] = useState<string | null>(null)

  const copy = async (text: string): Promise<boolean> => {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      return false
    }
  }

  const ask = async () => {
    const prompt = buildPrompt(data, question)
    const fits = encodeURIComponent(prompt).length <= MAX_URL_PROMPT
    // Open synchronously (inside the click) so pop-up blockers allow it
    window.open(fits ? `https://claude.ai/new?q=${encodeURIComponent(prompt)}` : 'https://claude.ai/new', '_blank', 'noopener')
    const copied = await copy(prompt)
    setNote(fits
      ? `Opened Claude with your briefing${copied ? ' (also copied, in case it isn\'t filled in)' : ''}.`
      : copied ? 'Opened Claude. The briefing is long: paste it into the chat (it\'s copied).' : 'Opened Claude. Copying failed, use "Copy briefing".')
  }

  const copyBriefing = async () => {
    setNote(await copy(buildPrompt(data, question)) ? 'Briefing copied.' : "Couldn't copy (the browser blocked it).")
  }

  return (
    <div className="assistant-widget">
      <div className="assistant-briefing" aria-label="Today's briefing">
        {data.sections.length === 0 && <p className="muted small">Add some widgets to get a briefing.</p>}
        {data.sections.map((s) => (
          <section key={s.widget}>
            <h4>{s.name}</h4>
            <p>{s.text}</p>
          </section>
        ))}
      </div>

      <div className="assistant-ask">
        <div className="chips compact">
          {SUGGESTIONS.map((s) => (
            <button key={s} className="chip" onClick={() => setQuestion(s)}>{s}</button>
          ))}
        </div>
        <textarea
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask Claude about your day… (or leave empty for an overview)"
          aria-label="Question for Claude"
        />
        <div className="assistant-actions">
          <span className="muted small">Uses your Claude subscription on claude.ai · your journal is never included</span>
          <span className="assistant-buttons">
            <button className="button ghost small-button" onClick={copyBriefing}>Copy briefing</button>
            <button className="button primary small-button" onClick={ask}>Ask Claude ↗</button>
          </span>
        </div>
        {note && <p className="small assistant-note">{note}</p>}
      </div>
    </div>
  )
}
