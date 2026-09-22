import type { AgentRunEvent, ExecutionGate, FailureContext, GeneratedChartReference, HistoryIntegrity, RunSummary } from '../../types/protocol'
import { eventPayload, failureContext } from '../records'
import { eventLabel } from '../display'
import { reviewGateFromPayload } from '../review'

export type RunTimeline = {
  summary: RunSummary
  events: AgentRunEvent[]
  historyGap: boolean
  integrity?: HistoryIntegrity
}

export type TimelineNodeStatus = 'running' | 'completed' | 'reviewing' | 'passed' | 'published' | 'failed' | 'blocked' | 'partial' | 'abandoned'
export type TimelineNodeType = 'measurement' | 'generation' | 'review' | 'publication' | 'observation'
export type DecisionPhase = 'observe' | 'decide' | 'assemble' | 'render' | 'review' | 'repair' | 'publish' | 'action'
export type DecisionRole = 'observation' | 'decision' | 'action' | 'gate' | 'review' | 'publication'
export type UserTimelineItemType = TimelineNodeType | 'error'

export type DecisionAction = {
  required: boolean
  allowed: string[]
  blocked: string[]
  reason?: string
  label?: string
}

export type TimelineNode = {
  id: string
  itemType: UserTimelineItemType
  unitType?: TimelineNodeType
  phase?: DecisionPhase
  actor?: string
  role?: DecisionRole
  status: TimelineNodeStatus
  label: string
  firstSequence: number
  lastSequence: number
  parentUnitId?: string
  sourceUnitId?: string
  event?: AgentRunEvent
  events: AgentRunEvent[]
  visibleEvents: AgentRunEvent[]
  call?: AgentRunEvent
  result?: AgentRunEvent
  resultTruncated?: boolean
  observations: Record<string, unknown>[]
  children: TimelineNode[]
  nextAction?: DecisionAction
  failure?: FailureContext
}

export type UserTimelineItem = TimelineNode

export const technicalTimelineEventKinds = [
  'run_started',
  'resume_started',
  'model_started',
  'model_completed',
  'operation_completed',
  'final_answer',
] as const

const technicalTimelineEvents = new Set<string>(technicalTimelineEventKinds)
const toolTimelineEvents = new Set(['tool_call', 'tool_result', 'tool_skipped', 'visual_observation'])
const hiddenEventKinds = new Set([
  'measurement_observed',
  'measurement_repair_required',
  'measurement_decision_required',
  'measurement_focus_requested',
  'measurement_focus_applied',
  'measurement_evidence_selected',
  'measurement_evidence_discarded',
  'measurement_evidence_used',
  'review_gate_required',
  'review_gate_updated',
  'review_subcheck',
])
const terminalErrorEvents = new Set([
  'run_failed',
  'recovery_blocked',
  'budget_exhausted',
  'measurement_focus_failed',
  'measurement_repair_rejected',
  'measurement_repair_exhausted',
  'review_failed',
  'generated_chart_rejected',
  'assembly_validation_failure',
])

const nodeLabels: Record<TimelineNodeType, string> = {
  measurement: '测量结果',
  generation: '图表生成',
  review: '审核',
  publication: '生成结果',
  observation: '工具观察',
}

function actionValue(value: unknown): DecisionAction | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  const list = (item: unknown): string[] => Array.isArray(item) ? item.map(String).slice(0, 16) : []
  const reason = typeof record.reason === 'string' ? record.reason : undefined
  const label = typeof record.label === 'string' ? record.label : undefined
  return { required: record.required === true, allowed: list(record.allowed), blocked: list(record.blocked), ...(reason ? { reason } : {}), ...(label ? { label } : {}) }
}

function metadata(event: AgentRunEvent): { id: string; type: TimelineNodeType; phase: DecisionPhase; actor: string; role: DecisionRole; parent?: string } | undefined {
  const payload = eventPayload(event)
  const id = payload.unit_id
  const type = payload.unit_type
  const phase = payload.phase
  const actor = payload.actor
  const role = payload.role
  const transition = payload.transition_id
  const state = payload.state ?? payload.status
  if (typeof id !== 'string' || !id || typeof type !== 'string' || !(type in nodeLabels)) return undefined
  if (!['observe', 'decide', 'assemble', 'render', 'review', 'repair', 'publish', 'action'].includes(String(phase))) return undefined
  if (!['agent', 'tool', 'system', 'vlm'].includes(String(actor))) return undefined
  if (!['observation', 'decision', 'action', 'gate', 'review', 'publication'].includes(String(role))) return undefined
  if (typeof transition !== 'string' || !transition || typeof state !== 'string' || !state) return undefined
  const parent = payload.parent_unit_id
  return {
    id,
    type: type as TimelineNodeType,
    phase: phase as DecisionPhase,
    actor: String(actor),
    role: role as DecisionRole,
    ...(typeof parent === 'string' && parent ? { parent } : {}),
  }
}

function stateValue(payload: Record<string, unknown>): string {
  return String(payload.state || payload.status || payload.publication_status || payload.review_status || '').toLowerCase()
}

function unitStatus(event: AgentRunEvent, payload: Record<string, unknown>, current: TimelineNodeStatus): TimelineNodeStatus {
  const state = stateValue(payload)
  if (event.kind === 'tool_call') return 'running'
  if (event.kind === 'tool_result') {
    if (state === 'error' || state.includes('fail') || state.includes('reject')) return 'failed'
    if (state === 'not_started') return 'blocked'
    return 'completed'
  }
  if (event.kind === 'tool_skipped') return 'blocked'
  if (event.kind === 'review_started') return 'reviewing'
  if (event.kind === 'review_repair_required') return 'blocked'
  if (event.kind === 'review_completed') return state.includes('warning') ? 'passed' : state.includes('fail') ? 'failed' : 'passed'
  if (event.kind === 'review_failed' || event.kind === 'generated_chart_rejected' || event.kind === 'measurement_focus_failed' || event.kind === 'measurement_repair_rejected' || event.kind === 'measurement_repair_exhausted' || event.kind === 'assembly_validation_failure') return 'failed'
  if (event.kind === 'generated_chart_published') return 'published'
  if (event.kind === 'measurement_repair_required' || event.kind === 'measurement_decision_required' || event.kind === 'measurement_focus_requested') return 'running'
  if (event.kind === 'measurement_observed' || event.kind === 'measurement_focus_applied' || event.kind === 'measurement_evidence_selected' || event.kind === 'measurement_evidence_discarded' || event.kind === 'measurement_evidence_used' || event.kind === 'generated_chart' || event.kind === 'visual_observation') return 'completed'
  if (state === 'abandoned' || event.kind === 'run_interrupted') return 'abandoned'
  if (state === 'partial') return 'partial'
  if (state === 'blocked') return 'blocked'
  return current
}

function isTechnicalTimelineEvent(eventOrKind: AgentRunEvent | string): boolean {
  const kind = typeof eventOrKind === 'string' ? eventOrKind : eventOrKind.kind
  return technicalTimelineEvents.has(kind)
}

export { isTechnicalTimelineEvent }

function userVisibleEvent(event: AgentRunEvent): boolean {
  if (isTechnicalTimelineEvent(event) || toolTimelineEvents.has(event.kind)) return false
  if (event.kind === 'progress' || event.kind === 'history_gap') return false
  return !hiddenEventKinds.has(event.kind)
}

function hasFailureSignal(event: AgentRunEvent): boolean {
  if (terminalErrorEvents.has(event.kind)) return true
  const payload = eventPayload(event)
  const state = stateValue(payload)
  return payload.failure_category !== undefined
    || payload.failure_code !== undefined
    || payload.error !== undefined
    || Array.isArray(payload.issues) && payload.issues.length > 0
    || state === 'error'
    || state.includes('fail')
    || state.includes('reject')
    || payload.outcome_known === false
}

function failureForEvent(event: AgentRunEvent): FailureContext | undefined {
  if (!hasFailureSignal(event)) return undefined
  const context = failureContext(eventPayload(event))
  if (context) return context
  const payload = eventPayload(event)
  const message = payload.safe_message || payload.message || payload.reason
  const category = event.kind === 'assembly_validation_failure'
    ? 'assembly_validation'
    : event.kind === 'recovery_blocked'
      ? 'recovery_blocked'
      : undefined
  return { ...(category ? { category } : {}), ...(message ? { safeMessage: String(message) } : {}) }
}

function dedupeEvents(events: AgentRunEvent[]): AgentRunEvent[] {
  const seen = new Set<string>()
  const result: AgentRunEvent[] = []
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    const transition = eventPayload(event).transition_id
    const key = typeof transition === 'string' && transition ? `transition:${transition}` : `event:${event.runId}:${event.sequence}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push(event)
  }
  return result
}

function reviewVisibleEvents(events: AgentRunEvent[]): AgentRunEvent[] {
  const visible = dedupeEvents(events.filter(userVisibleEvent))
  if (visible.length <= 2) return visible
  return [visible[0], visible[visible.length - 1]]
}

function toolLabel(events: AgentRunEvent[]): string {
  for (const event of events) {
    const payload = eventPayload(event)
    if (typeof payload.tool_label === 'string' && payload.tool_label) return payload.tool_label
    if (typeof payload.tool_display_name === 'string' && payload.tool_display_name) return payload.tool_display_name
  }
  return '工具执行'
}

function standaloneError(event: AgentRunEvent): TimelineNode {
  const failure = failureForEvent(event)
  return {
    id: `event:${event.runId}:${event.sequence}`,
    itemType: 'error',
    status: event.kind === 'run_interrupted' ? 'abandoned' : 'failed',
    label: eventLabel(event),
    firstSequence: event.sequence,
    lastSequence: event.sequence,
    event,
    events: [event],
    visibleEvents: [event],
    observations: [],
    children: [],
    ...(failure ? { failure } : {}),
  }
}

function buildProjection(events: AgentRunEvent[]): { roots: TimelineNode[]; nodes: TimelineNode[]; errors: TimelineNode[] } {
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence)
  const unique = new Map<string, AgentRunEvent>()
  ordered.forEach((event) => unique.set(`${event.runId}:${event.sequence}`, event))
  const nodes = new Map<string, TimelineNode>()
  const errors: TimelineNode[] = []

  for (const event of unique.values()) {
    const meta = metadata(event)
    if (!meta) {
      if (terminalErrorEvents.has(event.kind) || event.kind === 'run_interrupted') errors.push(standaloneError(event))
      continue
    }
    const payload = eventPayload(event)
    let node = nodes.get(meta.id)
    if (!node) {
      node = {
        id: meta.id,
        itemType: meta.type,
        unitType: meta.type,
        phase: meta.phase,
        actor: meta.actor,
        role: meta.role,
        status: 'running',
        label: meta.type === 'observation' ? toolLabel([event]) : nodeLabels[meta.type],
        firstSequence: event.sequence,
        lastSequence: event.sequence,
        ...(meta.parent ? { parentUnitId: meta.parent } : {}),
        sourceUnitId: meta.id,
        events: [],
        visibleEvents: [],
        observations: [],
        children: [],
      }
      nodes.set(meta.id, node)
    }
    node.events.push(event)
    node.firstSequence = Math.min(node.firstSequence, event.sequence)
    node.lastSequence = Math.max(node.lastSequence, event.sequence)
    node.phase = meta.phase
    node.actor = meta.actor
    node.role = meta.role
    if (meta.parent) node.parentUnitId = meta.parent
    node.status = unitStatus(event, payload, node.status)
    const action = actionValue(payload.next_action)
    if (action) node.nextAction = action
    if (event.kind === 'tool_call') node.call = event
    if (event.kind === 'tool_result') {
      node.result = event
      const result = payload.result
      node.resultTruncated = Boolean(payload.truncated === true || result && typeof result === 'object' && (result as Record<string, unknown>).truncated === true)
    }
    if (event.kind === 'visual_observation') {
      const observations = Array.isArray(payload.observations)
        ? payload.observations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
        : []
      node.observations.push(...observations)
    }
  }

  const allNodes = [...nodes.values()]
  for (const node of allNodes) {
    node.label = node.unitType === 'observation' ? toolLabel(node.events) : nodeLabels[node.unitType!]
    node.visibleEvents = node.unitType === 'review' ? reviewVisibleEvents(node.events) : dedupeEvents(node.events.filter(userVisibleEvent))
    node.event = node.visibleEvents[node.visibleEvents.length - 1] || node.result || node.call || node.events[node.events.length - 1]
    node.failure = node.events.map(failureForEvent).find((value): value is FailureContext => Boolean(value))
  }

  const roots: TimelineNode[] = []
  for (const node of allNodes) {
    if (node.parentUnitId && nodes.has(node.parentUnitId)) nodes.get(node.parentUnitId)!.children.push(node)
    else roots.push(node)
  }
  for (const node of allNodes) node.children.sort((left, right) => left.firstSequence - right.firstSequence)
  roots.push(...errors)
  roots.sort((left, right) => left.firstSequence - right.firstSequence)
  return { roots, nodes: allNodes, errors }
}

function flatten(nodes: TimelineNode[]): TimelineNode[] {
  const result: TimelineNode[] = []
  const visit = (node: TimelineNode) => {
    result.push(node)
    node.children.forEach(visit)
  }
  nodes.forEach(visit)
  return result
}

export function projectDecisionTimeline(events: AgentRunEvent[]): TimelineNode[] {
  return buildProjection(events).roots
}

export function projectUserTimeline(events: AgentRunEvent[]): UserTimelineItem[] {
  return flatten(buildProjection(events).roots).sort((left, right) => left.firstSequence - right.firstSequence)
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
