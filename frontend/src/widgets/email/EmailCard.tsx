import type { EmailItem } from '../../api'
import { categoryLabel, formatTime, senderName } from '../../lib/format'

export function CategoryBadge({ category }: { category: string | null }) {
  return <span className={`badge cat-${category ?? 'unsummarized'}`}>{categoryLabel(category)}</span>
}

export function EmailCard({ email, onOpen }: { email: EmailItem; onOpen: (id: number) => void }) {
  return (
    <button className="email-card" onClick={() => onOpen(email.id)}>
      <div className="email-card-top">
        <span className="sender">{senderName(email.sender)}</span>
        <span className="time">{formatTime(email.timestamp)}</span>
      </div>
      <div className="subject">{email.subject || '(no subject)'}</div>
      <p className="summary">{email.summary ?? email.snippet}</p>
      <CategoryBadge category={email.category} />
    </button>
  )
}
