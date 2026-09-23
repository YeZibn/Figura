import type { AgentRunEvent, ExecutionGate, FailureContext, GeneratedChartReference, HistoryIntegrity, RunSummary } from '../../types/protocol'
import { boundedDisplayText, eventPayload, failureContext } from '../records'
import { eventLabel } from '../display'

export type RunTimeline = {
  summary: RunSummary
  events: AgentRunEvent[]
  historyGap: boolean
  integrity?: HistoryIntegrity
}

export type TimelineNodeStatus = 'running' | 'completed' | 'reviewing' | 'passed' | 'published' | 'failed' | 'blocked' | 'partial' | 'abandoned' | 'unknown' | 'skipped' | 'unavailable'
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

export type TimelineProtocolStatus =
  | { status: 'supported' }
  | { status: 'unsupported_version' }
  | { status: 'malformed' }

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
const strictTimelineEvents = new Set([
  'review_started', 'review_completed', 'review_repair_required', 'review_failed', 'review_subcheck',
  'generated_chart_published', 'generated_chart_rejected', 'tool_call', 'tool_result', 'tool_skipped',
  'visual_observation', 'generated_chart', 'assembly_validation_failure',
])
const unknownStatusAllowedEvents = new Set(['tool_call', 'tool_result', 'tool_skipped', 'visual_observation', 'generated_chart'])
const reviewTimelineEvents = new Set(['review_started', 'review_completed', 'review_repair_required', 'review_failed', 'review_subcheck'])
const callTimelineEvents = new Set(['tool_call', 'tool_result', 'tool_skipped', 'visual_observation'])
const toolBackedTimelineEvents = new Set([...callTimelineEvents, 'generated_chart'])
const retiredTimelineEvents = new Set([
  'chart_review_started', 'chart_review_required', 'chart_review_repair_required', 'chart_review_completed',
  'review_gate_required', 'review_gate_updated',
])
const strictAliases = new Set([
  'correlationVersion', 'unitId', 'unitType', 'parentUnitId', 'transitionId', 'callId', 'reviewId',
  'reviewType', 'candidateId', 'subjectId', 'toolName', 'runId', 'processId', 'operationId', 'nextAction',
  'failureCategory', 'failureCode', 'safeMessage', 'fieldLocation', 'actionHint', 'firstFailureRef',
  'providerStatus', 'outcomeKnown', 'chartSpecDigest', 'sourceScope', 'sourceAttachmentIds', 'panelIds',
  'parentCandidateId', 'parentAttempt', 'collectionId', 'figureId', 'candidateStatus', 'reviewStatus',
  'publicationStatus', 'repairKind', 'repairPhase', 'maxAttempts', 'remainingAttempts', 'createdAt',
  'updatedAt', 'subjectRef', 'generationContext', 'contextStatus', 'traceSequence',
])
const hiddenEventKinds = new Set([
  'review_subcheck',
])
const terminalErrorEvents = new Set([
  'run_failed',
  'recovery_blocked',
  'budget_exhausted',
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

function nonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

export function timelineProtocolStatus(events: AgentRunEvent[]): TimelineProtocolStatus {
  for (const event of events) {
    if (retiredTimelineEvents.has(event.kind)) return { status: 'unsupported_version' }
    if (!strictTimelineEvents.has(event.kind)) continue
    const payload = eventPayload(event)
    if (payload.correlation_version !== 2) return { status: 'unsupported_version' }
    if ([...strictAliases].some((key) => Object.prototype.hasOwnProperty.call(payload, key))) return { status: 'malformed' }
    if (['execution_gate', 'executionGate', 'gate'].some((key) => Object.prototype.hasOwnProperty.call(payload, key))) return { status: 'malformed' }
    const stateField = event.kind === 'tool_result' ? 'status' : 'state'
    const aliasField = stateField === 'status' ? 'state' : 'status'
    if ((!nonEmptyString(payload[stateField]) && !unknownStatusAllowedEvents.has(event.kind)) || Object.prototype.hasOwnProperty.call(payload, aliasField)) return { status: 'malformed' }
    if (event.kind === 'tool_result' && Object.prototype.hasOwnProperty.call(payload, 'tool_status')) return { status: 'malformed' }
    if (!nonEmptyString(payload.unit_id) || !nonEmptyString(payload.transition_id)) return { status: 'malformed' }
    if (!['measurement', 'generation', 'review', 'publication', 'observation'].includes(String(payload.unit_type))) return { status: 'malformed' }
    if (!['observe', 'decide', 'assemble', 'render', 'review', 'repair', 'publish', 'action'].includes(String(payload.phase))) return { status: 'malformed' }
    if (!['agent', 'tool', 'system', 'vlm'].includes(String(payload.actor))) return { status: 'malformed' }
    if (!['observation', 'decision', 'action', 'gate', 'review', 'publication'].includes(String(payload.role))) return { status: 'malformed' }
    if (callTimelineEvents.has(event.kind) && !nonEmptyString(payload.call_id)) return { status: 'malformed' }
    if (reviewTimelineEvents.has(event.kind) && !nonEmptyString(payload.review_id)) return { status: 'malformed' }
    if (payload.parent_unit_id !== undefined && payload.parent_unit_id !== null && typeof payload.parent_unit_id !== 'string') return { status: 'malformed' }
    if (payload.parent_unit_id === payload.unit_id) return { status: 'malformed' }
  }
  return { status: 'supported' }
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
  if (typeof id !== 'string' || !id || typeof type !== 'string' || !(type in nodeLabels)) return undefined
  if (!['observe', 'decide', 'assemble', 'render', 'review', 'repair', 'publish', 'action'].includes(String(phase))) return undefined
  if (!['agent', 'tool', 'system', 'vlm'].includes(String(actor))) return undefined
  if (!['observation', 'decision', 'action', 'gate', 'review', 'publication'].includes(String(role))) return undefined
  if (typeof transition !== 'string' || !transition) return undefined
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

function stateValue(event: AgentRunEvent, payload: Record<string, unknown>): string {
  const statusField = event.kind === 'tool_result' ? 'status' : 'state'
  return typeof payload[statusField] === 'string' ? String(payload[statusField]).toLowerCase() : ''
}

function unitStatus(event: AgentRunEvent, payload: Record<string, unknown>, current: TimelineNodeStatus): TimelineNodeStatus {
  const state = stateValue(event, payload)
  if (event.kind === 'tool_call') return state === 'running' ? 'running' : 'unknown'
  if (event.kind === 'tool_result') {
    if (state === 'success') return 'completed'
    if (state === 'error') return 'failed'
    return 'unknown'
  }
  if (event.kind === 'tool_skipped') return state === 'not_started' ? 'skipped' : 'unknown'
  if (event.kind === 'review_started') return 'reviewing'
  if (event.kind === 'review_repair_required') return 'blocked'
  if (event.kind === 'review_completed') return state.includes('warning') ? 'passed' : state.includes('fail') ? 'failed' : 'passed'
  if (event.kind === 'review_failed' || event.kind === 'generated_chart_rejected' || event.kind === 'assembly_validation_failure') return 'failed'
  if (event.kind === 'generated_chart_published') return 'published'
  if (event.kind === 'generated_chart') {
    if (state === 'available') return 'completed'
    if (state === 'unavailable') return 'unavailable'
    return 'unknown'
  }
  if (event.kind === 'visual_observation') return state === 'observed' ? 'completed' : 'unknown'
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
  const state = stateValue(event, payload)
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
  const context = failureContext(eventPayload(event), event.kind)
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
  const payloads = events.map(eventPayload)
  for (const field of ['tool_label', 'tool_display_name', 'tool_name']) {
    for (const payload of payloads) {
      const label = boundedDisplayText(payload[field])
      if (label) return label
    }
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
        label: toolBackedTimelineEvents.has(event.kind) ? toolLabel([event]) : nodeLabels[meta.type],
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
    node.label = node.events.some((event) => toolBackedTimelineEvents.has(event.kind))
      ? toolLabel(node.events)
      : nodeLabels[node.unitType!]
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
  if (timelineProtocolStatus(events).status !== 'supported') return []
  return buildProjection(events).roots
}

export function projectUserTimeline(events: AgentRunEvent[]): UserTimelineItem[] {
  if (timelineProtocolStatus(events).status !== 'supported') return []
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

export function executionGateValue(timeline: RunTimeline): ExecutionGate | null {
  return timeline.summary.executionGate || null
}
