import { useState } from 'react'
import { languageApi, type ReviewGrade } from '../../api'
import type { WidgetProps } from '../types'
import './language.css'

export type LanguageData = {
  language: string
  languages: string[]
  speech_lang: string // BCP 47 tag for the browser's text-to-speech, e.g. "da-DK"
  today: string
  card: { word: string; meaning: string; is_new: boolean } | null
  due: number
  new_left: number
  learned: number
  seen: number
  total: number
}

const GRADES: { grade: ReviewGrade; label: string; hint: string }[] = [
  { grade: 'again', label: 'Again', hint: "Didn't know it: see it again today" },
  { grade: 'good', label: 'Good', hint: 'Knew it' },
  { grade: 'easy', label: 'Easy', hint: 'Knew it instantly: wait longer' },
]

function speak(text: string, lang: string) {
  if (!('speechSynthesis' in window)) return
  const utterance = new SpeechSynthesisUtterance(text.replace(/[¿?¡!]/g, ''))
  utterance.lang = lang
  utterance.rate = 0.9
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(utterance)
}

export function LanguageWidget({ data, reload, updateSettings }: WidgetProps<LanguageData>) {
  // Which card's answer is showing; a new card hides it without any reset step
  const [revealedWord, setRevealedWord] = useState<string | null>(null)
  const revealed = data.card !== null && revealedWord === `${data.language}:${data.card.word}`
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window

  const grade = async (g: ReviewGrade) => {
    if (!data.card) return
    setBusy(true)
    setError(null)
    try {
      await languageApi.review({ language: data.language, word: data.card.word, grade: g, day: data.today })
      reload()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="language-widget">
      <div className="language-head">
        <div className="segmented" role="group" aria-label="Language">
          {data.languages.map((name) => (
            <button
              key={name}
              className={data.language === name ? 'active' : ''}
              aria-pressed={data.language === name}
              onClick={() => data.language !== name && updateSettings({ language: name })}
            >
              {name}
            </button>
          ))}
        </div>
        <span className="muted small">{data.due} due · {data.new_left} new</span>
      </div>

      {data.card ? (
        <div className="flashcard">
          {data.card.is_new && <span className="flashcard-new">New word</span>}
          <div className="flashcard-word">
            <span>{data.card.word}</span>
            {canSpeak && (
              <button className="icon-button" onClick={() => speak(data.card!.word, data.speech_lang)} aria-label={`Say "${data.card.word}"`} title="Listen">🔊</button>
            )}
          </div>
          {revealed ? (
            <>
              <div className="flashcard-meaning">{data.card.meaning}</div>
              <div className="flashcard-grades">
                {GRADES.map((g) => (
                  <button key={g.grade} className={`button grade-${g.grade}`} onClick={() => grade(g.grade)} disabled={busy} title={g.hint}>
                    {g.label}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <button className="button primary" onClick={() => setRevealedWord(`${data.language}:${data.card!.word}`)}>Show answer</button>
          )}
        </div>
      ) : (
        <div className="flashcard done">
          <span className="flashcard-done-icon" aria-hidden>🎉</span>
          <strong>All done for today</strong>
          <span className="muted small">New words and reviews will be waiting tomorrow.</span>
        </div>
      )}
      {error && <p className="error-text small">{error}</p>}

      <div className="language-progress">
        <span className="bar" role="progressbar" aria-label="Words learned" aria-valuemin={0} aria-valuemax={data.total} aria-valuenow={data.learned}>
          <span className="bar-fill done" style={{ width: `${(data.learned / Math.max(1, data.total)) * 100}%` }} />
        </span>
        <span className="muted small">{data.learned} learned · {data.seen} seen · {data.total} words</span>
      </div>
    </div>
  )
}
