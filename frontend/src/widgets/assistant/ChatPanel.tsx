import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { assistantApi, connectorApi, type ChatMessage, type ChatReply, type ChatUsage } from '../../api'
import './assistant.css'

// One turn as shown on screen: the text plus, for Claude's replies, what it changed
type Turn = ChatMessage & { changes?: ChatReply['changes']; failed?: string[] }

const STORAGE_KEY = 'assistant-chat'
const SUGGESTIONS = [
  'What does my day look like?',
  'How am I doing on my nutrition goals this week?',
  'Remind me tomorrow at 9 to reply to the registrar',
  'Where did most of my money go this month?',
]

function loadTurns(): Turn[] {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]') as Turn[]
  } catch {
    return []
  }
}

// The Assistant's AI chat: Claude with the whole dashboard (except the journal) as
// context, able to look things up and make changes. Uses the paid Claude API, capped
// by the monthly budget in the Assistant settings. Opens as a side panel over the
// dashboard; the conversation is kept (per browser tab) when it's closed.
export function ChatPanel({ onClose }: { onClose: (changed: boolean) => void }) {
  const [turns, setTurns] = useState<Turn[]>(loadTurns)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<{ enabled: boolean; usage: ChatUsage } | null>(null)
  const [undone, setUndone] = useState<Set<number>>(new Set())
  const [changed, setChanged] = useState(false) // Claude changed something: refresh the dashboard on close
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    assistantApi.chatStatus()
      .then((s) => { if (!cancelled) setStatus(s) })
      .catch((err) => { if (!cancelled) setError((err as Error).message) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-40)))
    } catch {
      // private mode / storage full: the chat just isn't kept across reloads
    }
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns, sending])

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || sending) return
    const next: Turn[] = [...turns, { role: 'user', content }]
    setTurns(next)
    setDraft('')
    setSending(true)
    setError(null)
    try {
      const r = await assistantApi.chat(next.map(({ role, content }) => ({ role, content })))
      setTurns([...next, {
        role: 'assistant', content: r.reply, changes: r.changes,
        failed: r.actions.filter((a) => a.error).map((a) => a.tool),
      }])
      setStatus((s) => (s ? { ...s, usage: r.usage } : s))
      if (r.changes.length > 0) setChanged(true)
    } catch (err) {
      setError((err as Error).message)
      setTurns(turns) // take the unanswered question back out, so it can be sent again
      setDraft(content)
    } finally {
      setSending(false)
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void send(draft) }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(draft) }
  }

  const undo = async (id: number) => {
    try {
      await connectorApi.undo(id)
      setUndone((u) => new Set(u).add(id))
      setChanged(true)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const usage = status?.usage
  const overBudget = usage ? usage.cost >= usage.budget : false

  // Refresh the dashboard on close if Claude changed something while the panel was open
  const close = useCallback(() => onClose(changed), [onClose, changed])
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close])

  return createPortal(
    <div className="overlay" onClick={close}>
    <section className="chat-page chat-panel" role="dialog" aria-modal="true" aria-label="Chat with your dashboard" onClick={(e) => e.stopPropagation()}>
      <div className="section-head">
        <h2>Chat with your dashboard</h2>
        <div className="chat-head-actions">
          {turns.length > 0 && <button className="button ghost" onClick={() => { setTurns([]); setUndone(new Set()) }}>New chat</button>}
          <button className="icon-button" onClick={close} aria-label="Close">✕</button>
        </div>
      </div>

      {status && !status.enabled && (
        <div className="card"><p>The AI chat needs a Claude API key. Add <code>ANTHROPIC_API_KEY</code> in Render → your service → Environment.</p></div>
      )}

      <div className="chat-log card" aria-live="polite">
        {turns.length === 0 && (
          <div className="chat-empty">
            <p>Ask anything about your dashboard, or ask me to change something. I can see everything except your journal, and every change can be undone.</p>
            <div className="chips compact">
              {SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)} disabled={sending || !status?.enabled}>{s}</button>)}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`chat-turn ${t.role}`}>
            <div className="chat-bubble">{t.content}</div>
            {t.changes && t.changes.length > 0 && (
              <ul className="chat-changes">
                {t.changes.map((c) => (
                  <li key={c.id} className={undone.has(c.id) ? 'undone' : ''}>
                    <span>✓ {c.summary}</span>
                    {undone.has(c.id)
                      ? <span className="muted small">undone</span>
                      : <button className="button ghost small-button" onClick={() => undo(c.id)}>Undo</button>}
                  </li>
                ))}
              </ul>
            )}
            {t.failed && t.failed.length > 0 && <p className="muted small">Some lookups failed ({t.failed.join(', ')}); the answer may be incomplete.</p>}
          </div>
        ))}
        {sending && <div className="chat-turn assistant"><div className="chat-bubble chat-thinking">Thinking…</div></div>}
        <div ref={endRef} />
      </div>

      {error && <p className="error-text">{error}</p>}

      <form className="chat-input" onSubmit={submit}>
        <textarea rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} maxLength={6000}
          placeholder={overBudget ? "This month's budget is used up (raise it in ⚙ Settings)" : 'Message your dashboard… (Enter to send, Shift+Enter for a new line)'}
          disabled={!status?.enabled} aria-label="Message" />
        <button className="button primary" type="submit" disabled={!draft.trim() || sending || !status?.enabled}>Send</button>
      </form>
      {usage && (
        <p className="muted small chat-usage">
          {usage.model_label} · this month ${usage.cost.toFixed(2)} of ${usage.budget.toFixed(2)} ({usage.requests} request{usage.requests === 1 ? '' : 's'}) · change model or budget in the Assistant's ⚙ Settings
        </p>
      )}
    </section>
    </div>,
    document.body,
  )
}
