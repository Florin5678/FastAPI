import type { WidgetProps } from '../types'
import './animal.css'

export type AnimalData = {
  day: string
  name: string
  wikipedia_title: string | null
  description: string | null
  extract: string | null
  image: string | null
  image_2x: string | null
  link: string | null
}

export function AnimalWidget({ data }: WidgetProps<AnimalData>) {
  return (
    <div className="animal-widget">
      {data.image && (
        <img
          className="animal-photo"
          src={data.image}
          srcSet={data.image_2x && data.image_2x !== data.image ? `${data.image} 1x, ${data.image_2x} 2x` : undefined}
          alt={data.name}
          loading="lazy"
        />
      )}
      <div className="animal-text">
        <h3 className="animal-name">{data.name}</h3>
        {data.description && <p className="animal-description">{data.description}</p>}
        {data.extract && <p className="animal-extract">{data.extract}</p>}
      </div>
      <div className="animal-foot">
        {data.link && (
          <a className="link" href={data.link} target="_blank" rel="noopener noreferrer">More on Wikipedia →</a>
        )}
        <span className="muted small">Photo &amp; text: Wikipedia</span>
      </div>
    </div>
  )
}
