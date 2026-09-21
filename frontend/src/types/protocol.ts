export type Session = {
  id: string
  name: string
  updatedAt: string
  runCount: number
}

export type AttachmentStatus = 'pending' | 'uploading' | 'registered' | 'unavailable' | 'loaded' | 'observation' | 'error'

export type Attachment = {
  id: string
  filename: string
  mediaType: string
  byteCount: number
  sha256?: string
  previewUrl?: string
  status: AttachmentStatus
  previewAvailable?: boolean
  previewResource?: PreviewResource
  error?: string
}

export type PreviewResource =
  | { kind: 'attachment'; sessionId: string; attachmentId: string }
  | { kind: 'observation'; sessionId: string; runId: string; observationId: string }
  | { kind: 'candidate'; sessionId: string; runId: string; candidateId: string }
  | { kind: 'artifact'; sessionId: string; runId: string; artifactId: string }
  | { kind: 'evaluation'; evaluationId: string; caseId: string; resourceId: string }

export type PreviewLoadResult = {
  url: string
  contentType?: string
  temporary: boolean
}

export type ConversationItem =
  | { id: string; kind: 'user'; text: string; timestamp: string; attachmentIds?: string[]; associationStatus?: string }
  | { id: string; kind: 'assistant'; text: string; timestamp: string; associationStatus?: string }
  | { id: string; kind: 'tool_call'; toolName: string; status: 'success' | 'running' | 'error'; detail: string; timestamp: string }
  | { id: string; kind: 'tool_result'; toolName: string; status: 'success' | 'error'; detail: string; timestamp: string }
  | { id: string; kind: 'visual_observation'; toolName: string; caption: string; imageUrl?: string; previewResource?: PreviewResource; timestamp: string }
  | { id: string; kind: 'error'; text: string; timestamp: string }

export type SessionData = { session: Session; messages: ConversationItem[]; attachments: Attachment[]; runs: RunSummary[]; activeSourceAttachmentIds?: string[] }
export type RunStatus = 'running' | 'completed' | 'failed' | 'interrupted'
export type RunState = 'idle' | 'connecting' | 'running' | 'reconnecting' | 'cancel_requested' | 'completed' | 'failed' | 'interrupted' | 'history-gap' | 'unavailable'
export type Provider = 'openai' | 'qwen' | 'deepseek'
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
  repairAction?: Record<string, unknown> | null
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

export type RunHistory = {
  run: RunSummary
  events: AgentRunEvent[]
  historyGap: boolean
  firstSequence?: number | null
  integrity?: HistoryIntegrity
}

export type EvaluationHistory = RunHistory

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

export type GatewayAgentStatus = {
  status: 'ready' | 'unavailable' | 'unknown'
  reason?: string
  provider?: Provider
  model?: string
}

export type GatewayProviderStatus = {
  status: 'ready' | 'unavailable' | 'unknown'
  reason?: string
  provider?: Provider
  model?: string
}

export type GatewayHealth = {
  version: 'v1'
  status: 'ok'
  service: string
  agent?: GatewayAgentStatus & {
    providers?: Partial<Record<Provider, GatewayProviderStatus>>
  }
}
