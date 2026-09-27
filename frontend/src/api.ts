// Thin wrapper around the FastAPI backend (same origin, session cookie auth)

export type Me = {
  email: string
  name: string | null
  summaries_enabled: boolean
}

export type EmailItem = {
  id: number
  gmail_id: string
  subject: string | null
  sender: string | null
  snippet: string | null
  timestamp: string | null
  category: string | null
  summary: string | null
  full_body?: string | null
}

export type EmailList = { total: number; emails: EmailItem[] }

export type Digest = {
  date: string
  total: number
  categories: Record<string, EmailItem[]>
}

export type SyncResult = { synced: number; checked: number }
export type SummaryResult = { summarized: number; failed?: number; remaining?: number; skipped?: string }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // not JSON - keep the status text
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

function localMidnightIso(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString() // UTC instant of the viewer's local midnight
}

export const api = {
  me: () => request<Me>('/api/me'),
  logout: () => request<unknown>('/auth/google/logout', { method: 'POST' }),
  emails: (params: { category?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams()
    if (params.category) q.set('category', params.category)
    q.set('limit', String(params.limit ?? 30))
    q.set('offset', String(params.offset ?? 0))
    return request<EmailList>(`/emails?${q}`)
  },
  email: (id: number) => request<EmailItem>(`/emails/${id}`),
  digest: () => request<Digest>(`/digest/today?since=${encodeURIComponent(localMidnightIso())}`),
  sync: () => request<SyncResult>('/gmail/sync/gmail?max_results=20', { method: 'POST' }),
  summarize: () => request<SummaryResult>('/summaries/run?limit=10', { method: 'POST' }),
}
