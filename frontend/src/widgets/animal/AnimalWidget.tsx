import { useEffect, useState } from 'react'
import type { WidgetProps } from '../types'
import './animal.css'

type AnimalDetails = {
  wikipedia_title: string | null
  description: string | null
  extract: string | null
  image: string | null
  image_2x: string | null
  link: string | null
}

export type AnimalData = { day: string; name: string; summary_url: string } & (
  | ({ loaded: true } & AnimalDetails)
  | { loaded: false } // the server couldn't reach Wikipedia: the browser loads it
)

type WikiSummary = {
  title?: string
  description?: string
  extract?: string
  thumbnail?: { source: string }
  originalimage?: { width: number }
  content_urls?: { desktop?: { page?: string } }
}

// Same rule as the backend: Wikimedia only serves standard thumbnail widths
function thumbnail(summary: WikiSummary, width: number): string | null {
  const src = summary.thumbnail?.source
  if (!src) return null
  if ((summary.originalimage?.width ?? 0) < width || !/\/\d+px-/.test(src)) return src
  return src.replace(/\/\d+px-/, `/${width}px-`)
}

function fromWikipedia(summary: WikiSummary): AnimalDetails {
  return {
    wikipedia_title: summary.title ?? null,
    description: summary.description ?? null,
    extract: summary.extract ?? null,
    image: thumbnail(summary, 500),
    image_2x: thumbnail(summary, 960),
    link: summary.content_urls?.desktop?.page ?? null,
  }
}

export function AnimalWidget({ data }: WidgetProps<AnimalData>) {
  const [fallback, setFallback] = useState<AnimalDetails | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (data.loaded) return
    setFallback(null)
    setError(null)
    fetch(data.summary_url, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((summary: WikiSummary) => setFallback(fromWikipedia(summary)))
      .catch(() => setError("Couldn't load today's animal from Wikipedia. Try again later."))
  }, [data])

  const details: AnimalDetails | null = data.loaded ? data : fallback

  return (
    <div className="animal-widget">
      {details?.image ? (
        <img
          className="animal-photo"
          src={details.image}
          srcSet={details.image_2x && details.image_2x !== details.image ? `${details.image} 1x, ${details.image_2x} 2x` : undefined}
          alt={data.name}
        />
      ) : (
        <div className="animal-photo" aria-hidden />
      )}
      <div className="animal-text">
        <h3 className="animal-name">{data.name}</h3>
        {details?.description && <p className="animal-description">{details.description}</p>}
        {details?.extract && <p className="animal-extract">{details.extract}</p>}
        {!details && !error && <p className="muted small">Loading from Wikipedia…</p>}
        {error && <p className="error-text small">{error}</p>}
      </div>
      <div className="animal-foot">
        {details?.link && (
          <a className="link" href={details.link} target="_blank" rel="noopener noreferrer">More on Wikipedia →</a>
        )}
        <span className="muted small">Photo &amp; text: Wikipedia</span>
      </div>
    </div>
  )
}
