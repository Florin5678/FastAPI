import { useEffect, useState } from 'react'
import { api, type EmailItem } from '../api'
import { formatFullDate } from '../format'
import { CategoryBadge } from './EmailCard'

type Props = { id: number; onClose: () => void }

export function EmailDetail({ id, onClose }: Props) {
  const [email, setEmail] = useState<EmailItem | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setEmail(null)
    api.email(id).then(setEmail).catch((err) => setError(err.message))
  }, [id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="overlay" onClick={onClose}>
      <article className="detail" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        {error && <p className="error-text">{error}</p>}
        {!email && !error && <p className="muted">Loading…</p>}
        {email && (
          <>
            <h2>{email.subject || '(no subject)'}</h2>
            <div className="detail-meta">
              <span>{email.sender}</span>
              <span className="muted">{formatFullDate(email.timestamp)}</span>
            </div>
            <CategoryBadge category={email.category} />
            {email.summary && (
              <div className="summary-box">
                <div className="summary-label">Summary</div>
                <p>{email.summary}</p>
              </div>
            )}
            <div className="body">{email.full_body || email.snippet || '(empty message)'}</div>
            <a
              className="button ghost"
              href={`https://mail.google.com/mail/u/0/#all/${email.gmail_id}`}
              target="_blank"
              rel="noreferrer"
            >
              Open in Gmail ↗
            </a>
          </>
        )}
      </article>
    </div>
  )
}
