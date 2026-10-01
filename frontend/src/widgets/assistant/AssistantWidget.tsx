import { useState } from 'react'
import type { WidgetProps } from '../types'
import { AssistantSettingsDialog } from './AssistantSettingsDialog'
import { ChatPanel } from './ChatPanel'
import { fillWhen, type AssistantData } from './prompt'
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

  // The "Claude prompt" from Settings; by default it asks Claude to fetch the briefing via the connector
  const openInClaude = () => {
    // Open synchronously (inside the click) so pop-up blockers allow it
    window.open(`https://claude.ai/new?q=${encodeURIComponent(data.claude_prompt)}`, '_blank', 'noopener')
    setNote('Opened Claude: it fetches your full briefing through the My Dashboard connector (switch it on in that chat if asked).')
  }

  const copyBriefing = async () => {
    setNote(await copy(fillWhen(data.prompt)) ? 'Full briefing copied: paste it into any chat.' : "Couldn't copy (the browser blocked it).")
  }

  return (
    <div className="assistant-widget">
      <div className="assistant-buttons">
        <button className="button ghost" onClick={copyBriefing}>Copy briefing</button>
        <button className="button primary" onClick={openInClaude}>Open in Claude ↗</button>
        <button className="button ghost assistant-settings-button" onClick={() => setSettingsOpen(true)} aria-label="Assistant settings" title="Settings: what the prompt says and includes">⚙</button>
      </div>
      <button className="button ghost assistant-chat-button" onClick={() => setChatOpen(true)}>💬 Chat with your dashboard</button>
      {note
        ? <p className="small assistant-note">{note}</p>
        : <button className="assistant-link small" onClick={() => actions.goTo('connector')}>Claude connector: let Claude read &amp; edit your dashboard →</button>}
      {chatOpen && <ChatPanel onClose={(changed) => { setChatOpen(false); if (changed) actions.refresh() }} />}
      {settingsOpen && (
        <AssistantSettingsDialog onSaved={() => { setNote('Settings saved.'); reload() }} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  )
}
