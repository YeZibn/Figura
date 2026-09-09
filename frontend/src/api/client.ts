import type { Session, SessionData } from '../types/protocol'

export type ChartAgentClient = {
  listSessions(): Promise<Session[]>
  getSession(id: string): Promise<SessionData>
  createSession(name: string): Promise<SessionData>
  submitMessage(sessionId: string, text: string): Promise<SessionData>
}
