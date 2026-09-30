// Building the prompt "Open in Claude" / "Copy briefing" send to Claude (shared by the widget
// and its Settings dialog's preview)
import type { AssistantSettings } from '../../api'

export type AssistantData = {
  sections: { widget: string; name: string; text: string }[]
  // Built on the server from the Assistant settings (see composeInstructions)
  prompt: { instructions: string; default_question: string }
}

// claude.ai pre-fills a new chat from ?q=; longer links can be cut off, so "Open in Claude"
// trims the briefing to fit (Copy briefing always has everything)
export const MAX_URL_PROMPT = 6000

// The prompt, with list items ("- ...") dropped from the longest sections until its
// encoded length fits `maxEncoded`. Instructions and the question are never trimmed.
export function buildPrompt(data: AssistantData, maxEncoded = Infinity): { prompt: string; dropped: number; fits: boolean } {
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

// Same as build_prompt() in app/widgets/assistant.py, for the live preview of unsaved settings
export function composeInstructions(s: AssistantSettings): string {
  let text = s.instructions.trim()
  const extras = s.extras.filter((e) => e.enabled && e.name.trim() && e.text.trim())
  if (extras.length) {
    text += '\n\nIn your answer, also include (only where it fits my question):\n' + extras.map((e) => `- ${e.name.trim()}: ${e.text.trim()}`).join('\n')
  }
  return text
}
