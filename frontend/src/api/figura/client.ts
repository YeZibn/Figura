import type { AgentRunEvent } from '../../types/protocol'
import type { RunSubscription } from '../client'
import type {
  FiguraAttachmentDto,
  FiguraClient,
  FiguraEventDto,
  FiguraHealth,
  FiguraPanelDto,
  FiguraRunHandleDto,
  FiguraRunHistoryDto,
  FiguraSessionDataDto,
  FiguraSessionDto,
  FiguraToolCallDetailDto,
  FiguraToolTimelineSnapshotDto,
} from './types'

export class FiguraClientError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'FiguraClientError'
    this.code = code
    this.status = status
  }
}

const defaultBaseUrl = (import.meta.env.VITE_FIGURA_GATEWAY_URL || 'http://127.0.0.1:8766/api/v1').replace(/\/$/, '')

type ErrorEnvelope = { error?: { code?: string; message?: string } }

export function createFiguraClient(baseUrl = defaultBaseUrl): FiguraClient {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, '')

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response
    try {
      response = await fetch(`${normalizedBaseUrl}${path}`, {
        ...init,
        cache: 'no-store',
        headers: { ...(init?.headers || {}) },
      })
    } catch {
      throw new FiguraClientError('gateway_unavailable', '无法连接到本地 Figura Gateway。', 0)
    }
    if (response.status === 204) return undefined as T
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      throw new FiguraClientError('invalid_gateway_response', 'Figura Gateway 返回了无效响应。', response.status)
    }
    if (!response.ok) {
      const error = (payload as ErrorEnvelope)?.error
      throw new FiguraClientError(
        error?.code || 'gateway_error',
        error?.message || 'Figura Gateway 请求失败。',
        response.status,
      )
    }
    return payload as T
  }

  async function getChartRenderContent(sessionId: string, runId: string, callId: string): Promise<Blob> {
    let response: Response
    try {
      response = await fetch(buildChartRenderContentUrl(sessionId, runId, callId), { cache: 'no-store' })
    } catch {
      throw new FiguraClientError('gateway_unavailable', '无法连接到本地 Figura Gateway。', 0)
    }
    if (!response.ok) {
      let payload: unknown
      try {
        payload = await response.json()
      } catch {
        payload = undefined
      }
      const error = (payload as ErrorEnvelope | undefined)?.error
      const code = typeof error?.code === 'string' && /^[a-z0-9_]{1,64}$/.test(error.code)
        ? error.code
        : 'gateway_error'
      const message = typeof error?.message === 'string' && error.message.trim()
        ? error.message.slice(0, 160)
        : 'Figura Gateway 请求失败。'
      throw new FiguraClientError(
        code,
        message,
        response.status,
      )
    }

    const contentType = (response.headers.get('Content-Type') || '').split(';', 1)[0].trim().toLowerCase()
    if (contentType !== 'image/png') {
      throw new FiguraClientError('invalid_chart_render_response', 'Figura Gateway 返回了无效的图表文件。', response.status)
    }
    try {
      const blob = await response.blob()
      if (blob.size === 0) {
        throw new FiguraClientError('invalid_chart_render_response', 'Figura Gateway 返回了空的图表文件。', response.status)
      }
      return blob
    } catch (error) {
      if (error instanceof FiguraClientError) throw error
      throw new FiguraClientError('invalid_chart_render_response', 'Figura Gateway 返回了无效的图表文件。', response.status)
    }
  }

  function buildChartRenderContentUrl(sessionId: string, runId: string, callId: string): string {
    return `${normalizedBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/chart-renders/${encodeURIComponent(callId)}/content`
  }

  return {
    baseUrl: normalizedBaseUrl,
    async getHealth() {
      return request<FiguraHealth>('/health')
    },
    async listSessions() {
      const payload = await request<{ sessions: FiguraSessionDto[] }>('/sessions')
      return payload.sessions
    },
    async getSession(sessionId) {
      return request<FiguraSessionDataDto>(`/sessions/${encodeURIComponent(sessionId)}`)
    },
    async createSession(name) {
      const payload = await request<{ session: FiguraSessionDto }>('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      return payload.session
    },
    async deleteSession(sessionId) {
      await request<void>(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
    },
    async listAttachments(sessionId) {
      const payload = await request<{ attachments: FiguraAttachmentDto[] }>(`/sessions/${encodeURIComponent(sessionId)}/attachments`)
      return payload.attachments
    },
    async listPanels(sessionId) {
      const payload = await request<{ panels: FiguraPanelDto[] }>(`/sessions/${encodeURIComponent(sessionId)}/panels`)
      return payload.panels
    },
    async uploadAttachment(sessionId, file) {
      const query = new URLSearchParams({ filename: file.name })
      const payload = await request<{ attachment: FiguraAttachmentDto }>(`/sessions/${encodeURIComponent(sessionId)}/attachments?${query}`, {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
      })
      return payload.attachment
    },
    async deleteAttachment(sessionId, attachmentId) {
      await request<void>(`/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`, { method: 'DELETE' })
    },
    async startRun(sessionId, text, attachmentIds, providerId, idempotencyKey) {
      const payload = await request<{ run: FiguraRunHandleDto }>(`/sessions/${encodeURIComponent(sessionId)}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ text, attachmentIds, providerId }),
      })
      return payload.run
    },
    async getRunHistory(sessionId, runId, afterSequence = 0) {
      return request<FiguraRunHistoryDto>(
        `/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/history?afterSequence=${Math.max(0, afterSequence)}`,
      )
    },
    async getRunTimeline(sessionId, runId) {
      return request<FiguraToolTimelineSnapshotDto>(
        '/sessions/' + encodeURIComponent(sessionId) + '/runs/' + encodeURIComponent(runId) + '/timeline',
      )
    },
    async getRunTimelineCall(sessionId, runId, callId) {
      return request<FiguraToolCallDetailDto>(
        '/sessions/' + encodeURIComponent(sessionId) + '/runs/' + encodeURIComponent(runId) + '/timeline/' + encodeURIComponent(callId),
      )
    },
    getChartRenderContent,
    subscribeRun(sessionId, runId, callbacks, afterSequence = 0) {
      const source = new EventSource(
        `${normalizedBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/events?afterSequence=${Math.max(0, afterSequence)}`,
      )
      let closed = false
      const receive = (raw: Event) => {
        if (closed) return
        try {
          const event = JSON.parse((raw as MessageEvent<string>).data) as FiguraEventDto
          callbacks.onEvent({
            runId: event.runId,
            sequence: event.sequence,
            kind: event.kind,
            timestamp: event.timestamp,
            payload: event.payload,
          })
          if (['run_completed', 'run_failed', 'run_interrupted'].includes(event.kind)) {
            closed = true
            source.close()
            callbacks.onComplete()
          }
        } catch {
          closed = true
          source.close()
          callbacks.onError(new FiguraClientError('invalid_gateway_event', 'Figura Gateway 返回了无效运行事件。', 502))
        }
      }
      ;['run_created', 'run_progress', 'run_completed', 'run_failed', 'run_interrupted'].forEach((kind) => source.addEventListener(kind, receive))
      source.onerror = () => {
        if (closed) return
        closed = true
        source.close()
        callbacks.onError(new FiguraClientError('gateway_stream_unavailable', 'Figura 运行事件流已断开。', 0))
      }
      return { close() { closed = true; source.close() } } satisfies RunSubscription
    },
    attachmentContentUrl(sessionId, attachmentId) {
      return `${normalizedBaseUrl}/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/content`
    },
    panelContentUrl(sessionId, panelId) {
      return `${normalizedBaseUrl}/sessions/${encodeURIComponent(sessionId)}/panels/${encodeURIComponent(panelId)}/content`
    },
    chartRenderContentUrl(sessionId, runId, callId) {
      return buildChartRenderContentUrl(sessionId, runId, callId)
    },
    timelineObservationUrl(sessionId, runId, callId) {
      return `${normalizedBaseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/timeline/${encodeURIComponent(callId)}/observation`
    },
  }
}

export const figuraClient = createFiguraClient()
