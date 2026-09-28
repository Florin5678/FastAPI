const CLOUD_CONSOLE = 'https://console.cloud.google.com/apis/library'
const PROJECT = '660269344051'

// What a Google-backed widget shows before it can load: sign in again for a missing
// permission, or turn on the API in Cloud Console
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
