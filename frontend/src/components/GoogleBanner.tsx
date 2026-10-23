import type { Me } from '../api'

// Shown when the dashboard can't use the Google sign-in (Gmail sync, Calendar): says why and
// offers to reconnect. Signing in again gives Google's consent screen, which renews the access.
export function GoogleBanner({ google }: { google: Me['google'] }) {
  if (google.ok) return null
  const since = google.since ? new Date(google.since).toLocaleDateString([], { day: 'numeric', month: 'short' }) : null
  return (
    <div className="google-banner" role="alert">
      <div className="google-banner-text">
        <strong>Gmail and Google Calendar aren't updating{since && ` since ${since}`}.</strong>{' '}
        <span>{google.problem}</span>
        <details>
          <summary>Has to be redone about once a week?</summary>
          Google ends sign-ins after 7 days while the dashboard's app in Google Cloud Console is in <em>Testing</em>.
          Publishing it (Google Auth Platform → Audience, or OAuth consent screen → <em>Publish app</em>) stops that.
          Until you reconnect, briefings ask Claude to use its own Gmail and Calendar connectors instead.
        </details>
      </div>
      <a className="button primary small-button" href="/auth/google/login">Reconnect Google</a>
    </div>
  )
}
