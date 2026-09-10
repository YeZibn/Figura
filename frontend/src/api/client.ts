import type { AgentRunEvent, Attachment, RunHandle, Session, SessionData } from '../types/protocol'

export type RunSubscription = { close(): void }

export type RunEventCallbacks = {
  onEvent(event: AgentRunEvent): void
  onError(error: Error): void
  onComplete(): void
}

export type ChartAgentClient = {
  listSessions(): Promise<Session[]>
  getSession(id: string): Promise<SessionData>
  createSession(name: string): Promise<SessionData>
  listAttachments(sessionId: string): Promise<Attachment[]>
  uploadAttachment(sessionId: string, file: File): Promise<Attachment>
  startRun(sessionId: string, text: string, attachmentIds?: string[]): Promise<RunHandle>
  subscribeRun(sessionId: string, runId: string, callbacks: RunEventCallbacks): RunSubscription
  submitMessage(sessionId: string, text: string, attachmentIds?: string[]): Promise<SessionData>
}
