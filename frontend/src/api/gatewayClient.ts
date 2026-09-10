import type { ChartAgentClient } from './client'
import type { Attachment, Session, SessionData } from '../types/protocol'
import { mediaTypeForFile } from '../attachments'

type GatewaySessionList = { sessions: Session[] }
type GatewayAttachment = {
  attachment_id: string
  filename: string
  media_type: string
  byte_count: number
  sha256?: string
  status?: Attachment['status']
  preview_available?: boolean
}
type GatewaySessionData = Omit<SessionData, 'attachments'> & { attachments: GatewayAttachment[] }

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

function mapAttachment(item: GatewayAttachment): Attachment {
  return {
    id: item.attachment_id,
    filename: item.filename,
    mediaType: item.media_type,
    byteCount: item.byte_count,
    sha256: item.sha256,
    status: item.status || 'registered',
    previewAvailable: item.preview_available || false,
    previewUrl: '',
  }
}

function mapSessionData(payload: GatewaySessionData): SessionData {
  return { ...payload, attachments: payload.attachments.map(mapAttachment) }
}

export const gatewayClient: ChartAgentClient = {
  async listSessions() {
    const payload = await request<GatewaySessionList>('/sessions')
    return payload.sessions
  },

  async getSession(id) {
    return mapSessionData(await request<GatewaySessionData>(`/sessions/${encodeURIComponent(id)}`))
  },

  async createSession(name) {
    return mapSessionData(await request<GatewaySessionData>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }))
  },

  async listAttachments(sessionId) {
    const payload = await request<{ attachments: GatewayAttachment[] }>(`/sessions/${encodeURIComponent(sessionId)}/attachments`)
    return payload.attachments.map(mapAttachment)
  },

  async uploadAttachment(sessionId, file) {
    const mediaType = mediaTypeForFile(file)
    const payload = await request<{ attachment: GatewayAttachment }>(
      `/sessions/${encodeURIComponent(sessionId)}/attachments?filename=${encodeURIComponent(file.name)}`,
      {
        method: 'POST',
        body: file,
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-ChartAgent-Media-Type': mediaType,
        },
      },
    )
    return mapAttachment(payload.attachment)
  },

  async submitMessage(sessionId, text, attachmentIds = []) {
    return mapSessionData(await request<GatewaySessionData>(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds }),
    }))
  },
}
