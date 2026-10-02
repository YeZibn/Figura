import type { AgentRunEvent, Attachment, ChartRenderSummary, RunHandle, RunHistory, Session, SessionData } from '../../types/protocol'
import type { RunSubscription } from '../client'

export type FiguraProviderId = 'qwen' | 'deepseek' | 'mimo'
export type FiguraProviderAvailability = {
  providerId: FiguraProviderId
  modelId: string
  available: boolean
  reasonCode: string | null
}
export type FiguraHealth = {
  version: 'v1'
  status: 'ok'
  service: 'figura'
  providers: FiguraProviderAvailability[]
}
export type FiguraSessionDto = {
  id: string
  name: string | null
  createdAt: string
  updatedAt: string
  runCount: number
}
export type FiguraAttachmentDto = {
  id: string
  filename: string
  mediaType: string
  byteCount: number
  createdAt: string
}
export type FiguraPanelDto = {
  panelId: string
  runId: string
  sourceAttachmentId: string
  name: string
  points: Array<{ x: number; y: number }>
}
export type FiguraChartRenderDto = ChartRenderSummary
export type FiguraMessageDto = {
  id: string
  runId: string
  kind: 'user' | 'assistant'
  text: string
  timestamp: string
  attachmentIds?: string[]
}
export type FiguraRunDto = {
  runId: string
  sessionId: string
  ordinal: number
  status: 'running' | 'completed' | 'failed' | 'interrupted'
  provider: FiguraProviderId
  model: string
  createdAt: string
  startedAt: string
  finishedAt: string | null
  terminalCode: string | null
  terminalMessage: string | null
  executionState: 'active' | 'needs_reconciliation'
  chartRenders: FiguraChartRenderDto[]
}
export type FiguraSessionDataDto = {
  session: FiguraSessionDto
  messages: FiguraMessageDto[]
  attachments: FiguraAttachmentDto[]
  runs: FiguraRunDto[]
}
export type FiguraEventDto = {
  runId: string
  sequence: number
  kind: string
  timestamp: string
  payload: Record<string, unknown>
}
export type FiguraRunHistoryDto = {
  run: FiguraRunDto
  events: FiguraEventDto[]
  historyGap: boolean
}
export type FiguraToolTimelineStatus =
  | 'pending'
  | 'running'
  | 'needs_reconciliation'
  | 'unknown'
  | 'completed'
  | 'failed'
  | 'not_started'
export type FiguraToolTimelineStepDto = {
  callId: string
  toolSequence: number
  toolName: string
  createdAt: string
  updatedAt: string
  status: FiguraToolTimelineStatus
  summary: string
}
export type FiguraToolTimelineSnapshotDto = {
  runId: string
  steps: FiguraToolTimelineStepDto[]
}
export type FiguraToolTimelineSourceDto = {
  kind: 'attachment' | 'panel'
  id: string
  name: string
}
export type FiguraToolAttemptDto = {
  attemptNumber: number
  startedAt: string
  finishedAt: string | null
  status: 'running' | 'completed' | 'failed' | 'unknown'
  errorSummary: string | null
}
export type FiguraToolCallDetailDto = {
  runId: string
  callId: string
  toolName: string
  status: FiguraToolTimelineStatus
  createdAt: string
  updatedAt: string
  argumentSummary?: string
  resultSummary?: string
  attempts?: FiguraToolAttemptDto[]
  errorSummary?: string | null
  source?: FiguraToolTimelineSourceDto | null
  observationAvailable?: boolean
}
export type FiguraRunHandleDto = Omit<FiguraRunDto, 'executionState' | 'chartRenders'>

export type FiguraClient = {
  readonly baseUrl: string
  getHealth(): Promise<FiguraHealth>
  listSessions(): Promise<FiguraSessionDto[]>
  getSession(sessionId: string): Promise<FiguraSessionDataDto>
  createSession(name: string): Promise<FiguraSessionDto>
  deleteSession(sessionId: string): Promise<void>
  listAttachments(sessionId: string): Promise<FiguraAttachmentDto[]>
  listPanels(sessionId: string): Promise<FiguraPanelDto[]>
  uploadAttachment(sessionId: string, file: File): Promise<FiguraAttachmentDto>
  deleteAttachment(sessionId: string, attachmentId: string): Promise<void>
  startRun(sessionId: string, text: string, attachmentIds: string[], providerId: FiguraProviderId, idempotencyKey: string): Promise<FiguraRunHandleDto>
  getRunHistory(sessionId: string, runId: string, afterSequence?: number): Promise<FiguraRunHistoryDto>
  getRunTimeline(sessionId: string, runId: string): Promise<FiguraToolTimelineSnapshotDto>
  getRunTimelineCall(sessionId: string, runId: string, callId: string): Promise<FiguraToolCallDetailDto>
  getChartRenderContent(sessionId: string, runId: string, callId: string): Promise<Blob>
  subscribeRun(sessionId: string, runId: string, callbacks: { onEvent(event: AgentRunEvent): void; onError(error: Error): void; onComplete(): void }, afterSequence?: number): RunSubscription
  attachmentContentUrl(sessionId: string, attachmentId: string): string
  panelContentUrl(sessionId: string, panelId: string): string
  chartRenderContentUrl(sessionId: string, runId: string, callId: string): string
  timelineObservationUrl(sessionId: string, runId: string, callId: string): string
}

export type FiguraWorkspaceApi = {
  health: { get(): Promise<FiguraHealth> }
  sessions: {
    list(): Promise<Session[]>
    get(sessionId: string): Promise<SessionData>
    create(name: string): Promise<Session>
    remove(sessionId: string): Promise<void>
  }
  attachments: {
    list(sessionId: string): Promise<Attachment[]>
    upload(sessionId: string, file: File): Promise<Attachment>
    remove(sessionId: string, attachmentId: string): Promise<void>
  }
  panels: {
    list(sessionId: string): Promise<FiguraPanelDto[]>
    contentUrl(sessionId: string, panelId: string): string
  }
  runs: {
    start(sessionId: string, text: string, attachmentIds: string[], providerId: FiguraProviderId, idempotencyKey: string): Promise<RunHandle>
    history(sessionId: string, runId: string, afterSequence?: number): Promise<RunHistory>
    timeline(sessionId: string, runId: string): Promise<FiguraToolTimelineSnapshotDto>
    timelineCall(sessionId: string, runId: string, callId: string): Promise<FiguraToolCallDetailDto>
    chartRenderContent(sessionId: string, runId: string, callId: string): Promise<Blob>
    subscribe(sessionId: string, runId: string, callbacks: { onEvent(event: AgentRunEvent): void; onError(error: Error): void; onComplete(): void }, afterSequence?: number): RunSubscription
    chartRenderContentUrl(sessionId: string, runId: string, callId: string): string
    timelineObservationUrl(sessionId: string, runId: string, callId: string): string
  }
}
