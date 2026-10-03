import { useEffect, useState } from 'react'
import { assistantApi, type AssistantSettings, type BriefingWidget, type ChatModel, type ChatUsage } from '../../api'
import { Dialog } from '../../components/Dialog'

type Props = { onSaved: () => void; onClose: () => void }

// Everything that goes into the briefing prompt (the same for "Open in Claude", "Copy
// briefing" and the AI chat): opening text, the answer sections, filters, which widgets
// are included (and how many items), and the
// Claude prompt (what "Open in Claude" sends). Saved per user; the server builds the prompt (assistant.py).
export function AssistantSettingsDialog({ onSaved, onClose }: Props) {
  const [settings, setSettings] = useState<AssistantSettings | null>(null)
  const [widgets, setWidgets] = useState<BriefingWidget[]>([])
  const [emailCategories, setEmailCategories] = useState<string[]>([])
  const [preview, setPreview] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [models, setModels] = useState<ChatModel[]>([])
  const [usage, setUsage] = useState<ChatUsage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    assistantApi.settings()
      .then((r) => { if (!cancelled) { setSettings(r.settings); setWidgets(r.widgets); setEmailCategories(r.email_categories) } })
      .catch((err) => { if (!cancelled) setError((err as Error).message) })
    assistantApi.chatStatus()
      .then((r) => { if (!cancelled) { setModels(r.models); setUsage(r.usage) } })
      .catch(() => undefined) // the chat section just shows fewer details
    return () => { cancelled = true }
  }, [])

  const update = (changes: Partial<AssistantSettings>) => {
    setSettings((s) => (s ? { ...s, ...changes } : s))
    setPreview(null) // out of date
  }
  const setExtra = (i: number, changes: Partial<AssistantSettings['extras'][number]>) =>
    settings && update({ extras: settings.extras.map((x, j) => (j === i ? { ...x, ...changes } : x)) })
  const moveExtra = (i: number) => {
    if (!settings || i === 0) return
    const extras = [...settings.extras]
    ;[extras[i - 1], extras[i]] = [extras[i], extras[i - 1]]
    update({ extras })
  }
  const setFilters = (changes: Partial<AssistantSettings['filters']>) => settings && update({ filters: { ...settings.filters, ...changes } })

  const cleaned = (s: AssistantSettings): AssistantSettings => ({
    ...s,
    extras: s.extras.filter((e) => e.name.trim() && e.text.trim()).map((e) => ({ ...e, name: e.name.trim(), text: e.text.trim() })),
  })

  const showPreview = async () => {
    if (!settings) return
    setPreviewing(true)
    setError(null)
    try {
      setPreview((await assistantApi.preview(cleaned(settings))).prompt)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPreviewing(false)
    }
  }

  const save = async () => {
    if (!settings) return
    setSaving(true)
    setError(null)
    try {
      await assistantApi.save(cleaned(settings))
      onSaved()
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

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
              <h3>Answer sections</h3>
              <button type="button" className="button ghost small-button" disabled={settings.extras.length >= 30}
                onClick={() => update({ extras: [...settings.extras, { name: '', text: '', enabled: true }] })}>+ Add</button>
            </div>
            <p className="muted small">
              Each one becomes a section of Claude's answer, in this order (↑ moves one up). Untick the box to switch one off.
            </p>
            <ul className="assistant-extras">
              {settings.extras.map((extra, i) => (
                <li key={i} className={extra.enabled ? '' : 'off'}>
                  <input type="checkbox" checked={extra.enabled} aria-label={`Use ${extra.name || 'this instruction'}`}
                    onChange={(e) => setExtra(i, { enabled: e.target.checked })} />
                  <div className="assistant-extra-fields">
                    <input type="text" value={extra.name} placeholder="Name, e.g. Meal ideas" maxLength={80} aria-label="Name"
                      onChange={(e) => setExtra(i, { name: e.target.value })} />
                    <textarea rows={2} value={extra.text} placeholder="What Claude should do" maxLength={600} aria-label="Instruction"
                      onChange={(e) => setExtra(i, { text: e.target.value })} />
                  </div>
                  <button type="button" className="icon-button" aria-label={`Move ${extra.name || 'this instruction'} up`} title="Move up"
                    disabled={i === 0} onClick={() => moveExtra(i)}>↑</button>
                  <button type="button" className="icon-button" aria-label={`Delete ${extra.name || 'this instruction'}`} title="Delete"
                    onClick={() => update({ extras: settings.extras.filter((_, j) => j !== i) })}>✕</button>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h3>Items loaded per section</h3>
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
                        <span className="muted small">{w.items_label}</span>
                      </label>
                    ) : <span />}
                  </li>
                )
              })}
            </ul>
          </section>

          <section>
            <h3>Filters</h3>
            <p className="muted small">Left out before Claude sees the briefing (more reliable than asking Claude to ignore them). Separate words with commas.</p>
            <label className="assistant-filter">
              <span>Ignore calendar events whose title contains</span>
              <input type="text" value={settings.filters.calendar_ignore} maxLength={1000} placeholder="e.g. Cabin trip, LICS drop-in, brainwaves"
                onChange={(e) => setFilters({ calendar_ignore: e.target.value })} />
            </label>
            <div className="assistant-filter">
              <span>Leave out these email categories</span>
              <div className="assistant-categories">
                {emailCategories.map((c) => (
                  <label key={c} className="small">
                    <input type="checkbox" checked={settings.filters.email_skip_categories.includes(c)}
                      onChange={(e) => setFilters({
                        email_skip_categories: e.target.checked
                          ? [...settings.filters.email_skip_categories, c]
                          : settings.filters.email_skip_categories.filter((x) => x !== c),
                      })} />
                    {c}
                  </label>
                ))}
              </div>
            </div>
            <label className="assistant-filter">
              <span>Ignore emails whose sender or subject contains</span>
              <input type="text" value={settings.filters.email_ignore} maxLength={1000} placeholder="e.g. skyscanner, verify your account, privacy"
                onChange={(e) => setFilters({ email_ignore: e.target.value })} />
            </label>
          </section>

          <section>
            <h3>Rules</h3>
            <p className="muted small">Added after the answer sections, for every briefing and the AI chat. Leave empty for the default rules.</p>
            <textarea rows={8} value={settings.rules} maxLength={4000}
              onChange={(e) => update({ rules: e.target.value })} aria-label="Rules" />
          </section>

          <section>
            <h3>Claude prompt</h3>
            <p className="muted small">What "Open in Claude" asks.</p>
            <textarea rows={3} value={settings.claude_prompt} maxLength={2000}
              onChange={(e) => update({ claude_prompt: e.target.value })} aria-label="Claude prompt" />
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

          <section>
            <h3>Morning brief</h3>
            <p className="muted small">
              Claude writes your brief each day after this time and leaves it on the Assistant tile (☀️ Morning brief).
              It uses the AI chat above (model and monthly budget; about $0.01 a day).
            </p>
            <div className="assistant-morning">
              <label className="assistant-morning-toggle">
                <input type="checkbox" checked={settings.morning_brief} onChange={(e) => update({ morning_brief: e.target.checked })} />
                Write a morning brief every day
              </label>
              <label>
                <span className="muted small">After</span>
                <input type="time" value={settings.morning_brief_time} disabled={!settings.morning_brief}
                  onChange={(e) => update({ morning_brief_time: e.target.value || '07:00' })} aria-label="Morning brief time" />
              </label>
            </div>
          </section>

          <section className="assistant-preview">
            <div className="assistant-settings-head">
              <h3>Preview</h3>
              <button type="button" className="button ghost small-button" onClick={showPreview} disabled={previewing}>
                {previewing ? 'Building…' : preview ? 'Refresh' : 'Show the full prompt'}
              </button>
            </div>
            <p className="muted small">Exactly what Claude gets, with the settings above (saved or not).</p>
            {preview && <pre>{preview}</pre>}
          </section>
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
