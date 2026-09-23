import type { PreviewResource } from './preview'
import type { Provider } from './provider'

export type RunStatus = 'running' | 'completed' | 'failed' | 'interrupted'
export type RunState = 'idle' | 'connecting' | 'running' | 'reconnecting' | 'cancel_requested' | 'completed' | 'failed' | 'interrupted' | 'history-gap' | 'unavailable'
export type RecoveryStatus = 'available' | 'blocked' | 'unavailable'
export type CheckpointPhase = 'accepted' | 'model' | 'tool' | 'render' | 'review' | 'publication' | 'final'
export type OperationState = 'not_started' | 'in_flight' | 'completed' | 'uncertain'
export type ContinuationKind = 'resume' | 'retry'

export type RunRecovery = {
  status: RecoveryStatus
  checkpointId?: string | null
  checkpointVersion?: number | null
  phase?: CheckpointPhase | string | null
  nextAction?: string | null
  blockedReason?: string | null
  updatedAt?: string | null
  expiresAt?: number | null
}

export type ReviewState = 'reviewing' | 'passed' | 'passed_with_warning' | 'repair_required' | 'failed' | 'exhausted' | 'uncertain' | string
export type ReviewType = 'measurement' | 'generated_chart' | string
export type ReviewIssue = { code?: string; location?: string; message?: string; severity?: string }
export type ExecutionGate = {
  state: 'open' | 'reviewing' | 'repair_required' | 'failed' | 'exhausted' | string
  blocking: boolean
  reviewType?: ReviewType
  reviewId?: string | null
  subjectId?: string | null
  attempt?: number | null
  maxAttempts?: number | null
  remainingAttempts?: number | null
  nextAction?: string | null
  issues?: ReviewIssue[]
  updatedAt?: string | null
}

export type RunSummary = {
  runId: string
  sessionId: string
  status: RunStatus
  createdAt: string
  updatedAt: string
  expiresAt?: number
  eventCount: number
  terminalCode?: string | null
  terminalMessage?: string | null
  answer?: string | null
  historyWarning?: string | null
  provider?: Provider | null
  model?: string | null
  cancelRequested?: boolean
  retryOf?: string | null
  parentRunId?: string | null
  rootRunId?: string | null
  continuationKind?: ContinuationKind | null
  recovery?: RunRecovery | null
  executionGate?: ExecutionGate | null
}

export type RunHandle = {
  runId: string
  sessionId: string
  status: RunStatus
  provider?: Provider | null
  model?: string | null
  terminalCode?: string | null
  terminalMessage?: string | null
  retryOf?: string | null
  parentRunId?: string | null
  rootRunId?: string | null
  continuationKind?: ContinuationKind | null
  recovery?: RunRecovery | null
  executionGate?: ExecutionGate | null
}

export type FailureContext = {
  category?: string
  code?: string
  location?: string
  providerStatus?: number
  safeMessage?: string
  retryable?: boolean
  outcomeKnown?: boolean
  firstFailureRef?: Record<string, unknown>
  actionHint?: string
}

export type ObservationReference = {
  observationId: string
  mediaType: string
  caption: string
  byteCount: number
  imageUrl?: string
  previewResource?: PreviewResource
}

export type GeneratedChartReference = {
  artifactKind: 'generated_chart'
  artifactId?: string
  candidateId?: string
  reviewId?: string
  chartSpecDigest?: string
  mediaType: string
  caption: string
  byteCount?: number
  chartType?: string
  title?: string
  width?: number
  height?: number
  status?: 'available' | 'pending' | 'warning' | 'unavailable' | 'failed' | string
  candidateStatus?: string
  reviewStatus?: string
  publicationStatus?: string
  reviewMode?: string
  figureId?: string
  collectionId?: string
  childChartIds?: string[]
  chartTypes?: string[]
  source?: { attachment_id?: string; panel_id?: string }
  layout?: { type?: string; columns?: number }
  coverage?: { source_series?: string[]; represented_series?: string[]; omitted_series?: string[]; status?: string }
  generationContext?: Record<string, unknown>
  generationContextDigest?: string
  contextStatus?: string
  candidateAttempt?: number
  reviewAttempts?: number
  lineageAttempt?: number
  parentCandidateId?: string
  parentAttempt?: number
  panelIds?: string[]
  sourceAttachmentIds?: string[]
  repairKind?: string
  review?: {
    decision?: string
    confidence?: number
    issues?: ReviewIssue[]
    checks?: Record<string, string>
  }
  reason?: string
  imageUrl?: string
  downloadUrl?: string
  previewResource?: PreviewResource
}

export type AgentRunEvent = {
  runId: string
  sequence: number
  kind: string
  timestamp: string
  payload: Record<string, unknown>
}

export const measurementRepairEventKinds = [
  'measurement_observed',
  'measurement_repair_required',
  'measurement_repair_rejected',
  'measurement_repair_exhausted',
  'measurement_decision_required',
  'measurement_focus_requested',
  'measurement_focus_applied',
  'measurement_focus_failed',
  'measurement_evidence_selected',
  'measurement_evidence_discarded',
  'measurement_evidence_used',
] as const

export type MeasurementRepairEventKind = typeof measurementRepairEventKinds[number]

export type MeasurementRepairSummary = {
  panelId?: string
  attemptId?: string
  parentAttemptId?: string
  targetType?: string
  status?: string
  code?: string
  reason?: string
  nextAction?: string
  budgetRemaining?: number
  selectedRefs?: string[]
  discardedRefs?: string[]
  observationScope?: Record<string, unknown>
}

export function isMeasurementRepairEventKind(kind: string): kind is MeasurementRepairEventKind {
  return (measurementRepairEventKinds as readonly string[]).includes(kind)
}

export type HistoryIntegrity = {
  status: 'complete' | 'redacted' | 'truncated' | 'unavailable' | string
  source?: string
  recordsAvailable?: boolean
  eventCount?: number
  detailResourceCount?: number
  unavailableCount?: number
  redactedCount?: number
  persistedTruncatedCount?: number
  projectionTruncatedCount?: number
  persistedTruncated?: boolean
  projectionTruncated?: boolean
  detailUnavailable?: boolean
  reason?: string | null
}

export type RunHistory = {
  run: RunSummary
  events: AgentRunEvent[]
  historyGap: boolean
  firstSequence?: number | null
  integrity?: HistoryIntegrity
}
