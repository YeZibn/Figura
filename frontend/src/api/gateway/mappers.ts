import type { AgentRunEvent, Attachment, EvaluationCase, EvaluationDetailEntry, EvaluationResource, GeneratedChartReference, ObservationReference, PreviewResource, RunHandle, SessionData } from '../../types/protocol'
import { mediaTypeForFile } from '../../attachments'
import { currentGatewayBaseUrl } from './transport'
import type { GatewayAttachment, GatewayEvaluationCase, GatewayRunEvent, GatewayRunResponse, GatewaySessionData } from './types'

export function attachmentContentUrl(sessionId: string, attachmentId: string): string {
  return `${currentGatewayBaseUrl()}/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}/content`
}

export function attachmentPreviewResource(sessionId: string, attachmentId: string): PreviewResource {
  return { kind: 'attachment', sessionId, attachmentId }
}

export function generatedArtifactUrl(sessionId: string, runId: string, artifactId: string): string {
  return `${currentGatewayBaseUrl()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`
}

export function generatedCandidateUrl(sessionId: string, runId: string, candidateId: string): string {
  return `${currentGatewayBaseUrl()}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidateId)}`
}

export function chartPreviewResource(sessionId: string, runId: string, reference: GeneratedChartReference): PreviewResource | undefined {
  if (reference.artifactId) return { kind: 'artifact', sessionId, runId, artifactId: reference.artifactId }
  if (reference.candidateId) return { kind: 'candidate', sessionId, runId, candidateId: reference.candidateId }
  return undefined
}

export function evaluationPreviewResource(evaluationId: string, caseId: string, value: Partial<EvaluationResource>): PreviewResource | undefined {
  if (!value.resourceId || !value.caseId) return undefined
  return { kind: 'evaluation', evaluationId, caseId: value.caseId || caseId, resourceId: value.resourceId }
}

export function mapEvaluationResource(evaluationId: string, caseId: string, value: EvaluationResource): EvaluationResource {
  const previewResource = value.mediaType.startsWith('image/') ? evaluationPreviewResource(evaluationId, caseId, value) : undefined
  return { ...value, previewResource }
}

export function mapEvaluationCase(evaluationId: string, value: EvaluationCase): EvaluationCase {
  return { ...value, resources: (value.resources || []).map((resource) => mapEvaluationResource(evaluationId, value.caseId, resource)) }
}

export function mapEvaluationDetailEntry(entry: EvaluationDetailEntry, evaluationId: string, caseId: string): EvaluationDetailEntry {
  const observations = Array.isArray(entry.observations)
    ? entry.observations.map((observation) => {
      const resource = observation.previewResource
      if (!resource || typeof resource !== 'object') return observation
      const mapped = evaluationPreviewResource(evaluationId, caseId, resource as Partial<EvaluationResource>)
      return mapped ? { ...observation, previewResource: mapped } : observation
    })
    : entry.observations
  const artifacts = Array.isArray(entry.artifacts)
    ? entry.artifacts.map((artifact) => {
      const resource = artifact.previewResource
      if (!resource || typeof resource !== 'object') return artifact
      const mapped = evaluationPreviewResource(evaluationId, caseId, resource as Partial<EvaluationResource>)
      return mapped ? { ...artifact, previewResource: mapped } : artifact
    })
    : entry.artifacts
  return { ...entry, observations, artifacts }
}

export function mapEvaluationEvent(event: GatewayRunEvent, evaluationId: string, caseId: string): AgentRunEvent {
  const payload = { ...(event.payload || {}) }
  if (event.kind === 'visual_observation' && Array.isArray(payload.observations)) {
    payload.observations = payload.observations.map((item) => {
      if (!item || typeof item !== 'object') return item
      const observation = item as Record<string, unknown>
      const resource = observation.previewResource
      if (!resource || typeof resource !== 'object') return item
      const mapped = evaluationPreviewResource(evaluationId, caseId, resource as Partial<EvaluationResource>)
      return mapped ? { ...observation, previewResource: mapped } : item
    })
  }
  if (event.kind === 'generated_chart' && Array.isArray(payload.artifacts)) {
    payload.artifacts = payload.artifacts.map((item) => {
      if (!item || typeof item !== 'object') return item
      const artifact = item as Record<string, unknown>
      const resource = artifact.previewResource
      if (!resource || typeof resource !== 'object') return item
      const mapped = evaluationPreviewResource(evaluationId, caseId, resource as Partial<EvaluationResource>)
      return mapped ? { ...artifact, previewResource: mapped } : item
    })
  }
  const detailResource = payload.detailResource
  if (detailResource && typeof detailResource === 'object') {
    const mapped = evaluationPreviewResource(evaluationId, caseId, detailResource as Partial<EvaluationResource>)
    if (mapped) payload.detailResource = { ...(detailResource as Record<string, unknown>), previewResource: mapped }
  }
  return { runId: event.runId, sequence: event.sequence, kind: event.kind, timestamp: event.timestamp, payload }
}

export function mapAttachment(item: GatewayAttachment, sessionId?: string): Attachment {
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

export function mapSessionData(payload: GatewaySessionData): SessionData {
  return { ...payload, runs: payload.runs || [], attachments: payload.attachments.map((item) => mapAttachment(item, payload.session.id)) }
}

export function mapRun(payload: GatewayRunResponse): RunHandle {
  return payload.run
}

export function mapRunEvent(event: GatewayRunEvent, sessionId: string): AgentRunEvent {
  const payload = { ...(event.payload || {}) }
  if (event.kind === 'visual_observation' && Array.isArray(payload.observations)) {
    payload.observations = payload.observations.map((item) => {
      if (!item || typeof item !== 'object') return item
      const reference = item as Partial<ObservationReference>
      if (!reference.observationId) return item
      return { ...reference, previewResource: { kind: 'observation', sessionId, runId: event.runId, observationId: reference.observationId } }
    })
  }
  if (event.kind === 'generated_chart' && Array.isArray(payload.artifacts)) {
    payload.artifacts = payload.artifacts.map((item) => {
      if (!item || typeof item !== 'object') return item
      const reference = item as Partial<GeneratedChartReference>
      if (reference.status === 'unavailable') return item
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

export { mediaTypeForFile }
