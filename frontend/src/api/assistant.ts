// Assistant widget: the prompt settings (edited in the widget's Settings dialog)
import { json, request } from './client'

export type ExtraInstruction = { name: string; text: string; enabled: boolean }

export type AssistantSettings = {
  instructions: string // opening text; {when} = the current day and time
  default_question: string
  extras: ExtraInstruction[]
  briefing: Record<string, number | 'on' | 'off'> // widget id -> items / on / off (missing = included as usual)
  context: string // free-form notes for Claude
}

export type BriefingWidget = { id: string; name: string; on_dashboard: boolean; default_items: number | null }

export const assistantApi = {
  settings: () => request<{ settings: AssistantSettings; widgets: BriefingWidget[] }>('/widgets/assistant/settings'),
  save: (settings: AssistantSettings) =>
    request<{ settings: AssistantSettings }>('/widgets/assistant/settings', { method: 'PUT', ...json(settings) }),
}
