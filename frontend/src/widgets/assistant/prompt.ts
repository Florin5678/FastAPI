// The Assistant's prompt. The server builds all of it (app/widgets/assistant.py): the
// briefing, then "How to answer" (the answer sections, then the rules),
// then the Claude prompt; {when} is filled in here with the current time.

import type { MorningBrief } from '../../api'

export type AssistantData = {
  sections: { widget: string; name: string; text: string }[]
  prompt: string // the full prompt; "{when}" = the current day and time
  claude_prompt: string // what "Open in Claude" pre-fills (Settings -> Claude prompt)
  morning_brief: MorningBrief
}

export function fillWhen(prompt: string): string {
  const when = new Date().toLocaleString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  return prompt.replaceAll('{when}', when)
}
