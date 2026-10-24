import { useState } from 'react'
import { api } from '../../api'
import { categoryLabel, formatTime, senderName } from '../../lib/format'
import { CategoryBadge } from './EmailCard'
import { EmailSettingsDialog } from './EmailSettingsDialog'
import type { WidgetProps } from '../types'
import './email.css'

export type EmailSummaryData = {
  today_total: number
  categories: { category: string; count: number }[]
  latest: {
    id: number
    subject: string | null
    sender: string | null
    timestamp: string | null
    category: string | null
    summary: string | null
    snippet: string | null
  }[]
  summaries_enabled: boolean
  last_new_mail_at: string | null
  hidden_today: number // today's emails in categories hidden in the settings
}

export function EmailSummaryWidget({ data, actions, settings, updateSettings }: WidgetProps<EmailSummaryData>) {
  const [syncing, setSyncing] = useState(false)
  const [status, setStatus] = useState<{ text: string; error?: boolean } | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Only real categories: emails without a summary yet don't get a chip
  const categories = data.categories.filter((c) => c.category !== 'unsummarized')

  // Fetch new mail from Gmail (and summarize it), then refresh the dashboard
  const sync = async () => {
    setSyncing(true)
    setStatus(null)
    try {
      const synced = await api.sync()
      let text = synced.synced === 0 ? 'No new emails' : `${synced.synced} new email${synced.synced === 1 ? '' : 's'}`
      if (data.summaries_enabled && synced.synced > 0) {
        const summarized = await api.summarize()
        text += `, ${summarized.summarized} summarized`
        if (summarized.remaining) text += ` (${summarized.remaining} still waiting)`
      }
      setStatus({ text })
      actions.refresh()
    } catch (err) {
      setStatus({ text: `Sync failed: ${(err as Error).message}`, error: true })
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="email-widget">
      <div className="email-head">
        <button className="stat" onClick={() => actions.goTo('today')}>
          <span className="stat-number">{data.today_total}</span>
          <span className="stat-label">email{data.today_total === 1 ? '' : 's'} today</span>
        </button>
        <span className="email-head-actions">
          <button className="button primary small-button" onClick={sync} disabled={syncing}>{syncing ? 'Syncing…' : 'Sync now'}</button>
          <button className="icon-button" onClick={() => setSettingsOpen(true)} aria-label="Email settings" title="Settings: categories to show">⚙</button>
        </span>
      </div>
      {status && <p className={status.error ? 'error-text small' : 'muted small'} role="status">{status.text}</p>}
      {data.hidden_today > 0 && (
        <p className="muted small">{data.hidden_today} more today in hidden categories</p>
      )}

      {categories.length > 0 && (
        <div className="chips compact">
          {categories.map((c) => (
            <button
              key={c.category}
              className={`chip cat-${c.category}`}
              onClick={() => actions.goTo('inbox', { category: c.category })}
            >
              {categoryLabel(c.category)} <span className="count">{c.count}</span>
            </button>
          ))}
        </div>
      )}

      <div className="widget-subhead">Latest</div>
      {data.latest.length === 0 ? (
        <p className="muted small">No emails synced yet.</p>
      ) : (
        <ul className="mini-list">
          {data.latest.map((e) => (
            <li key={e.id}>
              <button className="mini-item" onClick={() => actions.openEmail(e.id)}>
                <span className="mini-top">
                  <span className="sender">{senderName(e.sender)}</span>
                  <span className="time">{formatTime(e.timestamp)}</span>
                </span>
                <span className="mini-subject">{e.subject || '(no subject)'}</span>
                <span className="mini-summary">{e.summary ?? e.snippet}</span>
                {e.category && <CategoryBadge category={e.category} />}
              </button>
            </li>
          ))}
        </ul>
      )}

      {!data.summaries_enabled && (
        <p className="muted small">Summaries are off (no <code>ANTHROPIC_API_KEY</code> on Render).</p>
      )}

      <div className="widget-footer">
        <button className="link" onClick={() => actions.goTo('today')}>Today's digest →</button>
        <button className="link" onClick={() => actions.goTo('inbox')}>Inbox →</button>
      </div>
      {settingsOpen && <EmailSettingsDialog settings={settings} onSave={updateSettings} onClose={() => setSettingsOpen(false)} />}
    </div>
  )
}
