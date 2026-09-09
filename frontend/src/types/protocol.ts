export type Session = {
  id: string
  name: string
  updatedAt: string
  runCount: number
}

export type AttachmentStatus = 'registered' | 'loaded' | 'observation'

export type Attachment = {
  id: string
  filename: string
  mediaType: string
  byteCount: number
  previewUrl: string
  status: AttachmentStatus
}

export type ConversationItem =
  | { id: string; kind: 'user'; text: string; timestamp: string; attachmentIds?: string[] }
  | { id: string; kind: 'assistant'; text: string; timestamp: string }
  | { id: string; kind: 'tool_call'; toolName: string; status: 'success' | 'running' | 'error'; detail: string; timestamp: string }
  | { id: string; kind: 'tool_result'; toolName: string; status: 'success' | 'error'; detail: string; timestamp: string }
  | { id: string; kind: 'visual_observation'; toolName: string; caption: string; imageUrl: string; timestamp: string }
  | { id: string; kind: 'error'; text: string; timestamp: string }

export type SessionData = { session: Session; messages: ConversationItem[]; attachments: Attachment[] }
export type RunState = 'idle' | 'running' | 'completed' | 'error'
