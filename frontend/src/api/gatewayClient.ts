import type { ChartAgentClient, RunEventCallbacks, RunResumeOptions, RunStartOptions, RunSubscription } from './client'
import { mediaTypeForFile } from '../attachments'
import type { EvaluationDetail, EvaluationHistory, EvaluationHistoryDetails, EvaluationSummary, GatewayHealth, RunHistory } from '../types/protocol'
import { configureGatewayBaseUrl, currentGatewayBaseUrl, GatewayClientError, request } from './gateway/transport'
import {
  attachmentContentUrl,
  generatedArtifactUrl,
  mapAttachment,
  mapEvaluationCase,
  mapEvaluationDetailEntry,
  mapEvaluationEvent,
  mapRun,
  mapRunEvent,
  mapSessionData,
} from './gateway/mappers'
import { subscribeRun } from './gateway/runStream'
import type {
  GatewayAttachment,
  GatewayEvaluationCase,
  GatewayEvaluationDetail,
  GatewayEvaluationHistoryDetails,
  GatewayEvaluationList,
  GatewayRunEvent,
  GatewayRunHistory,
  GatewayRunResponse,
  GatewaySessionData,
  GatewaySessionList,
} from './gateway/types'

export { GatewayClientError, configureGatewayBaseUrl, currentGatewayBaseUrl } from './gateway/transport'

export const gatewayClient: ChartAgentClient = {
  async getHealth() {
    return request<GatewayHealth>('/health')
  },

  async listSessions() {
    const payload = await request<GatewaySessionList>('/sessions')
    return payload.sessions
  },

  async listEvaluations() {
    const payload = await request<GatewayEvaluationList>('/evaluations')
    return payload.evaluations
  },

  async getEvaluation(id) {
    return request<GatewayEvaluationDetail>(`/evaluations/${encodeURIComponent(id)}`)
  },

  async getEvaluationCase(evaluationId, caseId) {
    const payload = await request<GatewayEvaluationCase>(`/evaluations/${encodeURIComponent(evaluationId)}/cases/${encodeURIComponent(caseId)}`)
    return { ...payload, case: mapEvaluationCase(evaluationId, payload.case) }
  },

  async getEvaluationHistory(evaluationId, caseId, afterSequence = 0) {
    const payload = await request<GatewayRunHistory>(
      `/evaluations/${encodeURIComponent(evaluationId)}/cases/${encodeURIComponent(caseId)}/history?after=${Math.max(0, afterSequence)}`,
    )
    return {
      run: payload.run,
      events: payload.events.map((event) => mapEvaluationEvent(event, evaluationId, caseId)),
      historyGap: payload.historyGap,
      firstSequence: payload.firstSequence,
      integrity: payload.integrity,
    }
  },

  async getEvaluationHistoryDetails(evaluationId, caseId, afterRecordSequence = 0) {
    const payload = await request<GatewayEvaluationHistoryDetails>(
      `/evaluations/${encodeURIComponent(evaluationId)}/cases/${encodeURIComponent(caseId)}/history/details?after_record=${Math.max(0, afterRecordSequence)}`,
    )
    return {
      ...payload,
      entries: payload.entries.map((entry) => mapEvaluationDetailEntry(entry, evaluationId, caseId)),
    }
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

  attachmentContentUrl,
  generatedArtifactUrl,

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

  async resumeRun(sessionId, runId, options: RunResumeOptions) {
    const payload = await request<GatewayRunResponse>(`/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
      body: JSON.stringify(options.cursorId ? { cursorId: options.cursorId } : {}),
      headers: { 'Idempotency-Key': options.idempotencyKey },
    })
    return mapRun(payload)
  },

  async getRunHistory(sessionId, runId, afterSequence = 0) {
    const payload = await request<GatewayRunHistory>(`/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}?after=${Math.max(0, afterSequence)}`)
    const history: RunHistory = {
      run: payload.run,
      events: payload.events.map((event) => mapRunEvent(event, sessionId)),
      historyGap: payload.historyGap,
      firstSequence: payload.firstSequence,
      integrity: payload.integrity,
    }
    return history
  },

  subscribeRun(sessionId, runId, callbacks: RunEventCallbacks, afterSequence = 0): RunSubscription {
    return subscribeRun(currentGatewayBaseUrl(), sessionId, runId, callbacks, afterSequence)
  },

  async submitMessage(sessionId, text, attachmentIds = [], provider) {
    return mapSessionData(await request<GatewaySessionData>(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds, ...(provider ? { provider } : {}) }),
    }))
  },
}
