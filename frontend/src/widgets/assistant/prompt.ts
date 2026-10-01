// The Assistant's prompt. The server builds all of it (app/widgets/assistant.py): the
// briefing, then "How to answer" (the extra instructions as sections, then the rules),
// then the question; {when} is filled in here with the current time.

export type AssistantData = {
  sections: { widget: string; name: string; text: string }[]
  prompt: string // the full prompt; "{when}" = the current day and time
}

export function fillWhen(prompt: string): string {
  const when = new Date().toLocaleString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  return prompt.replaceAll('{when}', when)
}

// What "Open in Claude" pre-fills on claude.ai: Claude fetches the full briefing itself
// through the My Dashboard connector (no link-length limit, always up to date)
export const OPEN_IN_CLAUDE_PROMPT =
  'Brief me. First call get_briefing from my "My Dashboard" connector, then answer exactly as its ' +
  '"How to answer" part says. If you can\'t use that connector here, tell me to switch it on for this chat.'
