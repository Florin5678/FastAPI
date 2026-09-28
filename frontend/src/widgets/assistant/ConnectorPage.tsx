import { useEffect, useState } from 'react'
import { connectorApi, type ConnectorStatus } from '../../api'
import './assistant.css'

function ago(iso: string | null): string {
  if (!iso) return 'not used yet'
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`
  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' })
}

function when(iso: string): string {
  return new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// The dashboard as a Claude connector: how to connect, who is connected (with
// Disconnect), and every change Claude made (with Undo)
export function ConnectorPage() {
  const [status, setStatus] = useState<{ version: number; data?: ConnectorStatus; error?: string } | null>(null)
  const [version, setVersion] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let cancelled = false
    connectorApi.status()
      .then((data) => { if (!cancelled) setStatus({ version, data }) })
      .catch((err) => { if (!cancelled) setStatus({ version, error: (err as Error).message }) })
    return () => { cancelled = true }
  }, [version])

  const data = status?.data
  const act = async (key: string, action: () => Promise<unknown>, done: string) => {
    setBusy(key)
    setMessage(null)
    try {
      await action()
      setMessage({ text: done })
      setVersion((v) => v + 1)
    } catch (err) {
      setMessage({ text: (err as Error).message, error: true })
    } finally {
      setBusy(null)
    }
  }

  const copyUrl = async () => {
    if (!data) return
    try {
      await navigator.clipboard.writeText(data.url)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section className="connector-page">
      <div className="section-head">
        <h2>Claude connector</h2>
      </div>
      {status?.error && <p className="error-text">{status.error}</p>}
      {!status && <p className="muted">Loading…</p>}
      {message && <p className={message.error ? 'error-text' : 'connector-message'}>{message.text}</p>}

      {data && (
        <>
          <div className="card connector-card">
            <h3>Connect Claude to your dashboard</h3>
            <p>
              Claude can then read your dashboard and make changes you ask for, in any chat on claude.ai, the Claude
              apps or Claude Code. It uses your Claude subscription (no extra cost). Your journal is never shared.
            </p>
            <div className="connector-url">
              <code>{data.url}</code>
              <button className="button ghost small-button" onClick={copyUrl}>{copied ? 'Copied' : 'Copy'}</button>
            </div>
            <ol className="connector-steps">
              <li><b>claude.ai / Claude apps:</b> Settings → Connectors → Add custom connector → paste the URL → Add → Connect, then sign in and choose Allow.</li>
              <li><b>Claude Code:</b> run <code>claude mcp add --transport http dashboard {data.url}</code>, then <code>/mcp</code> in Claude Code to sign in.</li>
            </ol>
          </div>

          <div className="card connector-card">
            <h3>Connected</h3>
            {data.connections.length === 0 ? (
              <p className="muted small">Nothing connected yet.</p>
            ) : (
              <ul className="item-list">
                {data.connections.map((c) => (
                  <li key={c.grant_id}>
                    <span className="item-name">
                      <b>{c.app}</b>
                      <span className="muted small"> · connected {when(c.connected_at)} · last used {ago(c.last_used_at)}</span>
                    </span>
                    <button className="button ghost small-button" disabled={busy !== null}
                      onClick={() => { if (confirm(`Disconnect ${c.app}? It will need to sign in again.`)) void act(c.grant_id, () => connectorApi.revoke(c.grant_id), `${c.app} disconnected.`) }}>
                      Disconnect
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="card connector-card">
            <h3>Changes made by Claude</h3>
            {data.changes.length === 0 ? (
              <p className="muted small">None yet. Everything Claude adds, edits or deletes shows up here and can be undone.</p>
            ) : (
              <ul className="item-list">
                {data.changes.map((c) => (
                  <li key={c.id} className={c.undone_at ? 'connector-undone' : ''}>
                    <span className="item-name">
                      {c.summary}
                      <span className="muted small"> · {when(c.at)}{c.undone_at && ' · undone'}</span>
                    </span>
                    {c.can_undo && (
                      <button className="button ghost small-button" disabled={busy !== null}
                        onClick={() => void act(`c${c.id}`, () => connectorApi.undo(c.id), `Undone: ${c.summary}`)}>
                        {busy === `c${c.id}` ? 'Undoing…' : 'Undo'}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  )
}
