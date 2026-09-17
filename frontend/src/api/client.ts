import type { AgentRunEvent, Attachment, GatewayHealth, Provider, RunHandle, RunHistory, Session, SessionData } from '../types/protocol'

export type RunStartOptions = { idempotencyKey?: string; retryOf?: string }

export type RunSubscription = { close(): void }

export type RunEventCallbacks = {
  onEvent(event: AgentRunEvent): void
  onError(error: Error): void
  onComplete(): void
}

export type ChartAgentClient = {
  getHealth(): Promise<GatewayHealth>
  listSessions(): Promise<Session[]>
  getSession(id: string): Promise<SessionData>
  createSession(name: string): Promise<SessionData>
  deleteSession(id: string): Promise<void>
  listAttachments(sessionId: string): Promise<Attachment[]>
  uploadAttachment(sessionId: string, file: File): Promise<Attachment>
  deleteAttachment(sessionId: string, attachmentId: string): Promise<void>
  interruptRun(sessionId: string, runId: string): Promise<RunHandle>
  attachmentContentUrl(sessionId: string, attachmentId: string): string
  generatedArtifactUrl(sessionId: string, runId: string, artifactId: string): string
  startRun(sessionId: string, text: string, attachmentIds?: string[], provider?: Provider, options?: RunStartOptions): Promise<RunHandle>
  getRunHistory(sessionId: string, runId: string, afterSequence?: number): Promise<RunHistory>
  subscribeRun(sessionId: string, runId: string, callbacks: RunEventCallbacks, afterSequence?: number): RunSubscription
  submitMessage(sessionId: string, text: string, attachmentIds?: string[], provider?: Provider): Promise<SessionData>
}
