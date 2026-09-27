import { useEffect, useState } from 'react'
import { api, type Digest as DigestData } from '../api'
import { categoryLabel } from '../format'
import { EmailCard } from './EmailCard'

type Props = { refreshKey: number; onOpen: (id: number) => void }

export function Digest({ refreshKey, onOpen }: Props) {
  const [data, setData] = useState<DigestData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setError(null)
    api.digest().then(setData).catch((err) => setError(err.message))
  }, [refreshKey])

  if (error) return <p className="error-text">Couldn't load today's digest: {error}</p>
  if (!data) return <p className="muted">Loading…</p>

  // Biggest categories first, unsummarized last
  const groups = Object.entries(data.categories).sort(([a, x], [b, y]) => {
    if (a === 'unsummarized') return 1
    if (b === 'unsummarized') return -1
    return y.length - x.length
  })

  const today = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <section>
      <div className="section-head">
        <h2>{today}</h2>
        <span className="muted">{data.total} email{data.total === 1 ? '' : 's'} today</span>
      </div>

      {data.total === 0 && (
        <div className="empty">Nothing yet today. New mail syncs every 10 minutes, or press <b>Sync now</b>.</div>
      )}

      {groups.length > 0 && (
        <div className="chips static">
          {groups.map(([category, emails]) => (
            <a key={category} className={`chip cat-${category}`} href={`#cat-${category}`}>
              {categoryLabel(category)} <span className="count">{emails.length}</span>
            </a>
          ))}
        </div>
      )}

      {groups.map(([category, emails]) => (
        <div key={category} className="group" id={`cat-${category}`}>
          <h3>{categoryLabel(category)}</h3>
          <div className="card-list">
            {emails.map((email) => <EmailCard key={email.id} email={email} onOpen={onOpen} />)}
          </div>
        </div>
      ))}
    </section>
  )
}
