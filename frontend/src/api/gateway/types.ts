import type { AgentRunEvent, Attachment, EvaluationCase, EvaluationCaseData, EvaluationDetail, EvaluationDetailEntry, EvaluationHistoryDetails, EvaluationResource, EvaluationSummary, GatewayHealth, GeneratedChartReference, ObservationReference, PreviewResource, RunHandle, RunHistory, RunSummary, Session, SessionData } from '../../types/protocol'

export type GatewaySessionList = { sessions: Session[] }
export type GatewayAttachment = {
  attachment_id: string
  filename: string
  media_type: string
  byte_count: number
  sha256?: string
  status?: Attachment['status']
  preview_available?: boolean
}
export type GatewaySessionData = Omit<SessionData, 'attachments'> & { attachments: GatewayAttachment[] }
export type GatewayRunResponse = { run: RunHandle }
export type GatewayRunEvent = { runId: string; sequence: number; kind: string; timestamp: string; payload?: Record<string, unknown> }
export type GatewayRunHistory = { run: RunSummary; events: GatewayRunEvent[]; historyGap: boolean; historyGapCode?: string | null; firstSequence?: number | null; integrity?: RunHistory['integrity'] }
export type GatewayHealthResponse = GatewayHealth
export type GatewayEvaluationList = { evaluations: EvaluationSummary[] }
export type GatewayEvaluationDetail = { evaluation: EvaluationSummary; cases: EvaluationDetail['cases']; report: EvaluationDetail['report'] }
export type GatewayEvaluationCase = { evaluationId: string; case: EvaluationCase }
export type GatewayEvaluationHistoryDetails = EvaluationHistoryDetails

export type GatewayMappedEvent = AgentRunEvent
export type GatewayObservation = ObservationReference
export type GatewayPreviewResource = PreviewResource
export type GatewayChartReference = GeneratedChartReference
export type GatewayEvaluationCaseData = EvaluationCaseData
export type GatewayEvaluationEntry = EvaluationDetailEntry
export type GatewayEvaluationResource = EvaluationResource
