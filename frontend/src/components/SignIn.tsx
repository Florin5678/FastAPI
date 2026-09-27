const ERRORS: Record<string, string> = {
  access_denied: 'Sign-in was cancelled.',
  google_login_failed: 'Google sign-in failed. Please try again.',
}

export function SignIn() {
  const loginError = new URLSearchParams(location.search).get('login_error')

  return (
    <div className="center-screen">
      <div className="signin-card">
        <img src="/favicon.svg" alt="" width={48} height={48} />
        <h1>Inbox Dashboard</h1>
        <p className="muted">Your Gmail, summarized and sorted.</p>
        {loginError && <p className="error-text">{ERRORS[loginError] ?? `Sign-in error: ${loginError}`}</p>}
        <a className="button primary large" href="/auth/google/login">Sign in with Google</a>
      </div>
    </div>
  )
}
