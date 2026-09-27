import { useEffect, useState } from 'react'
import { api, type EmailItem } from '../../api'
import { CATEGORIES, categoryLabel } from '../../lib/format'
import { EmailCard } from './EmailCard'

const PAGE_SIZE = 30

type Props = { refreshKey: number; onOpen: (id: number) => void; initialCategory?: string }

export function Inbox({ refreshKey, onOpen, initialCategory }: Props) {
  const [category, setCategory] = useState<string | undefined>(initialCategory)
  const [emails, setEmails] = useState<EmailItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.emails({ category, limit: PAGE_SIZE })
      .then((data) => {
        setEmails(data.emails)
        setTotal(data.total)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [category, refreshKey])

  const loadMore = () => {
    setLoading(true)
    api.emails({ category, limit: PAGE_SIZE, offset: emails.length })
      .then((data) => setEmails((prev) => [...prev, ...data.emails]))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  return (
    <section>
      <div className="section-head">
        <h2>Inbox</h2>
        <span className="muted">{total} stored email{total === 1 ? '' : 's'}</span>
      </div>

      <div className="chips" role="group" aria-label="Filter by category">
        <button className={category === undefined ? 'chip active' : 'chip'} onClick={() => setCategory(undefined)}>All</button>
        {CATEGORIES.map((c) => (
          <button key={c} className={category === c ? `chip cat-${c} active` : `chip cat-${c}`} onClick={() => setCategory(c)}>
            {categoryLabel(c)}
          </button>
        ))}
      </div>

      {error && <p className="error-text">Couldn't load emails: {error}</p>}
      {!loading && !error && emails.length === 0 && (
        <div className="empty">{category ? `No ${categoryLabel(category).toLowerCase()} emails yet.` : 'No emails stored yet — press Sync now.'}</div>
      )}

      <div className="card-list">
        {emails.map((email) => <EmailCard key={email.id} email={email} onOpen={onOpen} />)}
      </div>

      {loading && <p className="muted">Loading…</p>}
      {!loading && emails.length < total && (
        <button className="button load-more" onClick={loadMore}>Load more</button>
      )}
    </section>
  )
}
