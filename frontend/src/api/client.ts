import type { AgentRunEvent, Attachment, EvaluationCaseData, EvaluationDetail, EvaluationHistory, EvaluationHistoryDetails, EvaluationSummary, GatewayHealth, Provider, RunHandle, RunHistory, Session, SessionData } from '../types/protocol'

export type RunStartOptions = { idempotencyKey?: string; retryOf?: string }
export type RunResumeOptions = { idempotencyKey: string; checkpointId?: string }

export type RunSubscription = { close(): void }

export type RunEventCallbacks = {
  onEvent(event: AgentRunEvent): void
  onError(error: Error): void
  onComplete(): void
}

export type ChartAgentClient = {
  getHealth(): Promise<GatewayHealth>
  listSessions(): Promise<Session[]>
  listEvaluations(): Promise<EvaluationSummary[]>
  getEvaluation(id: string): Promise<EvaluationDetail>
  getEvaluationCase(evaluationId: string, caseId: string): Promise<EvaluationCaseData>
  getEvaluationHistory(evaluationId: string, caseId: string, afterSequence?: number): Promise<EvaluationHistory>
  getEvaluationHistoryDetails(evaluationId: string, caseId: string, afterRecordSequence?: number): Promise<EvaluationHistoryDetails>
  getSession(id: string): Promise<SessionData>
  createSession(name: string): Promise<SessionData>
  deleteSession(id: string): Promise<void>
  listAttachments(sessionId: string): Promise<Attachment[]>
  uploadAttachment(sessionId: string, file: File): Promise<Attachment>
  deleteAttachment(sessionId: string, attachmentId: string): Promise<void>
  interruptRun(sessionId: string, runId: string): Promise<RunHandle>
  resumeRun(sessionId: string, runId: string, options: RunResumeOptions): Promise<RunHandle>
  attachmentContentUrl(sessionId: string, attachmentId: string): string
  generatedArtifactUrl(sessionId: string, runId: string, artifactId: string): string
  startRun(sessionId: string, text: string, attachmentIds?: string[], provider?: Provider, options?: RunStartOptions): Promise<RunHandle>
  getRunHistory(sessionId: string, runId: string, afterSequence?: number): Promise<RunHistory>
  subscribeRun(sessionId: string, runId: string, callbacks: RunEventCallbacks, afterSequence?: number): RunSubscription
  submitMessage(sessionId: string, text: string, attachmentIds?: string[], provider?: Provider): Promise<SessionData>
}
