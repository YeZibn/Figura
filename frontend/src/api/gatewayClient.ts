import type { ChartAgentClient, RunEventCallbacks, RunStartOptions, RunSubscription } from './client'
import type { AgentRunEvent, Attachment, GatewayHealth, GeneratedChartReference, ObservationReference, PreviewResource, Provider, RunHandle, RunHistory, RunSummary, Session, SessionData } from '../types/protocol'
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
type GatewayRunResponse = { run: RunHandle }
type GatewayRunEvent = { runId: string; sequence: number; kind: string; timestamp: string; payload?: Record<string, unknown> }
type GatewayRunHistory = { run: RunSummary; events: GatewayRunEvent[]; historyGap: boolean; historyGapCode?: string | null; firstSequence?: number | null }
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

let gatewayBaseUrl = (import.meta.env.VITE_CHARTAGENT_GATEWAY_URL || 'http://127.0.0.1:8765/api/v1').replace(/\/$/, '')

export function configureGatewayBaseUrl(value?: string): string {
  if (value) gatewayBaseUrl = value.replace(/\/$/, '')
  return gatewayBaseUrl
}

export function currentGatewayBaseUrl(): string {
  return gatewayBaseUrl
}

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

function attachmentContentUrl(sessionId: string, attachmentId: string): string {
  return `${gatewayBaseUrl}/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/content`
}

function attachmentPreviewResource(sessionId: string, attachmentId: string): PreviewResource {
  return { kind: 'attachment', sessionId, attachmentId }
}

function generatedArtifactUrl(sessionId: string, runId: string, artifactId: string): string {
  return `${gatewayBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`
}

function generatedCandidateUrl(sessionId: string, runId: string, candidateId: string): string {
  return `${gatewayBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidateId)}`
}

function chartPreviewResource(sessionId: string, runId: string, reference: GeneratedChartReference): PreviewResource | undefined {
  if (reference.artifactId) return { kind: 'artifact', sessionId, runId, artifactId: reference.artifactId }
  if (reference.candidateId) return { kind: 'candidate', sessionId, runId, candidateId: reference.candidateId }
  return undefined
}

function mapAttachment(item: GatewayAttachment, sessionId?: string): Attachment {
  return {
    id: item.attachment_id,
    filename: item.filename,
    mediaType: item.media_type,
    byteCount: item.byte_count,
    sha256: item.sha256,
    status: item.status || 'registered',
    previewAvailable: item.preview_available || false,
    previewUrl: '',
    previewResource: item.preview_available && sessionId ? attachmentPreviewResource(sessionId, item.attachment_id) : undefined,
  }
}

function mapSessionData(payload: GatewaySessionData): SessionData {
  return { ...payload, runs: payload.runs || [], attachments: payload.attachments.map((item) => mapAttachment(item, payload.session.id)) }
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
        previewResource: { kind: 'observation', sessionId, runId: event.runId, observationId: reference.observationId },
      }
    })
  }
  if (event.kind === 'generated_chart' && Array.isArray(payload.artifacts)) {
    payload.artifacts = payload.artifacts.map((item) => {
      if (!item || typeof item !== 'object') return item
      const reference = item as Partial<GeneratedChartReference>
      if (reference.status === 'unavailable' || reference.status === 'failed') return item
      const chartReference = reference as GeneratedChartReference
      const resource = chartPreviewResource(sessionId, event.runId, chartReference)
      const url = reference.artifactId
        ? generatedArtifactUrl(sessionId, event.runId, reference.artifactId)
        : reference.candidateId
          ? generatedCandidateUrl(sessionId, event.runId, reference.candidateId)
          : ''
      return resource ? { ...reference, previewResource: resource, imageUrl: url, downloadUrl: reference.artifactId ? url : undefined } : item
    })
  }
  return { runId: event.runId, sequence: event.sequence, kind: event.kind, timestamp: event.timestamp, payload }
}

const terminalEventKinds = new Set(['final_answer', 'run_failed', 'run_interrupted'])
const streamEventKinds = [
  'run_started',
  'model_started',
  'model_completed',
  'tool_call',
  'tool_result',
  'visual_observation',
  'generated_chart',
  'chart_review_started',
  'chart_review_completed',
  'generated_chart_rejected',
  'chart_review_required',
  'generated_chart_published',
  'reasoning',
  'budget_exhausted',
  'final_answer',
  'run_failed',
  'run_interrupted',
  'history_gap',
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

  async deleteSession(id) {
    await request<{ deleted: boolean }>(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },

  async listAttachments(sessionId) {
    const payload = await request<{ attachments: GatewayAttachment[] }>(`/sessions/${encodeURIComponent(sessionId)}/attachments`)
    return payload.attachments.map((item) => mapAttachment(item, sessionId))
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
    return mapAttachment(payload.attachment, sessionId)
  },

  async deleteAttachment(sessionId, attachmentId) {
    await request<{ deleted: boolean }>(
      `/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: 'DELETE' },
    )
  },

  attachmentContentUrl(sessionId, attachmentId) {
    return attachmentContentUrl(sessionId, attachmentId)
  },

  generatedArtifactUrl(sessionId, runId, artifactId) {
    return generatedArtifactUrl(sessionId, runId, artifactId)
  },

  async startRun(sessionId, text, attachmentIds = [], provider, options: RunStartOptions = {}) {
    return mapRun(await request<GatewayRunResponse>(`/sessions/${encodeURIComponent(sessionId)}/runs`, {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds, ...(provider ? { provider } : {}), ...(options.retryOf ? { retryOf: options.retryOf } : {}) }),
      headers: options.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
    }))
  },

  async interruptRun(sessionId, runId) {
    const payload = await request<GatewayRunResponse>(`/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/interrupt`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'user_cancelled' }),
    })
    return mapRun(payload)
  },

  async getRunHistory(sessionId, runId, afterSequence = 0) {
    const payload = await request<GatewayRunHistory>(`/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}?after=${Math.max(0, afterSequence)}`)
    return {
      run: payload.run,
      events: payload.events.map((event) => mapRunEvent(event, sessionId)),
      historyGap: payload.historyGap,
      firstSequence: payload.firstSequence,
    }
  },

  subscribeRun(sessionId, runId, callbacks: RunEventCallbacks, afterSequence = 0): RunSubscription {
    const source = new EventSource(`${gatewayBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/events?after=${Math.max(0, afterSequence)}`)
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

  async submitMessage(sessionId, text, attachmentIds = [], provider) {
    return mapSessionData(await request<GatewaySessionData>(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds, ...(provider ? { provider } : {}) }),
    }))
  },
}
