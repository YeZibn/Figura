import type { AgentRunEvent } from '../types/protocol'
import { eventPayload, recordValue } from './records'

export const reviewEventKinds = new Set(['review_started', 'review_completed', 'review_repair_required', 'review_failed', 'review_subcheck', 'generated_chart_published', 'generated_chart_rejected'])

export function isReviewEvent(event: AgentRunEvent): boolean {
  return reviewEventKinds.has(event.kind)
}

export function reviewIssues(payload: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(payload.issues)
    ? payload.issues.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')).slice(0, 4)
    : []
}

export function reviewTypeLabel(value: unknown): string {
  if (value === 'measurement') return '测量审核'
  if (value === 'generated_chart') return '生成图审核'
  return '审核'
}

export function reviewStateLabel(value: unknown, blocking: boolean): string {
  if (value === 'reviewing') return '审核中'
  if (value === 'passed') return '已通过'
  if (value === 'passed_with_warning') return '已通过·有警告'
  if (value === 'repair_required') return '需要修复'
  if (value === 'exhausted') return '修复次数已耗尽'
  if (value === 'failed') return '未通过'
  if (value === 'uncertain') return '结果不确定'
  return blocking ? '主链路已暂停' : '审核状态已更新'
}

export function reviewEventState(event: AgentRunEvent): { payload: Record<string, unknown>; domain: Record<string, unknown> } {
  const payload = eventPayload(event)
  return { payload, domain: recordValue(payload.repair) || payload }
}
