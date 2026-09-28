import { useState } from 'react'

const CLOUD_CONSOLE = 'https://console.cloud.google.com/apis/library'
const PROJECT = '660269344051'

// What a Google-backed widget shows before it can load: sign in again for a missing
// permission, turn on the API in Cloud Console, or paste the file/folder link
export function GoogleSetup({ reason, service, api }: {
  reason: 'permission' | 'api_disabled'
  service: string // e.g. "Google Drive"
  api: string // Cloud Console API id, e.g. "drive.googleapis.com"
}) {
  if (reason === 'permission') {
    return (
      <div className="google-setup">
        <p>Allow the dashboard to read your {service} (read-only).</p>
        <a className="button primary" href="/auth/google/login">Connect {service}</a>
        <p className="muted small">You'll sign in with Google once more and tick the new permission.</p>
      </div>
    )
  }
  return (
    <div className="google-setup">
      <p>The {service} API is switched off for this app's Google Cloud project.</p>
      <a className="button primary" href={`${CLOUD_CONSOLE}/${api}?project=${PROJECT}`} target="_blank" rel="noopener noreferrer">Turn it on (one time)</a>
      <p className="muted small">Click <b>Enable</b> on that page, wait a minute, then refresh this widget.</p>
    </div>
  )
}

export function LinkSetup({ prompt, placeholder, invalid, onSave }: {
  prompt: string
  placeholder: string
  invalid: boolean // the saved link couldn't be read
  onSave: (link: string) => Promise<void>
}) {
  const [link, setLink] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await onSave(link.trim())
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <form className="google-setup" onSubmit={(e) => { e.preventDefault(); if (link.trim()) void save() }}>
      <p>{prompt}</p>
      {invalid && <p className="error-text small">That link doesn't look right. Copy it from the address bar or Share → Copy link.</p>}
      <input className="google-setup-input" type="url" value={link} onChange={(e) => setLink(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
      <button className="button primary" type="submit" disabled={!link.trim() || saving}>{saving ? 'Saving…' : 'Save'}</button>
      {error && <p className="error-text small">{error}</p>}
      <p className="muted small">You can change it later in Edit → ⚙ on this widget.</p>
    </form>
  )
}
