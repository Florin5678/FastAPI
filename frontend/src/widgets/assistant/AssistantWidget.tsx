import { useState } from 'react'
import type { WidgetProps } from '../types'
import './assistant.css'

export type AssistantData = {
  sections: { widget: string; name: string; text: string }[]
  // Wording from content/assistant_prompt.md (editable without code changes)
  prompt: { instructions: string; default_question: string }
}

// claude.ai pre-fills a new chat from ?q=; longer links can be cut off, so "Brief me"
// trims the briefing to fit (Copy briefing always has everything)
const MAX_URL_PROMPT = 6000

// The prompt, with list items ("- ...") dropped from the longest sections until its
// encoded length fits `maxEncoded`. Instructions and the question are never trimmed.
function buildPrompt(data: AssistantData, maxEncoded = Infinity): { prompt: string; dropped: number; fits: boolean } {
  const when = new Date().toLocaleString([], { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
  const intro = data.prompt.instructions.replaceAll('{when}', when)
  const sections = data.sections.map((s) => ({ name: s.name, lines: s.text.split('\n'), dropped: 0 }))
  const render = () => {
    const briefing = sections
      .map((s) => [`## ${s.name}`, ...s.lines, ...(s.dropped ? [`(+${s.dropped} more not shown)`] : [])].join('\n'))
      .join('\n\n')
    return `${intro}\n\n${briefing}\n\nMy question: ${data.prompt.default_question}`
  }
  const items = (s: (typeof sections)[number]) => s.lines.filter((l) => l.startsWith('- ')).length

  let prompt = render()
  let dropped = 0
  while (encodeURIComponent(prompt).length > maxEncoded) {
    // Trim the section with the most items left (the longest one on a tie)
    const longest = sections
      .filter((s) => items(s) > 0)
      .sort((a, b) => items(b) - items(a) || b.lines.join('\n').length - a.lines.join('\n').length)[0]
    if (!longest) break
    const last = longest.lines.map((l) => l.startsWith('- ')).lastIndexOf(true)
    longest.lines.splice(last, 1)
    longest.dropped += 1
    dropped += 1
    prompt = render()
  }
  return { prompt, dropped, fits: encodeURIComponent(prompt).length <= maxEncoded }
}

export function AssistantWidget({ data, actions }: WidgetProps<AssistantData>) {
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
    const { prompt, dropped, fits } = buildPrompt(data, MAX_URL_PROMPT)
    // Open synchronously (inside the click) so pop-up blockers allow it
    window.open(fits ? `https://claude.ai/new?q=${encodeURIComponent(prompt)}` : 'https://claude.ai/new', '_blank', 'noopener')
    if (!fits) {
      // Even the trimmed briefing is too long (very long instructions): paste it instead
      setNote(await copy(buildPrompt(data).prompt)
        ? 'Opened Claude. The briefing is too long for a link: paste it into the chat (it\'s copied).'
        : 'Opened Claude. Copying failed, use "Copy briefing".')
      return
    }
    setNote(dropped
      ? `Opened Claude with your briefing. Left out ${dropped} item${dropped === 1 ? '' : 's'} so it fits; "Copy briefing" has everything.`
      : 'Opened Claude with your briefing.')
  }

  const copyBriefing = async () => {
    setNote(await copy(buildPrompt(data).prompt) ? 'Briefing copied.' : "Couldn't copy (the browser blocked it).")
  }

  return (
    <div className="assistant-widget">
      <div className="assistant-buttons">
        <button className="button ghost" onClick={copyBriefing}>Copy briefing</button>
        <button className="button primary" onClick={briefMe}>Brief me ↗</button>
      </div>
      {note
        ? <p className="small assistant-note">{note}</p>
        : <button className="assistant-link small" onClick={() => actions.goTo('connector')}>Claude connector: let Claude read &amp; edit your dashboard →</button>}
    </div>
  )
}
