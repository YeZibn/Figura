import type { Attachment, ConversationItem, Provider, RunHandle, RunHistory, RunSummary, Session, SessionData } from '../../types/protocol'
import type { FiguraClient, FiguraMessageDto, FiguraProviderId, FiguraRunDto, FiguraRunHistoryDto, FiguraSessionDataDto, FiguraSessionDto, FiguraWorkspaceApi } from './types'

const figuraProviders = new Set<FiguraProviderId>(['qwen', 'deepseek', 'mimo'])

export function createFiguraWorkspaceApi(client: FiguraClient): FiguraWorkspaceApi {
  return {
    health: { get: () => client.getHealth() },
    sessions: {
      async list() {
        return (await client.listSessions()).map(mapSession)
      },
      async get(sessionId) {
        return mapSessionData(await client.getSession(sessionId), client)
      },
      async create(name) {
        return mapSession(await client.createSession(name))
      },
    },
    attachments: {
      async list(sessionId) {
        return (await client.listAttachments(sessionId)).map((item) => mapAttachment(item, sessionId, client))
      },
      async upload(sessionId, file) {
        return mapAttachment(await client.uploadAttachment(sessionId, file), sessionId, client)
      },
      remove: (sessionId, attachmentId) => client.deleteAttachment(sessionId, attachmentId),
    },
    panels: {
      list: (sessionId) => client.listPanels(sessionId),
      contentUrl: (sessionId, panelId) => client.panelContentUrl(sessionId, panelId),
    },
    runs: {
      async start(sessionId, text, attachmentIds, providerId, idempotencyKey) {
        return mapRunHandle(await client.startRun(sessionId, text, attachmentIds, providerId, idempotencyKey))
      },
      async history(sessionId, runId, afterSequence) {
        return mapRunHistory(await client.getRunHistory(sessionId, runId, afterSequence))
      },
      subscribe: (sessionId, runId, callbacks, afterSequence) => client.subscribeRun(sessionId, runId, callbacks, afterSequence),
      chartRenderContentUrl: (sessionId, runId, callId) => client.chartRenderContentUrl(sessionId, runId, callId),
    },
  }
}

export function mapSessionData(dto: FiguraSessionDataDto, client: FiguraClient): SessionData {
  return {
    session: mapSession(dto.session),
    messages: dto.messages.map(mapMessage),
    attachments: dto.attachments.map((item) => mapAttachment(item, dto.session.id, client)),
    runs: dto.runs.map(mapRun),
  }
}

function mapSession(dto: FiguraSessionDto): Session {
  return {
    id: dto.id,
    name: dto.name || '未命名会话',
    updatedAt: dto.updatedAt,
    runCount: dto.runCount,
  }
}

function mapMessage(dto: FiguraMessageDto): ConversationItem {
  if (dto.kind === 'user') {
    return {
      id: dto.id,
      kind: 'user',
      text: dto.text,
      timestamp: dto.timestamp,
      ...(dto.attachmentIds?.length ? { attachmentIds: [...dto.attachmentIds] } : {}),
    }
  }
  return { id: dto.id, kind: 'assistant', text: dto.text, timestamp: dto.timestamp }
}

function mapAttachment(dto: { id: string; filename: string; mediaType: string; byteCount: number }, sessionId: string, client: FiguraClient): Attachment {
  return {
    id: dto.id,
    filename: dto.filename,
    mediaType: dto.mediaType,
    byteCount: dto.byteCount,
    status: 'registered',
    previewAvailable: true,
    previewUrl: client.attachmentContentUrl(sessionId, dto.id),
  }
}

function mapRun(dto: FiguraRunDto): RunSummary {
  return {
    runId: dto.runId,
    sessionId: dto.sessionId,
    status: dto.status,
    createdAt: dto.createdAt,
    updatedAt: dto.finishedAt || dto.createdAt,
    eventCount: 0,
    provider: mapProvider(dto.provider),
    model: dto.model,
    terminalCode: dto.terminalCode,
    terminalMessage: dto.terminalMessage,
    executionState: dto.executionState,
    chartRenders: dto.chartRenders,
  }
}

function mapRunHandle(dto: Omit<FiguraRunDto, 'executionState' | 'chartRenders'>): RunHandle {
  return {
    runId: dto.runId,
    sessionId: dto.sessionId,
    status: dto.status,
    provider: mapProvider(dto.provider),
    model: dto.model,
    terminalCode: dto.terminalCode,
    terminalMessage: dto.terminalMessage,
  }
}

function mapRunHistory(dto: FiguraRunHistoryDto): RunHistory {
  const events = dto.events.map((event) => ({
    runId: event.runId,
    sequence: event.sequence,
    kind: event.kind,
    timestamp: event.timestamp,
    payload: event.payload,
  }))
  const run = mapRun(dto.run)
  return {
    run: { ...run, eventCount: Math.max(run.eventCount, ...events.map((event) => event.sequence), 0) },
    events,
    historyGap: dto.historyGap,
  }
}

function mapProvider(provider: FiguraProviderId): Provider | null {
  return figuraProviders.has(provider) ? provider as Provider : null
}
