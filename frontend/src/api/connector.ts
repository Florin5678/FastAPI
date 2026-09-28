// Claude connector (the dashboard as a custom connector in claude.ai / Claude Code)
import { request } from './client'

export type ConnectorChange = { id: number; tool: string; summary: string; at: string; can_undo: boolean; undone_at: string | null }
export type ConnectorConnection = { grant_id: string; app: string; connected_at: string; last_used_at: string | null }
export type ConnectorStatus = { url: string; connections: ConnectorConnection[]; changes: ConnectorChange[] }

export const connectorApi = {
  status: () => request<ConnectorStatus>('/connector/status'),
  undo: (changeId: number) => request<ConnectorChange>(`/connector/changes/${changeId}/undo`, { method: 'POST' }),
  revoke: (grantId: string) => request<{ revoked: boolean }>(`/connector/connections/${grantId}/revoke`, { method: 'POST' }),
}
