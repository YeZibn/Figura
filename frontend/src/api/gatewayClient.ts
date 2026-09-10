import type { ChartAgentClient, RunEventCallbacks, RunSubscription } from './client'
import type { AgentRunEvent, Attachment, GatewayHealth, ObservationReference, RunHandle, Session, SessionData } from '../types/protocol'
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
type GatewayRunResponse = { run: { runId: string; sessionId: string; status: 'running' } }
type GatewayRunEvent = { runId: string; sequence: number; kind: string; timestamp: string; payload?: Record<string, unknown> }
type GatewayHealthResponse = GatewayHealth

export class GatewayClientError extends Error {
  readonly code: string
  readonly status: number
  readonly reason?: string

  constructor(code: string, message: string, status: number, reason?: string) {
    super(message)
    this.name = 'GatewayClientError'
    this.code = code
    this.status = status
    this.reason = reason
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

  let payload: { error?: { code?: string; message?: string; reason?: string } } & T
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
      payload.error?.reason,
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

function mapRun(payload: GatewayRunResponse): RunHandle {
  return payload.run
}

function mapRunEvent(event: GatewayRunEvent, sessionId: string): AgentRunEvent {
  const payload = { ...(event.payload || {}) }
  if (event.kind === 'visual_observation' && Array.isArray(payload.observations)) {
    payload.observations = payload.observations.map((item) => {
      if (!item || typeof item !== 'object') return item
      const reference = item as Partial<ObservationReference>
      if (!reference.observationId) return item
      return {
        ...reference,
        imageUrl: `${gatewayBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(event.runId)}/observations/${encodeURIComponent(reference.observationId)}`,
      }
    })
  }
  return { runId: event.runId, sequence: event.sequence, kind: event.kind, timestamp: event.timestamp, payload }
}

const terminalEventKinds = new Set(['final_answer', 'run_failed'])
const streamEventKinds = [
  'run_started',
  'model_started',
  'model_completed',
  'tool_call',
  'tool_result',
  'visual_observation',
  'reasoning',
  'budget_exhausted',
  'final_answer',
  'run_failed',
]

export const gatewayClient: ChartAgentClient = {
  async getHealth() {
    return request<GatewayHealthResponse>('/health')
  },

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

  async startRun(sessionId, text, attachmentIds = []) {
    return mapRun(await request<GatewayRunResponse>(`/sessions/${encodeURIComponent(sessionId)}/runs`, {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds }),
    }))
  },

  subscribeRun(sessionId, runId, callbacks: RunEventCallbacks): RunSubscription {
    const source = new EventSource(`${gatewayBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/events`)
    let closed = false
    let connectionErrors = 0
    const receive = (raw: Event) => {
      if (closed) return
      try {
        const event = mapRunEvent(JSON.parse((raw as MessageEvent<string>).data) as GatewayRunEvent, sessionId)
        connectionErrors = 0
        callbacks.onEvent(event)
        if (terminalEventKinds.has(event.kind)) {
          closed = true
          source.close()
          callbacks.onComplete()
        }
      } catch {
        closed = true
        source.close()
        callbacks.onError(new GatewayClientError('invalid_gateway_event', 'Gateway 返回了无效执行事件', 502))
      }
    }
    streamEventKinds.forEach((kind) => source.addEventListener(kind, receive))
    source.onerror = () => {
      if (closed) return
      connectionErrors += 1
      if (source.readyState === EventSource.CLOSED || connectionErrors >= 3) {
        closed = true
        source.close()
        callbacks.onError(new GatewayClientError('gateway_stream_unavailable', '执行事件流已断开', 0))
      }
    }
    return {
      close() {
        closed = true
        source.close()
      },
    }
  },

  async submitMessage(sessionId, text, attachmentIds = []) {
    return mapSessionData(await request<GatewaySessionData>(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds }),
    }))
  },
}
