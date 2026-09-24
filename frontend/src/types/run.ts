import type { PreviewResource } from './preview'
import type { Provider } from './provider'

export type RunStatus = 'running' | 'completed' | 'failed' | 'interrupted'
export type RunState = 'idle' | 'connecting' | 'running' | 'reconnecting' | 'cancel_requested' | 'completed' | 'failed' | 'interrupted' | 'history-gap' | 'unavailable'
export type RecoveryStatus = 'available' | 'blocked' | 'unavailable'
export type ContinuationKind = 'resume' | 'retry'

export type RunRecovery = {
  status: RecoveryStatus
  cursorId?: string | null
  nextAction?: string | null
  blockedReason?: string | null
  updatedAt?: string | null
}

export type VerificationStatus = 'pass' | 'pass_with_warning' | 'fail' | 'unavailable'
export type VerificationIssue = { code: string; location: string; message: string; severity: 'warning' | 'error' }
export type ChartVerification = {
  verificationRef: string
  stagedRef: string
  manifestDigest: string
  policyVersion: number
  status: VerificationStatus
  checks: Record<string, string>
  issues: VerificationIssue[]
  decision?: 'pass' | 'pass_with_warning' | 'fail' | null
  confidence?: number | null
  attempt: number
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
  stagedRef?: string
  verificationRef?: string
  chartSpecDigest?: string
  mediaType: string
  caption: string
  byteCount?: number
  chartType?: string
  title?: string
  width?: number
  height?: number
  status?: VerificationStatus
  verification?: ChartVerification
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
  panelIds?: string[]
  sourceAttachmentIds?: string[]
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
