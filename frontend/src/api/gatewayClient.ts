import type { ChartAgentClient } from './client'
import type { Session, SessionData } from '../types/protocol'

type GatewaySessionList = { sessions: Session[] }

export class GatewayClientError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'GatewayClientError'
    this.code = code
    this.status = status
  }
}

const gatewayBaseUrl = (import.meta.env.VITE_CHARTAGENT_GATEWAY_URL || 'http://127.0.0.1:8765/api/v1').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(gatewayBaseUrl + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    })
  } catch (error) {
    throw new GatewayClientError('gateway_unavailable', '无法连接到本地 Gateway', 0)
  }

  let payload: { error?: { code?: string; message?: string } } & T
  try {
    payload = await response.json()
  } catch {
    throw new GatewayClientError('invalid_gateway_response', 'Gateway 返回了无效响应', response.status)
  }
  if (!response.ok) {
    throw new GatewayClientError(
      payload.error?.code || 'gateway_error',
      payload.error?.message || 'Gateway 请求失败',
      response.status,
    )
  }
  return payload
}

export const gatewayClient: ChartAgentClient = {
  async listSessions() {
    const payload = await request<GatewaySessionList>('/sessions')
    return payload.sessions
  },

  async getSession(id) {
    return request<SessionData>(`/sessions/${encodeURIComponent(id)}`)
  },

  async createSession(name) {
    return request<SessionData>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ name }),
    })
  },

  async submitMessage(sessionId, text) {
    return request<SessionData>(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    })
  },
}
