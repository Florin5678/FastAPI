import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError, type Me } from './api'
import { SignIn } from './components/SignIn'
import { Digest } from './components/Digest'
import { Inbox } from './components/Inbox'
import { EmailDetail } from './components/EmailDetail'
import { Dashboard } from './components/Dashboard'
import type { DashboardActions } from './widgets/types'

type Tab = 'home' | 'today' | 'inbox'

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [authState, setAuthState] = useState<'loading' | 'signed-out' | 'signed-in'>('loading')
  const [loadError, setLoadError] = useState<string | null>(null)

  const [tab, setTab] = useState<Tab>('home')
  const [inboxCategory, setInboxCategory] = useState<string | undefined>(undefined)
  const [openEmailId, setOpenEmailId] = useState<number | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [syncing, setSyncing] = useState(false)
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null)

  useEffect(() => {
    api.me()
      .then((data) => {
        setMe(data)
        setAuthState('signed-in')
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) setAuthState('signed-out')
        else setLoadError(err.message)
      })
  }, [])

  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(timer)
  }, [notice])

  const sync = useCallback(async () => {
    setSyncing(true)
    try {
      const synced = await api.sync()
      let text = synced.synced === 0 ? 'No new emails' : `${synced.synced} new email${synced.synced === 1 ? '' : 's'}`
      if (me?.summaries_enabled && synced.synced > 0) {
        const summarized = await api.summarize()
        text += `, ${summarized.summarized} summarized`
        if (summarized.remaining) text += ` (${summarized.remaining} still waiting)`
      }
      setNotice({ text })
      setRefreshKey((k) => k + 1)
    } catch (err) {
      setNotice({ text: `Sync failed: ${(err as Error).message}`, error: true })
    } finally {
      setSyncing(false)
    }
  }, [me])

  const showNotice = useCallback((text: string, error?: boolean) => setNotice({ text, error }), [])

  const actions: DashboardActions = useMemo(() => ({
    openEmail: setOpenEmailId,
    goTo: (view, options) => {
      if (view === 'inbox') setInboxCategory(options?.category)
      setTab(view)
      window.scrollTo(0, 0)
    },
  }), [])

  const logout = async () => {
    await api.logout().catch(() => undefined)
    setMe(null)
    setAuthState('signed-out')
  }

  if (loadError) {
    return (
      <div className="center-screen">
        <p className="error-text">Couldn't reach the server: {loadError}</p>
        <button className="button" onClick={() => location.reload()}>Try again</button>
      </div>
    )
  }
  if (authState === 'loading') return <div className="center-screen muted">Loading…</div>
  if (authState === 'signed-out' || !me) return <SignIn />

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>Inbox Dashboard</span>
        </div>
        <nav className="tabs" aria-label="Views">
          <button className={tab === 'home' ? 'tab active' : 'tab'} onClick={() => setTab('home')}>Home</button>
          <button className={tab === 'today' ? 'tab active' : 'tab'} onClick={() => setTab('today')}>Today</button>
          <button className={tab === 'inbox' ? 'tab active' : 'tab'} onClick={() => actions.goTo('inbox')}>Inbox</button>
        </nav>
        <div className="topbar-actions">
          <button className="button primary" onClick={sync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync now'}
          </button>
          <span className="user" title={me.email}>{me.name || me.email}</span>
          <button className="button ghost" onClick={logout}>Sign out</button>
        </div>
      </header>

      {!me.summaries_enabled && (
        <div className="banner">
          Summaries are off — add <code>ANTHROPIC_API_KEY</code> on Render to turn them on. Emails still sync.
        </div>
      )}

      <main className={tab === 'home' ? 'content wide' : 'content'}>
        {tab === 'home' && <Dashboard refreshKey={refreshKey} actions={actions} onNotice={showNotice} />}
        {tab === 'today' && <Digest refreshKey={refreshKey} onOpen={setOpenEmailId} />}
        {tab === 'inbox' && (
          <Inbox key={inboxCategory ?? 'all'} initialCategory={inboxCategory} refreshKey={refreshKey} onOpen={setOpenEmailId} />
        )}
      </main>

      {openEmailId !== null && <EmailDetail id={openEmailId} onClose={() => setOpenEmailId(null)} />}

      {notice && (
        <div className={notice.error ? 'toast error' : 'toast'} role="status">{notice.text}</div>
      )}
    </div>
  )
}
