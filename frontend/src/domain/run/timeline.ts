import type { AgentRunEvent, ExecutionGate, GeneratedChartReference, HistoryIntegrity, RunSummary } from '../../types/protocol'
import { eventPayload } from '../records'
import { reviewGateFromPayload } from '../review'

export type RunTimeline = {
  summary: RunSummary
  events: AgentRunEvent[]
  historyGap: boolean
  integrity?: HistoryIntegrity
}

export type ToolStep = {
  id: string
  callId: string
  toolName: string
  toolLabel?: string
  call?: AgentRunEvent
  result?: AgentRunEvent
  resultTruncated?: boolean
  observations: Record<string, unknown>[]
  status: 'running' | 'success' | 'error'
}

export type TimelineRow = { kind: 'event'; event: AgentRunEvent } | { kind: 'tool'; step: ToolStep }

export function normalizeTimeline(events: AgentRunEvent[]): TimelineRow[] {
  const rows: TimelineRow[] = []
  const steps = new Map<string, ToolStep>()
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    const payload = eventPayload(event)
    if (event.kind === 'tool_call' || event.kind === 'tool_result') {
      const callId = typeof payload.call_id === 'string' && payload.call_id ? payload.call_id : ''
      if (!callId && event.kind === 'tool_result' && payload.truncated === true) {
        rows.push({ kind: 'event', event })
        continue
      }
      const stableCallId = callId || `sequence-${event.sequence}`
      let step = steps.get(stableCallId)
      if (!step) {
        step = { id: `${event.runId}-${stableCallId}`, callId: stableCallId, toolName: String(payload.tool_name || '未知工具'), toolLabel: typeof payload.tool_label === 'string' ? payload.tool_label : undefined, observations: [], status: 'running' }
        steps.set(stableCallId, step)
        rows.push({ kind: 'tool', step })
      }
      step.toolName = String(payload.tool_name || step.toolName)
      if (typeof payload.tool_label === 'string') step.toolLabel = payload.tool_label
      if (event.kind === 'tool_call') step.call = event
      else {
        step.result = event
        const result = payload.result
        step.resultTruncated = Boolean(
          payload.truncated === true
          || (result && typeof result === 'object' && (result as Record<string, unknown>).truncated === true),
        )
        step.status = payload.status === 'error' ? 'error' : 'success'
      }
      continue
    }
    if (event.kind === 'visual_observation') {
      const callId = typeof payload.call_id === 'string' ? payload.call_id : ''
      const observations = Array.isArray(payload.observations) ? payload.observations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : []
      const step = callId ? steps.get(callId) : undefined
      if (step) { step.observations.push(...observations); continue }
    }
    rows.push({ kind: 'event', event })
  }
  return rows
}

export function generatedArtifacts(events: AgentRunEvent[]): GeneratedChartReference[] {
  const references = events
    .filter((event) => event.kind === 'generated_chart')
    .flatMap((event) => {
      const artifacts = eventPayload(event).artifacts
      return Array.isArray(artifacts)
        ? artifacts.filter((item): item is GeneratedChartReference => Boolean(item && typeof item === 'object' && (item as Record<string, unknown>).artifactKind === 'generated_chart'))
        : []
    })
  const byCandidate = new Map<string, GeneratedChartReference>()
  references.forEach((reference) => {
    const key = reference.candidateId || reference.artifactId || `${reference.title || 'chart'}-${reference.chartSpecDigest || ''}`
    const current = byCandidate.get(key)
    if (!current || (!current.artifactId && reference.artifactId) || (current.status === 'pending' && reference.status !== 'pending')) byCandidate.set(key, reference)
  })
  return [...byCandidate.values()]
}

export function mergeEvents(current: AgentRunEvent[], incoming: AgentRunEvent[]): AgentRunEvent[] {
  const byCursor = new Map(current.map((event) => [`${event.runId}:${event.sequence}`, event]))
  incoming.forEach((event) => {
    const key = `${event.runId}:${event.sequence}`
    if (!byCursor.has(key)) byCursor.set(key, event)
  })
  return [...byCursor.values()].sort((left, right) => left.sequence - right.sequence)
}

export function latestExecutionGate(timeline: RunTimeline): Record<string, unknown> | null {
  for (const event of [...timeline.events].sort((left, right) => right.sequence - left.sequence)) {
    const gate = reviewGateFromPayload(eventPayload(event))
    if (gate) return gate
  }
  if (timeline.summary.executionGate) return timeline.summary.executionGate as unknown as Record<string, unknown>
  return null
}

export function executionGateValue(timeline: RunTimeline): ExecutionGate | null {
  const gate = latestExecutionGate(timeline)
  return gate ? gate as unknown as ExecutionGate : null
}
