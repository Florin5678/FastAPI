import { useState, type FormEvent } from 'react'
import { journalApi, localDate, type JournalEntry, type JournalPrompt } from '../../api'

export const QUICK_MOODS = ['😄', '🙂', '😐', '😔', '😢', '😠', '😰', '😴', '🥰', '💪']

type Props = {
  initialPrompt: JournalPrompt | null
  onSaved: (entry: JournalEntry) => void
  compact?: boolean
}

// Write a new entry: optional prompt (refresh / remove), optional mood emoji, text.
export function JournalComposer({ initialPrompt, onSaved, compact }: Props) {
  const [prompt, setPrompt] = useState<JournalPrompt | null>(initialPrompt)
  const [loadingPrompt, setLoadingPrompt] = useState(false)
  const [mood, setMood] = useState<string | null>(null)
  const [customMood, setCustomMood] = useState('')
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const newPrompt = async () => {
    setLoadingPrompt(true)
    setError(null)
    try {
      setPrompt(await journalApi.prompt(prompt?.id))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoadingPrompt(false)
    }
  }

  const pickMood = (emoji: string) => {
    setMood(mood === emoji ? null : emoji)
    setCustomMood('')
  }

  const typeMood = (value: string) => {
    setCustomMood(value)
    setMood(value.trim() || null)
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!body.trim()) return
    setSaving(true)
    setError(null)
    try {
      const entry = await journalApi.add({ day: localDate(), body, prompt_id: prompt?.id ?? null, mood })
      setBody('')
      setMood(null)
      setCustomMood('')
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      onSaved(entry)
      // Every new entry starts with a fresh prompt
      setPrompt(await journalApi.prompt(entry.prompt_id ?? prompt?.id).catch(() => null))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className={compact ? 'journal-composer compact' : 'journal-composer'} onSubmit={save}>
      {prompt ? (
        <div className="journal-prompt">
          <p className="prompt-text">{prompt.text}</p>
          <div className="prompt-foot">
            <span className="prompt-tools">
              <button
                type="button"
                className={loadingPrompt ? 'icon-button spinning' : 'icon-button'}
                onClick={newPrompt}
                disabled={loadingPrompt}
                aria-label="Show another prompt"
                title="Another prompt"
              >↻</button>
              <button type="button" className="icon-button" onClick={() => setPrompt(null)} aria-label="Remove prompt and write freely" title="Write without a prompt">✕</button>
            </span>
          </div>
        </div>
      ) : (
        <button type="button" className="link add-prompt" onClick={newPrompt} disabled={loadingPrompt}>
          + Add a prompt
        </button>
      )}

      <div className="mood-row" role="group" aria-label="Mood (optional)">
        {QUICK_MOODS.map((emoji) => (
          <button
            key={emoji}
            type="button"
            className={mood === emoji && !customMood ? 'mood active' : 'mood'}
            aria-pressed={mood === emoji && !customMood}
            onClick={() => pickMood(emoji)}
          >{emoji}</button>
        ))}
        <input
          className={customMood ? 'mood-custom active' : 'mood-custom'}
          value={customMood}
          onChange={(e) => typeMood(e.target.value)}
          maxLength={16}
          placeholder="any 🙃"
          aria-label="Any emoji for your mood"
        />
      </div>

      <textarea
        className="journal-body"
        rows={compact ? 4 : 7}
        placeholder={prompt ? 'Write your answer…' : 'Write anything…'}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        maxLength={20000}
        aria-label="Journal entry"
      />

      {error && <p className="error-text small">{error}</p>}
      <div className="composer-actions">
        {saved && <span className="saved-note">Saved ✓</span>}
        <button type="submit" className="button primary small-button" disabled={saving || !body.trim()}>
          {saving ? 'Saving…' : 'Save entry'}
        </button>
      </div>
    </form>
  )
}
