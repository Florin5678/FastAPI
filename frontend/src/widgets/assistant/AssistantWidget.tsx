import { useState } from 'react'
import type { WidgetProps } from '../types'
import { AssistantSettingsDialog } from './AssistantSettingsDialog'
import { ChatPanel } from './ChatPanel'
import { buildPrompt, MAX_URL_PROMPT, type AssistantData } from './prompt'
import './assistant.css'

export type { AssistantData } from './prompt'

export function AssistantWidget({ data, actions, reload }: WidgetProps<AssistantData>) {
  const [note, setNote] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)

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
        <button className="button primary" onClick={briefMe}>Open in Claude ↗</button>
        <button className="button ghost assistant-settings-button" onClick={() => setSettingsOpen(true)} aria-label="Assistant settings" title="Settings: what the prompt says and includes">⚙</button>
      </div>
      <button className="button ghost assistant-chat-button" onClick={() => setChatOpen(true)}>💬 Chat with your dashboard</button>
      {note
        ? <p className="small assistant-note">{note}</p>
        : <button className="assistant-link small" onClick={() => actions.goTo('connector')}>Claude connector: let Claude read &amp; edit your dashboard →</button>}
      {chatOpen && <ChatPanel onClose={(changed) => { setChatOpen(false); if (changed) actions.refresh() }} />}
      {settingsOpen && (
        <AssistantSettingsDialog data={data} onSaved={() => { setNote('Settings saved.'); reload() }} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  )
}
