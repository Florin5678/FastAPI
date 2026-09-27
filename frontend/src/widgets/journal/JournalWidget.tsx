import type { JournalPrompt } from '../../api'
import type { WidgetProps } from '../types'
import { JournalComposer } from './JournalComposer'
import './journal.css'

export type JournalData = {
  day: string
  prompt: JournalPrompt | null
  today: { id: number; mood: string | null; prompt_text: string | null; created_at: string }[]
  total: number
  streak: number
}

export function JournalWidget({ data, reload, actions }: WidgetProps<JournalData>) {
  return (
    <div className="journal-widget">
      {/* keyed by day so a new day starts with a fresh composer */}
      <JournalComposer key={data.day} initialPrompt={data.prompt} onSaved={reload} compact />

      <div className="journal-foot">
        <span className="muted small">
          {data.streak > 0 && <>🔥 {data.streak} day{data.streak === 1 ? '' : 's'} · </>}
          {data.today.length > 0
            ? <>Today: {data.today.map((e) => e.mood || '•').join(' ')}</>
            : <>{data.total} entr{data.total === 1 ? 'y' : 'ies'}</>}
        </span>
        <button className="link" onClick={() => actions.goTo('journal')}>Open journal →</button>
      </div>
    </div>
  )
}
