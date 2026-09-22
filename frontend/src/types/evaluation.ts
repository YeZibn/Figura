import type { PreviewResource } from './preview'
import type { GeneratedChartReference, HistoryIntegrity, ObservationReference, RunHistory, RunSummary } from './run'

export type EvaluationHistory = RunHistory

export type EvaluationDetailEntry = {
  entryId: string
  source: 'record' | 'event' | string
  recordSequence?: number | null
  eventSequence?: number | null
  timestamp: string
  kind: string
  recordKind?: string
  role?: 'user' | 'assistant' | 'tool' | 'system' | string
  content?: unknown
  details?: unknown
  toolCalls?: unknown
  toolName?: string
  toolDisplayName?: string
  toolLabel?: string
  callId?: string
  status?: string
  code?: string
  reason?: string
  arguments?: unknown
  result?: unknown
  observations?: ObservationReference[]
  artifacts?: GeneratedChartReference[]
  detailResource?: EvaluationResource
  detailUnavailable?: boolean
  detailUnavailableReason?: string
  integrity?: HistoryIntegrity
  truncated?: boolean
  redacted?: boolean
}

export type EvaluationHistoryDetails = {
  run: RunSummary
  entries: EvaluationDetailEntry[]
  recordsAvailable: boolean
  eventsAvailable: boolean
  sourceAvailability: { records: boolean; gatewayEvents: boolean }
  recordCount: number
  eventCount: number
  historyGap: boolean
  firstRecordSequence?: number | null
  firstEventSequence?: number | null
  truncated: boolean
  redacted: boolean
  notice?: string | null
  integrity?: HistoryIntegrity
}

export type EvaluationStatus = 'running' | 'completed' | 'partial' | 'blocked'
export type EvaluationCaseStatus = 'pending' | 'running' | 'completed' | 'failed' | 'interrupted' | 'blocked' | 'not_run' | 'unknown'

export type EvaluationFailure = {
  code?: string
  category?: string
  stage?: string
  sequence?: number
  message?: string
}

export type EvaluationSummary = {
  evaluationId: string
  status: EvaluationStatus
  provider?: string | null
  model?: string | null
  startedAt?: string | null
  endedAt?: string | null
  updatedAt?: string | null
  caseCount: number
  caseCounts: Record<string, number>
  firstFailure?: EvaluationFailure | null
}

export type EvaluationCaseSummary = {
  evaluationId: string
  caseId: string
  status: EvaluationCaseStatus
  sessionId?: string | null
  runId?: string | null
  sha256?: string | null
  firstFailure?: EvaluationFailure | null
  error?: { code?: string; message?: string } | null
}

export type EvaluationResource = {
  resourceId: string
  caseId: string
  kind: string
  label: string
  mediaType: string
  byteCount: number
  sha256?: string
  previewResource?: PreviewResource
}

export type EvaluationStage = {
  name: string
  status: string
  sequences: number[]
  panelIds: string[]
  attemptIds: string[]
  artifactIds: string[]
  observationIds: string[]
  errors: string[]
  notes: string[]
}

export type EvaluationTimeline = {
  stages: EvaluationStage[]
  anomalies: Array<{ code?: string; category?: string; stage?: string; sequence?: number; message?: string }>
  historyGap: boolean
  firstFailure?: EvaluationFailure | null
}

export type EvaluationReport = {
  available: boolean
  source: string
  text: string
  truncated: boolean
}

export type EvaluationPanelHint = {
  name: string
  chartType?: string
  role?: string
  bboxNorm?: number[]
}

export type EvaluationCase = EvaluationCaseSummary & {
  asset?: string | null
  expectedPanels: EvaluationPanelHint[]
  timeline: EvaluationTimeline
  report: EvaluationReport
  resources: EvaluationResource[]
}

export type EvaluationDetail = {
  evaluation: EvaluationSummary
  cases: EvaluationCaseSummary[]
  report: { available: boolean; source: string; truncated: boolean }
}

export type EvaluationCaseData = {
  evaluationId: string
  case: EvaluationCase
}
