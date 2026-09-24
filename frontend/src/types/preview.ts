export type PreviewResource =
  | { kind: 'attachment'; sessionId: string; attachmentId: string }
  | { kind: 'observation'; sessionId: string; runId: string; observationId: string }
  | { kind: 'staged'; sessionId: string; runId: string; stagedRef: string }
  | { kind: 'artifact'; sessionId: string; runId: string; artifactId: string }
  | { kind: 'evaluation'; evaluationId: string; caseId: string; resourceId: string }

export type PreviewLoadResult = {
  url: string
  contentType?: string
  temporary: boolean
}
