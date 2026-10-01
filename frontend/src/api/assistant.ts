// Assistant widget: the prompt settings (edited in the widget's Settings dialog)
import { json, request } from './client'

// One answer section ("Answer sections" in the Settings dialog)
export type ExtraInstruction = { name: string; text: string; enabled: boolean }

// Applied on the server before Claude sees anything
export type BriefingFilters = {
  calendar_ignore: string // comma/line separated words; events whose title contains one are left out
  email_skip_categories: string[]
  email_ignore: string // comma/line separated words, matched in sender or subject
}

export type AssistantSettings = {
  instructions: string // opening text; {when} = the current day and time
  default_question: string
  extras: ExtraInstruction[]
  briefing: Record<string, number | 'on' | 'off'> // widget id -> items / on / off (missing = included as usual)
  filters: BriefingFilters
  model: string // AI chat model id
  monthly_budget: number // AI chat spend limit per month, USD (0 = off)
}

export type ChatMessage = { role: 'user' | 'assistant'; content: string }
export type ChatUsage = { month: string; cost: number; requests: number; budget: number; model: string; model_label: string }
export type ChatModel = { id: string; label: string; input: number; output: number } // $ per million tokens
export type ChatReply = {
  reply: string
  actions: { tool: string; error: string | null }[]
  changes: { id: number; summary: string }[] // undo via connectorApi.undo
  usage: ChatUsage
}

export type BriefingWidget = { id: string; name: string; on_dashboard: boolean; default_items: number | null; items_label: string }

export const assistantApi = {
  settings: () => request<{ settings: AssistantSettings; widgets: BriefingWidget[]; email_categories: string[] }>('/widgets/assistant/settings'),
  // The whole prompt with these (unsaved) settings
  preview: (settings: AssistantSettings) =>
    request<{ prompt: string }>('/widgets/assistant/preview', { method: 'POST', ...json(settings) }),
  chatStatus: () => request<{ enabled: boolean; usage: ChatUsage; models: ChatModel[] }>('/widgets/assistant/chat/status'),
  chat: (messages: ChatMessage[]) => request<ChatReply>('/widgets/assistant/chat', { method: 'POST', ...json({ messages }) }),
  save: (settings: AssistantSettings) =>
    request<{ settings: AssistantSettings }>('/widgets/assistant/settings', { method: 'PUT', ...json(settings) }),
}
