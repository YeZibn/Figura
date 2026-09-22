import { request } from './transport'

export function loadEvaluationResource(evaluationId: string, resourceId: string, caseId: string): Promise<unknown> {
  return request<unknown>(`/evaluations/${encodeURIComponent(evaluationId)}/resources/${encodeURIComponent(resourceId)}?case_id=${encodeURIComponent(caseId)}`)
}

