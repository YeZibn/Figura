import type { ChartAgentClient } from './client'
import type { Attachment, EvaluationCaseData, EvaluationDetail, EvaluationHistory, EvaluationHistoryDetails, EvaluationSummary, GatewayHealth, Provider, RunHandle, RunHistory, Session, SessionData } from '../types/protocol'
import type { RunResumeOptions, RunStartOptions } from './client'

/**
 * Workspace-level API groups the client façade by the workspaces that consume it.
 * App owns selection and state; request details stay behind this adapter.
 */
export type WorkspaceApi = {
  health: {
    get(): Promise<GatewayHealth>
  }
  sessions: {
    list(): Promise<Session[]>
    get(id: string): Promise<SessionData>
    create(name: string): Promise<SessionData>
    remove(id: string): Promise<void>
  }
  attachments: {
    upload(sessionId: string, file: File): Promise<Attachment>
    remove(sessionId: string, attachmentId: string): Promise<void>
  }
  runs: {
    start(sessionId: string, text: string, attachmentIds: string[], provider: Provider, options: RunStartOptions): Promise<RunHandle>
    resume(sessionId: string, runId: string, options: RunResumeOptions): Promise<RunHandle>
    interrupt(sessionId: string, runId: string): Promise<RunHandle>
    history(sessionId: string, runId: string): Promise<RunHistory>
  }
  evaluations: {
    list(): Promise<EvaluationSummary[]>
    get(id: string): Promise<EvaluationDetail>
    getCase(evaluationId: string, caseId: string): Promise<EvaluationCaseData>
    history(evaluationId: string, caseId: string): Promise<EvaluationHistory>
    historyDetails(evaluationId: string, caseId: string): Promise<EvaluationHistoryDetails>
  }
}

export function createWorkspaceApi(client: ChartAgentClient): WorkspaceApi {
  return {
    health: {
      get: () => client.getHealth(),
    },
    sessions: {
      list: () => client.listSessions(),
      get: (id) => client.getSession(id),
      create: (name) => client.createSession(name),
      remove: (id) => client.deleteSession(id),
    },
    attachments: {
      upload: (sessionId, file) => client.uploadAttachment(sessionId, file),
      remove: (sessionId, attachmentId) => client.deleteAttachment(sessionId, attachmentId),
    },
    runs: {
      start: (sessionId, text, attachmentIds, provider, options) => client.startRun(sessionId, text, attachmentIds, provider, options),
      resume: (sessionId, runId, options) => client.resumeRun(sessionId, runId, options),
      interrupt: (sessionId, runId) => client.interruptRun(sessionId, runId),
      history: (sessionId, runId) => client.getRunHistory(sessionId, runId),
    },
    evaluations: {
      list: () => client.listEvaluations(),
      get: (id) => client.getEvaluation(id),
      getCase: (evaluationId, caseId) => client.getEvaluationCase(evaluationId, caseId),
      history: (evaluationId, caseId) => client.getEvaluationHistory(evaluationId, caseId),
      historyDetails: (evaluationId, caseId) => client.getEvaluationHistoryDetails(evaluationId, caseId),
    },
  }
}
