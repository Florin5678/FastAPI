import { useState } from 'react'
import { timeAgo } from '../format'
import type { WidgetProps } from './types'

export type NewsData = {
  topic: string
  topics: string[]
  sources: string[]
  unavailable: string[]
  items: { title: string; link: string; source: string; published: string | null; excerpt: string }[]
}

export function NewsWidget({ data, updateSettings }: WidgetProps<NewsData>) {
  const [switching, setSwitching] = useState<string | null>(null)

  const pick = async (topic: string) => {
    if (topic === data.topic) return
    setSwitching(topic)
    await updateSettings({ topic })
    setSwitching(null)
  }

  return (
    <div className="news-widget">
      <div className="chips compact news-topics" role="group" aria-label="Topic">
        {data.topics.map((topic) => (
          <button
            key={topic}
            className={(switching ?? data.topic) === topic ? 'chip active' : 'chip'}
            aria-pressed={data.topic === topic}
            disabled={switching !== null}
            onClick={() => pick(topic)}
          >
            {topic}
          </button>
        ))}
      </div>

      <ul className="news-list">
        {data.items.map((item) => (
          <li key={item.link}>
            <a href={item.link} target="_blank" rel="noopener noreferrer" className="news-item">
              <span className="news-meta">{item.source} · {timeAgo(item.published)}</span>
              <span className="news-title">{item.title}</span>
              {item.excerpt && <span className="news-excerpt">{item.excerpt}</span>}
            </a>
          </li>
        ))}
      </ul>

      <p className="muted small">
        From {data.sources.join(', ')}
        {data.unavailable.length > 0 && ` · ${data.unavailable.join(', ')} unavailable right now`}
      </p>
    </div>
  )
}
