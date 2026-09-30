import { useEffect, useState } from 'react'
import { assistantApi, type AssistantSettings, type BriefingWidget, type ChatModel, type ChatUsage } from '../../api'
import { Dialog } from '../../components/Dialog'
import { buildPrompt, composeInstructions, type AssistantData } from './prompt'

type Props = { data: AssistantData; onSaved: () => void; onClose: () => void }

// Everything that goes into the prompt "Open in Claude" / "Copy briefing" send to Claude:
// opening text, extra instructions (switchable), which widgets
// are included (and how many items), and the question at the end. Saved per user.
export function AssistantSettingsDialog({ data, onSaved, onClose }: Props) {
  const [settings, setSettings] = useState<AssistantSettings | null>(null)
  const [widgets, setWidgets] = useState<BriefingWidget[]>([])
  const [models, setModels] = useState<ChatModel[]>([])
  const [usage, setUsage] = useState<ChatUsage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    assistantApi.settings()
      .then((r) => { if (!cancelled) { setSettings(r.settings); setWidgets(r.widgets) } })
      .catch((err) => { if (!cancelled) setError((err as Error).message) })
    assistantApi.chatStatus()
      .then((r) => { if (!cancelled) { setModels(r.models); setUsage(r.usage) } })
      .catch(() => undefined) // the chat section just shows fewer details
    return () => { cancelled = true }
  }, [])

  const update = (changes: Partial<AssistantSettings>) => setSettings((s) => (s ? { ...s, ...changes } : s))

  const save = async () => {
    if (!settings) return
    setSaving(true)
    setError(null)
    try {
      await assistantApi.save({
        ...settings,
        extras: settings.extras.filter((e) => e.name.trim() && e.text.trim()).map((e) => ({ ...e, name: e.name.trim(), text: e.text.trim() })),
      })
      onSaved()
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  // Preview with the current (unsaved) wording; the widget sections are as last loaded
  const preview = settings
    ? buildPrompt({ ...data, prompt: { instructions: composeInstructions(settings), default_question: settings.default_question } }).prompt
    : ''

  return (
    <Dialog title="Assistant settings" onClose={onClose} wide>
      {!settings && !error && <p className="muted">Loading…</p>}
      {settings && (
        <div className="assistant-settings">
          <section>
            <h3>Opening</h3>
            <p className="muted small">The first lines of the prompt. <code>{'{when}'}</code> becomes the current day and time.</p>
            <textarea rows={3} value={settings.instructions} maxLength={3000}
              onChange={(e) => update({ instructions: e.target.value })} aria-label="Opening instructions" />
          </section>

          <section>
            <div className="assistant-settings-head">
              <h3>Extra instructions</h3>
              <button type="button" className="button ghost small-button" disabled={settings.extras.length >= 30}
                onClick={() => update({ extras: [...settings.extras, { name: '', text: '', enabled: true }] })}>+ Add</button>
            </div>
            <p className="muted small">Requests added to every brief. Untick to switch one off without deleting it.</p>
            <ul className="assistant-extras">
              {settings.extras.map((extra, i) => (
                <li key={i} className={extra.enabled ? '' : 'off'}>
                  <input type="checkbox" checked={extra.enabled} aria-label={`Use ${extra.name || 'this instruction'}`}
                    onChange={(e) => update({ extras: settings.extras.map((x, j) => (j === i ? { ...x, enabled: e.target.checked } : x)) })} />
                  <div className="assistant-extra-fields">
                    <input type="text" value={extra.name} placeholder="Name, e.g. Meal ideas" maxLength={80} aria-label="Name"
                      onChange={(e) => update({ extras: settings.extras.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                    <textarea rows={2} value={extra.text} placeholder="What Claude should do" maxLength={600} aria-label="Instruction"
                      onChange={(e) => update({ extras: settings.extras.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)) })} />
                  </div>
                  <button type="button" className="icon-button" aria-label={`Delete ${extra.name || 'this instruction'}`} title="Delete"
                    onClick={() => update({ extras: settings.extras.filter((_, j) => j !== i) })}>✕</button>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h3>What the briefing includes</h3>
            <p className="muted small">For widgets with a list, choose how many items are sent. Widgets not on your dashboard are never sent; your journal is never included.</p>
            <ul className="assistant-briefing-rules">
              {widgets.map((w) => {
                const rule = settings.briefing[w.id]
                const mode = rule === 'off' ? 'off' : 'on'
                const setRule = (value: number | 'on' | 'off') => update({ briefing: { ...settings.briefing, [w.id]: value } })
                return (
                  <li key={w.id} className={w.on_dashboard ? '' : 'muted'}>
                    <span>{w.name}{!w.on_dashboard && <span className="small"> (not on dashboard)</span>}</span>
                    <select value={mode} onChange={(e) => setRule(e.target.value === 'off' ? 'off' : (w.default_items ? (typeof rule === 'number' ? rule : w.default_items) : 'on'))}
                      aria-label={`Include ${w.name}`}>
                      <option value="on">Include</option>
                      <option value="off">Leave out</option>
                    </select>
                    {w.default_items !== null && mode === 'on' ? (
                      <label className="assistant-items">
                        <input type="number" min={1} max={50} value={typeof rule === 'number' ? rule : w.default_items}
                          onChange={(e) => setRule(Math.min(50, Math.max(1, Number(e.target.value) || 1)))} aria-label={`Items from ${w.name}`} />
                        <span className="muted small">items</span>
                      </label>
                    ) : <span />}
                  </li>
                )
              })}
            </ul>
          </section>

          <section>
            <h3>Question</h3>
            <p className="muted small">What "Open in Claude" asks at the end.</p>
            <input type="text" value={settings.default_question} maxLength={1000}
              onChange={(e) => update({ default_question: e.target.value })} aria-label="Question" />
          </section>

          <section>
            <h3>AI chat</h3>
            <p className="muted small">
              The 💬 Chat uses the Claude API, billed per use to your Anthropic account (not your Claude subscription).
              Haiku is the cheapest and usually enough.
            </p>
            <div className="assistant-chat-settings">
              <label>
                <span>Model</span>
                <select value={settings.model} onChange={(e) => update({ model: e.target.value })} aria-label="Chat model">
                  {(models.length ? models : [{ id: settings.model, label: settings.model, input: 0, output: 0 }]).map((m) => (
                    <option key={m.id} value={m.id}>{m.label}{m.input ? ` ($${m.input} in / $${m.output} out per million tokens)` : ''}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Monthly budget (USD)</span>
                <input type="number" min={0} max={200} step={0.5} value={settings.monthly_budget}
                  onChange={(e) => update({ monthly_budget: Math.max(0, Math.min(200, Number(e.target.value) || 0)) })} aria-label="Monthly budget in US dollars" />
              </label>
            </div>
            {usage && <p className="muted small">This month so far: ${usage.cost.toFixed(2)} ({usage.requests} requests). The chat stops at the budget; 0 turns it off.</p>}
          </section>

          <details className="assistant-preview">
            <summary>Preview the prompt</summary>
            <p className="muted small">Widget changes above show up after saving.</p>
            <pre>{preview}</pre>
          </details>
        </div>
      )}
      {error && <p className="error-text small">{error}</p>}
      <div className="dialog-actions">
        <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
        <button type="button" className="button primary" onClick={save} disabled={!settings || saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </Dialog>
  )
}
