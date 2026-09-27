import { categoryLabel, formatTime, senderName } from '../../lib/format'
import { CategoryBadge } from './EmailCard'
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
}

export function EmailSummaryWidget({ data, actions }: WidgetProps<EmailSummaryData>) {
  // Only real categories: emails without a summary yet don't get a chip
  const categories = data.categories.filter((c) => c.category !== 'unsummarized')

  return (
    <div className="email-widget">
      <button className="stat" onClick={() => actions.goTo('today')}>
        <span className="stat-number">{data.today_total}</span>
        <span className="stat-label">email{data.today_total === 1 ? '' : 's'} today</span>
      </button>

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
    </div>
  )
}
