export type PreviewResource =
  | { kind: 'attachment'; sessionId: string; attachmentId: string }
  | { kind: 'observation'; sessionId: string; runId: string; observationId: string }
  | { kind: 'candidate'; sessionId: string; runId: string; candidateId: string }
  | { kind: 'artifact'; sessionId: string; runId: string; artifactId: string }
  | { kind: 'evaluation'; evaluationId: string; caseId: string; resourceId: string }

export type PreviewLoadResult = {
  url: string
  contentType?: string
  temporary: boolean
}
