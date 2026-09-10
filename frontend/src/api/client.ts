import type { Attachment, Session, SessionData } from '../types/protocol'

export type ChartAgentClient = {
  listSessions(): Promise<Session[]>
  getSession(id: string): Promise<SessionData>
  createSession(name: string): Promise<SessionData>
  listAttachments(sessionId: string): Promise<Attachment[]>
  uploadAttachment(sessionId: string, file: File): Promise<Attachment>
  submitMessage(sessionId: string, text: string, attachmentIds?: string[]): Promise<SessionData>
}
