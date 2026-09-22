import type { AgentRunEvent, FailureContext } from '../types/protocol'

export function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

export function eventPayload(event: AgentRunEvent): Record<string, unknown> {
  return event.payload || {}
}

export function failureContext(payload: Record<string, unknown>): FailureContext | null {
  const nested = [
    recordValue(payload.result),
    recordValue(payload.data),
    recordValue(payload.error),
    recordValue(payload.source_scope_resolution),
    recordValue(payload.sourceScopeResolution),
    recordValue(payload.measurement_gate),
    recordValue(payload.measurementGate),
  ].filter((item): item is Record<string, unknown> => Boolean(item))
  const candidates = [payload, ...nested]
  const first = (...keys: string[]): unknown => {
    for (const candidate of candidates) {
      for (const key of keys) if (candidate[key] !== undefined && candidate[key] !== null && candidate[key] !== '') return candidate[key]
    }
    return undefined
  }
  const issues = candidates.flatMap((candidate) => Array.isArray(candidate.issues) ? candidate.issues.map(recordValue).filter((item): item is Record<string, unknown> => Boolean(item)) : [])
  const issue = issues[0]
  const hasErrorShape = candidates.some((candidate) => candidate.error !== undefined || candidate.status === 'error' || candidate.state === 'error') || issues.length > 0
  const category = first('failure_category', 'failureCategory') || (hasErrorShape ? 'tool_rejected' : undefined)
  const code = first('failure_code', 'failureCode', 'error_code', 'errorCode', 'code')
  const safeMessage = first('safe_message', 'safeMessage', 'message') || (hasErrorShape ? first('error') : undefined) || issue?.message
  const location = first('location', 'field_location', 'fieldLocation') || issue?.location
  const providerStatus = first('provider_status', 'providerStatus')
  const actionHintValue = first('action_hint', 'actionHint', 'next_action', 'nextAction')
  const actionHint = typeof actionHintValue === 'string' ? actionHintValue : undefined
  const retryable = first('retryable')
  const outcomeKnown = first('outcome_known', 'outcomeKnown')
  const firstFailureRef = first('first_failure_ref', 'firstFailureRef')
  if (category === undefined && code === undefined && safeMessage === undefined && location === undefined && providerStatus === undefined && actionHint === undefined) return null
  return {
    ...(category !== undefined ? { category: String(category) } : {}),
    ...(code !== undefined ? { code: String(code) } : {}),
    ...(location !== undefined ? { location: String(location) } : {}),
    ...(providerStatus !== undefined && Number.isFinite(Number(providerStatus)) ? { providerStatus: Number(providerStatus) } : {}),
    ...(safeMessage !== undefined ? { safeMessage: String(safeMessage) } : {}),
    ...(typeof retryable === 'boolean' ? { retryable } : {}),
    ...(typeof outcomeKnown === 'boolean' ? { outcomeKnown } : {}),
    ...(firstFailureRef && typeof firstFailureRef === 'object' ? { firstFailureRef: firstFailureRef as Record<string, unknown> } : {}),
    ...(actionHint !== undefined ? { actionHint: String(actionHint) } : {}),
  }
}

export function boundedDisplayText(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  if (!normalized) return undefined
  const redacted = normalized.replace(/(?:[A-Za-z]:[\\/]|\/(?:Users|home|private|tmp|var|opt|etc)\/)[^\s"'`，。；;]+/g, '[已隐藏路径]')
  return redacted.slice(0, 120)
}

export function textDetail(value: unknown): string {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return '事件内容不可显示' }
}
