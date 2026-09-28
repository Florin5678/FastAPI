import { useState } from 'react'
import type { WidgetProps } from '../types'
import './assistant.css'

export type AssistantData = {
  sections: { widget: string; name: string; text: string }[]
  // Wording from content/assistant_prompt.md (editable without code changes)
  prompt: { instructions: string; default_question: string }
}

// claude.ai pre-fills a new chat from ?q=; beyond this length the prompt goes via the
// clipboard only (long URLs can be cut off)
const MAX_URL_PROMPT = 6000

function buildPrompt(data: AssistantData): string {
  const when = new Date().toLocaleString([], { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
  const intro = data.prompt.instructions.replaceAll('{when}', when)
  const briefing = data.sections.map((s) => `## ${s.name}\n${s.text}`).join('\n\n')
  return `${intro}\n\n${briefing}\n\nMy question: ${data.prompt.default_question}`
}

export function AssistantWidget({ data }: WidgetProps<AssistantData>) {
  const [note, setNote] = useState<string | null>(null)

  const copy = async (text: string): Promise<boolean> => {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      return false
    }
  }

  const briefMe = async () => {
    const prompt = buildPrompt(data)
    const fits = encodeURIComponent(prompt).length <= MAX_URL_PROMPT
    // Open synchronously (inside the click) so pop-up blockers allow it
    window.open(fits ? `https://claude.ai/new?q=${encodeURIComponent(prompt)}` : 'https://claude.ai/new', '_blank', 'noopener')
    const copied = await copy(prompt)
    setNote(fits
      ? `Opened Claude with your briefing${copied ? ' (also copied, in case it isn\'t filled in)' : ''}.`
      : copied ? 'Opened Claude. The briefing is long: paste it into the chat (it\'s copied).' : 'Opened Claude. Copying failed, use "Copy briefing".')
  }

  const copyBriefing = async () => {
    setNote(await copy(buildPrompt(data)) ? 'Briefing copied.' : "Couldn't copy (the browser blocked it).")
  }

  return (
    <div className="assistant-widget">
      <div className="assistant-buttons">
        <button className="button ghost" onClick={copyBriefing}>Copy briefing</button>
        <button className="button primary" onClick={briefMe}>Brief me ↗</button>
      </div>
      {note
        ? <p className="small assistant-note">{note}</p>
        : <p className="muted small">Opens claude.ai · your journal is never included</p>}
    </div>
  )
}
