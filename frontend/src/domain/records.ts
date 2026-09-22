import type { AgentRunEvent } from '../types/protocol'

export function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

export function eventPayload(event: AgentRunEvent): Record<string, unknown> {
  return event.payload || {}
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
