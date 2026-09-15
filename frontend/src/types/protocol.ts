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

export type SessionData = { session: Session; messages: ConversationItem[]; attachments: Attachment[]; runs: RunSummary[] }
export type RunStatus = 'running' | 'completed' | 'failed' | 'interrupted'
export type RunState = 'idle' | 'connecting' | 'running' | 'completed' | 'failed' | 'interrupted' | 'unavailable'

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
}

export type RunHandle = {
  runId: string
  sessionId: string
  status: 'running'
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

export type RunHistory = {
  run: RunSummary
  events: AgentRunEvent[]
  historyGap: boolean
  firstSequence?: number | null
}

export type GatewayAgentStatus = {
  status: 'ready' | 'unavailable' | 'unknown'
  reason?: string
}

export type GatewayHealth = {
  version: 'v1'
  status: 'ok'
  service: string
  agent?: GatewayAgentStatus
}
