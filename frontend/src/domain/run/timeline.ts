import type { AgentRunEvent, ExecutionGate, FailureContext, GeneratedChartReference, HistoryIntegrity, RunSummary } from '../../types/protocol'
import { eventPayload, failureContext } from '../records'
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

export type UserTimelineItemType = 'tool' | 'measurement' | 'generation' | 'review' | 'publication' | 'observation' | 'error' | 'status'

export type UserTimelineItem = {
  id: string
  itemType: UserTimelineItemType
  label: string
  status: DecisionUnitStatus | ToolStep['status']
  firstSequence: number
  lastSequence: number
  phase?: DecisionPhase
  sourceUnitId?: string
  event?: AgentRunEvent
  events: AgentRunEvent[]
  visibleEvents: AgentRunEvent[]
  toolStep?: ToolStep
  nextAction?: DecisionAction
  failure?: FailureContext
}

export const technicalTimelineEventKinds = [
  'run_started',
  'resume_started',
  'model_started',
  'model_completed',
  'operation_completed',
  'final_answer',
] as const

const technicalTimelineEvents = new Set<string>(technicalTimelineEventKinds)
const toolTimelineEvents = new Set(['tool_call', 'tool_result', 'visual_observation'])
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

// These events remain part of the persisted trace and evaluation detail, but
// they are implementation facts rather than user-facing business steps.
// Keeping this projection here means ordinary runs and read-only evaluations
// cannot drift into two different stories about the same execution.
const defaultHiddenEventKinds = new Set([
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
  'chart_review_required',
  'chart_review_repair_required',
  'review_subcheck',
  'generated_chart_published',
])

const userEventLabels: Record<string, string> = {
  model_completed: '模型调用失败',
  operation_completed: '操作执行失败',
  recovery_blocked: '继续执行被阻止',
  run_failed: '运行失败',
  run_interrupted: '运行已中断',
  budget_exhausted: '达到预算上限',
  generated_chart: '图表状态已更新',
  generated_chart_published: '图表已发布',
  generated_chart_rejected: '图表未发布',
  assembly_validation_failure: '图表组装校验失败',
  measurement_focus_failed: '局部测量未获得足够证据',
  measurement_repair_rejected: '定向补充被拒绝',
  measurement_repair_exhausted: '定向补充次数已用尽',
  tool_skipped: '工具未执行',
}

export type DecisionUnitStatus = 'unknown' | 'pending' | 'completed' | 'failed' | 'partial' | 'blocked' | 'abandoned'
export type DecisionUnitType = 'measurement' | 'generation' | 'review' | 'publication' | 'observation' | 'process' | 'legacy' | 'unknown'
export type DecisionPhase = 'observe' | 'decide' | 'assemble' | 'render' | 'review' | 'repair' | 'publish' | 'action' | 'unknown'
export type DecisionRole = 'observation' | 'decision' | 'action' | 'gate' | 'review' | 'publication' | 'legacy'

export type DecisionAction = {
  required: boolean
  allowed: string[]
  blocked: string[]
  reason?: string
  label?: string
}

export type DecisionSubcheck = {
  id: string
  checkType: string
  status: string
  event: AgentRunEvent
}

export type DecisionUnit = {
  id: string
  unitType: DecisionUnitType
  phase: DecisionPhase
  actor: string
  role: DecisionRole
  status: DecisionUnitStatus
  label: string
  firstSequence: number
  lastSequence: number
  parentUnitId?: string
  nextAction?: DecisionAction
  events: AgentRunEvent[]
  transitions: AgentRunEvent[]
  children: DecisionUnit[]
  toolSteps: ToolStep[]
  subchecks: DecisionSubcheck[]
  virtual?: boolean
  legacy?: boolean
  detailUnavailable?: boolean
}

const decisionUnitLabels: Record<string, string> = {
  measurement: '测量结果',
  generation: '图表生成',
  review: '审核周期',
  publication: '发布状态',
  observation: '工具观察',
  process: '运行过程',
  legacy: '历史事件（兼容模式）',
  unknown: '未分类记录',
}

function correlationValue(payload: Record<string, unknown>, snake: string, camel: string): unknown {
  return payload[snake] ?? payload[camel]
}

function actionValue(value: unknown): DecisionAction | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  const list = (item: unknown): string[] => Array.isArray(item) ? item.map(String).slice(0, 16) : []
  const reason = typeof record.reason === 'string' ? record.reason : undefined
  const label = typeof record.label === 'string' ? record.label : undefined
  return { required: record.required === true, allowed: list(record.allowed), blocked: list(record.blocked), ...(reason ? { reason } : {}), ...(label ? { label } : {}) }
}

function compatibilityBucket(event: AgentRunEvent, payload: Record<string, unknown>): string {
  const processId = correlationValue(payload, 'process_id', 'processId')
  if (typeof processId === 'string' && processId) return `process:${processId}`
  const operationId = correlationValue(payload, 'operation_id', 'operationId')
  if (typeof operationId === 'string' && operationId) return `operation:${operationId}`
  const turn = correlationValue(payload, 'turn', 'turn')
  if ((event.kind === 'model_started' || event.kind === 'model_completed') && turn !== undefined && turn !== null) return `turn:${String(turn)}`
  if (event.kind === 'model_started' || event.kind === 'model_completed') return 'model'
  if (event.kind === 'run_started' || event.kind === 'run_failed' || event.kind === 'run_interrupted' || event.kind === 'final_answer' || event.kind === 'recovery_blocked' || event.kind === 'budget_exhausted') return 'run'
  if (event.kind === 'operation_completed') return 'operation'
  return 'other'
}

function legacyUnitId(event: AgentRunEvent, payload: Record<string, unknown>): string {
  return `legacy:${event.runId}:${compatibilityBucket(event, payload)}`
}

function processUnitId(event: AgentRunEvent, payload: Record<string, unknown>): string | undefined {
  const processId = correlationValue(payload, 'process_id', 'processId')
  if (typeof processId === 'string' && processId) return `process:${event.runId}:${processId}`
  const operationId = correlationValue(payload, 'operation_id', 'operationId')
  if (typeof operationId === 'string' && operationId) return `process:${event.runId}:operation:${operationId}`
  const turn = correlationValue(payload, 'turn', 'turn')
  if ((event.kind === 'model_started' || event.kind === 'model_completed') && turn !== undefined && turn !== null) return `process:${event.runId}:turn:${String(turn)}`
  return undefined
}

function unitStatus(event: AgentRunEvent, payload: Record<string, unknown>, current: DecisionUnitStatus): DecisionUnitStatus {
  const action = actionValue(correlationValue(payload, 'next_action', 'nextAction'))
  if (event.kind === 'measurement_focus_failed' || event.kind === 'measurement_repair_rejected' || event.kind === 'measurement_repair_exhausted' || event.kind === 'review_failed' || event.kind === 'generated_chart_rejected' || event.kind === 'run_failed') return 'failed'
  // A legacy envelope may synthesize `next_action.required` for an old
  // measurement event. That is diagnostic compatibility data, not an open
  // user decision. Only review/generation gates can make a visible unit wait.
  if (action?.required && !event.kind.startsWith('measurement_')) return 'pending'
  if (event.kind === 'review_started' || event.kind === 'chart_review_started' || event.kind === 'review_subcheck' && payload.status === 'running') return 'pending'
  if (event.kind === 'generated_chart_published' || event.kind === 'review_completed' || event.kind === 'chart_review_completed') {
    const state = String(payload.state || payload.publication_status || payload.publicationStatus || '')
    return state.includes('warning') ? 'completed' : state.includes('fail') || state.includes('reject') ? 'failed' : 'completed'
  }
  if (event.kind === 'measurement_evidence_selected' || event.kind === 'measurement_evidence_discarded') return 'completed'
  if (event.kind === 'measurement_observed') return String(payload.decision_status || payload.decisionStatus || '') === 'pending' ? 'pending' : 'completed'
  if (event.kind === 'model_started') return 'pending'
  if (event.kind === 'model_completed' || event.kind === 'operation_completed') {
    const failureCategory = String(payload.failure_category || payload.failureCategory || '').toLowerCase()
    const explicit = String(payload.status || payload.state || '').toLowerCase()
    if (failureCategory || explicit === 'error' || explicit.includes('fail') || explicit.includes('uncertain') || payload.outcome_known === false || payload.outcomeKnown === false) return 'failed'
    return explicit === 'ok' || explicit === 'success' || explicit === 'completed' ? 'completed' : current === 'pending' ? 'completed' : current
  }
  if (event.kind === 'final_answer') return 'completed'
  if (event.kind === 'review_repair_required' || event.kind === 'chart_review_repair_required') return 'blocked'
  if (current !== 'failed' && current !== 'blocked') {
    const explicit = String(payload.state || payload.status || '')
    if (explicit === 'abandoned') return 'abandoned'
    if (explicit === 'partial') return 'partial'
  }
  return current === 'unknown' ? 'unknown' : current
}

function unitType(value: unknown): DecisionUnitType {
  const text = String(value || 'unknown')
  return ['measurement', 'generation', 'review', 'publication', 'observation', 'process', 'legacy', 'unknown'].includes(text) ? text as DecisionUnitType : 'unknown'
}

function phaseValue(value: unknown): DecisionPhase {
  const text = String(value || 'unknown')
  return ['observe', 'decide', 'assemble', 'render', 'review', 'repair', 'publish', 'action', 'unknown'].includes(text) ? text as DecisionPhase : 'unknown'
}

function roleValue(value: unknown): DecisionRole {
  const text = String(value || 'legacy')
  return ['observation', 'decision', 'action', 'gate', 'review', 'publication', 'legacy'].includes(text) ? text as DecisionRole : 'legacy'
}

export function isTechnicalTimelineEvent(eventOrKind: AgentRunEvent | string): boolean {
  const kind = typeof eventOrKind === 'string' ? eventOrKind : eventOrKind.kind
  return technicalTimelineEvents.has(kind)
}

function userEventLabel(event: AgentRunEvent): string {
  return userEventLabels[event.kind] || event.kind
}

function hasFailureSignal(event: AgentRunEvent): boolean {
  if (terminalErrorEvents.has(event.kind)) return true
  const payload = eventPayload(event)
  const state = String(payload.status || payload.state || payload.outcome || '').toLowerCase()
  return payload.failure_category !== undefined
    || payload.failureCategory !== undefined
    || payload.failure_code !== undefined
    || payload.failureCode !== undefined
    || payload.error !== undefined
    || Array.isArray(payload.issues) && payload.issues.length > 0
    || state === 'error'
    || state.includes('fail')
    || state.includes('reject')
    || state.includes('uncertain')
    || payload.outcome_known === false
    || payload.outcomeKnown === false
}

function failureForEvent(event: AgentRunEvent): FailureContext | undefined {
  if (!hasFailureSignal(event)) return undefined
  const context = failureContext(eventPayload(event))
  if (context) return context
  const payload = eventPayload(event)
  const message = payload.safe_message || payload.safeMessage || payload.message || payload.reason
  const category = event.kind === 'assembly_validation_failure'
    ? 'assembly_validation'
    : event.kind === 'recovery_blocked'
      ? 'recovery_blocked'
      : undefined
  return {
    ...(category ? { category } : {}),
    ...(message ? { safeMessage: String(message) } : {}),
  }
}

function eventType(event: AgentRunEvent): UserTimelineItemType {
  if (terminalErrorEvents.has(event.kind) || failureForEvent(event)) return 'error'
  if (event.kind.startsWith('measurement_')) return 'measurement'
  if (event.kind.startsWith('review_') || event.kind.startsWith('chart_review_')) return 'review'
  if (event.kind === 'generated_chart_published') return 'publication'
  if (event.kind === 'generated_chart') return 'generation'
  if (event.kind === 'visual_observation') return 'observation'
  return 'status'
}

function domainType(type: DecisionUnitType): UserTimelineItemType | undefined {
  // Publication transitions are represented by the generated artifact and
  // the canonical review result, not as a second timeline card.
  if (type === 'measurement' || type === 'generation' || type === 'review' || type === 'observation') return type
  return undefined
}

function userVisibleEvent(event: AgentRunEvent): boolean {
  if (isTechnicalTimelineEvent(event) || toolTimelineEvents.has(event.kind)) return false
  if (event.kind === 'progress' || event.kind === 'history_gap') return false
  if (defaultHiddenEventKinds.has(event.kind)) return false
  return true
}

function dedupeEvents(events: AgentRunEvent[]): AgentRunEvent[] {
  const seen = new Set<string>()
  const result: AgentRunEvent[] = []
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    const payload = eventPayload(event)
    const transition = correlationValue(payload, 'transition_id', 'transitionId')
    const key = typeof transition === 'string' && transition
      ? `transition:${transition}`
      : `event:${event.runId}:${event.sequence}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push(event)
  }
  return result
}

function allDecisionUnits(units: DecisionUnit[]): DecisionUnit[] {
  const seen = new Set<string>()
  const result: DecisionUnit[] = []
  const visit = (unit: DecisionUnit) => {
    if (seen.has(unit.id)) return
    seen.add(unit.id)
    result.push(unit)
    unit.children.forEach(visit)
  }
  units.forEach(visit)
  return result
}

function eventItem(event: AgentRunEvent, sourceUnitId?: string): UserTimelineItem {
  const failure = failureForEvent(event)
  const itemType = eventType(event)
  const status: DecisionUnitStatus = itemType === 'error' ? 'failed' : event.kind === 'run_interrupted' ? 'abandoned' : 'completed'
  return {
    id: `event:${event.runId}:${event.sequence}`,
    itemType,
    label: userEventLabel(event),
    status,
    firstSequence: event.sequence,
    lastSequence: event.sequence,
    ...(sourceUnitId ? { sourceUnitId } : {}),
    event,
    events: [event],
    visibleEvents: userVisibleEvent(event) ? [event] : [],
    ...(failure ? { failure } : {}),
  }
}

function reviewEventRows(events: AgentRunEvent[]): AgentRunEvent[] {
  const visible = dedupeEvents(events)
  if (visible.length <= 2) return visible
  const start = visible.find((event) => event.kind === 'review_started' || event.kind === 'chart_review_started') || visible[0]
  const final = visible[visible.length - 1]
  return start.sequence === final.sequence ? [start] : [start, final]
}

function toolItem(step: ToolStep): UserTimelineItem {
  const firstSequence = step.call?.sequence ?? step.result?.sequence ?? Number.MAX_SAFE_INTEGER
  const lastSequence = step.result?.sequence ?? step.call?.sequence ?? firstSequence
  return {
    id: `tool:${step.id}`,
    itemType: 'tool',
    label: step.toolLabel || step.toolName,
    status: step.status,
    firstSequence,
    lastSequence,
    events: [step.call, step.result].filter((event): event is AgentRunEvent => Boolean(event)),
    visibleEvents: [],
    toolStep: step,
  }
}

export function projectUserTimeline(events: AgentRunEvent[]): UserTimelineItem[] {
  const units = allDecisionUnits(projectDecisionTimeline(events))
  const collectionParentIds = new Set(
    units.filter((unit) => unit.virtual && unit.unitType === 'review').map((unit) => unit.id),
  )
  const items: UserTimelineItem[] = []
  const toolIds = new Set<string>()

  for (const unit of units) {
    for (const step of unit.toolSteps) {
      if (toolIds.has(step.id)) continue
      toolIds.add(step.id)
      items.push(toolItem(step))
    }

    const collectionChildren = unit.virtual && unit.unitType === 'review' ? allDecisionUnits(unit.children) : []
    const rawEvents = dedupeEvents(
      unit.events.length > 0 ? unit.events : collectionChildren.flatMap((child) => child.events),
    )
    const visibleEvents = dedupeEvents(unit.transitions.filter(userVisibleEvent))
    const displayEvents = unit.unitType === 'review' ? reviewEventRows(visibleEvents) : visibleEvents
    const hiddenFailures = rawEvents.filter((event) => isTechnicalTimelineEvent(event) && failureForEvent(event))
    const failedChildren = collectionChildren.filter((child) => ['failed', 'blocked', 'partial'].includes(child.status))
    const domain = domainType(unit.unitType)

    if (domain) {
      // Collection review children remain available in the parent technical
      // details, but they do not become several top-level review cards.
      if (unit.parentUnitId && collectionParentIds.has(unit.parentUnitId)) continue
      const shouldRender = displayEvents.length > 0
        || (domain !== 'measurement' && (Boolean(unit.nextAction) || ['pending', 'blocked', 'failed', 'partial'].includes(unit.status)))
      if (shouldRender) {
        const representative = displayEvents[displayEvents.length - 1] || (unit.virtual ? undefined : rawEvents[rawEvents.length - 1])
        const firstSequence = displayEvents[0]?.sequence ?? representative?.sequence ?? unit.firstSequence
        const lastSequence = displayEvents[displayEvents.length - 1]?.sequence ?? representative?.sequence ?? unit.lastSequence
        const failure = displayEvents.map(failureForEvent).find((value): value is FailureContext => Boolean(value))
          || hiddenFailures.map(failureForEvent).find((value): value is FailureContext => Boolean(value))
          || (failedChildren.length > 0 ? { safeMessage: `集合审核中有 ${failedChildren.length} 个候选未通过` } : undefined)
        items.push({
          id: `unit:${unit.id}`,
          itemType: domain,
          label: unit.label,
          status: unit.status,
          firstSequence,
          lastSequence,
          phase: unit.phase,
          sourceUnitId: unit.id,
          event: representative,
          events: rawEvents,
          visibleEvents: displayEvents,
          nextAction: unit.nextAction,
          ...(failure ? { failure } : {}),
        })
      }
      continue
    }

    const visibleNonDomainEvents = visibleEvents
    visibleNonDomainEvents.forEach((event) => items.push(eventItem(event, unit.id)))
    if (visibleNonDomainEvents.length === 0) {
      hiddenFailures.forEach((event) => items.push(eventItem(event, unit.id)))
    }
  }

  const deduped = new Map<string, UserTimelineItem>()
  for (const item of items) {
    if (item.itemType !== 'error' || !item.failure) {
      deduped.set(`${item.id}:${item.firstSequence}`, item)
      continue
    }
    const failureKey = [item.failure.category, item.failure.safeMessage || item.failure.code, item.failure.location].filter(Boolean).join('|') || item.id
    const current = deduped.get(`failure:${failureKey}`)
    if (!current || (current.event && isTechnicalTimelineEvent(current.event) && item.event && !isTechnicalTimelineEvent(item.event))) deduped.set(`failure:${failureKey}`, item)
  }

  return [...deduped.values()].sort((left, right) => {
    if (left.firstSequence !== right.firstSequence) return left.firstSequence - right.firstSequence
    if (left.itemType === 'tool' && right.itemType !== 'tool') return -1
    if (left.itemType !== 'tool' && right.itemType === 'tool') return 1
    return left.id.localeCompare(right.id)
  })
}

function buildUnitToolSteps(events: AgentRunEvent[]): ToolStep[] {
  const rows = normalizeTimeline(events)
  return rows.filter((row): row is { kind: 'tool'; step: ToolStep } => row.kind === 'tool').map((row) => row.step)
}

function unitEventMetadata(event: AgentRunEvent): { id: string; type: DecisionUnitType; phase: DecisionPhase; actor: string; role: DecisionRole; parent?: string; legacy: boolean } {
  const payload = eventPayload(event)
  const rawId = correlationValue(payload, 'unit_id', 'unitId')
  const processId = processUnitId(event, payload)
  const hasExplicitUnit = typeof rawId === 'string' && Boolean(rawId)
  const compatibilityId = processId || legacyUnitId(event, payload)
  const legacy = !hasExplicitUnit && !processId
  return {
    id: hasExplicitUnit ? String(rawId) : compatibilityId,
    type: hasExplicitUnit ? unitType(correlationValue(payload, 'unit_type', 'unitType')) : processId ? 'process' : 'legacy',
    phase: hasExplicitUnit ? phaseValue(payload.phase) : processId ? 'action' : 'unknown',
    actor: hasExplicitUnit ? String(payload.actor || 'unknown') : processId ? String(payload.actor || 'system') : 'unknown',
    role: hasExplicitUnit ? roleValue(payload.role) : processId ? 'action' : 'legacy',
    parent: hasExplicitUnit ? (typeof correlationValue(payload, 'parent_unit_id', 'parentUnitId') === 'string' ? String(correlationValue(payload, 'parent_unit_id', 'parentUnitId')) : undefined) : undefined,
    legacy,
  }
}

export function projectDecisionTimeline(events: AgentRunEvent[]): DecisionUnit[] {
  const sorted = [...events].sort((left, right) => left.sequence - right.sequence)
  const unique = new Map<string, AgentRunEvent>()
  sorted.forEach((event) => unique.set(`${event.runId}:${event.sequence}`, event))
  const toolResultUnits = new Map<string, { id: string; type: DecisionUnitType; phase: DecisionPhase; actor: string; role: DecisionRole; parent?: string }>()
  for (const event of unique.values()) {
    if (event.kind !== 'tool_result') continue
    const payload = eventPayload(event)
    const callId = payload.call_id || payload.callId
    if (typeof callId !== 'string' || !callId) continue
    const metadata = unitEventMetadata(event)
    if (!metadata.legacy) toolResultUnits.set(callId, metadata)
  }
  const units = new Map<string, DecisionUnit>()
  const transitionIndexes = new Map<string, Set<string>>()
  const checkIndexes = new Map<string, Set<string>>()
  for (const event of unique.values()) {
    const payload = eventPayload(event)
    let metadata = unitEventMetadata(event)
    const callId = payload.call_id || payload.callId
    if ((event.kind === 'tool_call' || event.kind === 'visual_observation') && typeof callId === 'string') {
      const resultMetadata = toolResultUnits.get(callId)
      if (resultMetadata) metadata = { ...resultMetadata, legacy: false }
    }
    let unit = units.get(metadata.id)
    if (!unit) {
      unit = {
        id: metadata.id,
        unitType: metadata.type,
        phase: metadata.phase,
        actor: metadata.actor,
        role: metadata.role,
        status: 'unknown',
        label: decisionUnitLabels[metadata.type],
        firstSequence: event.sequence,
        lastSequence: event.sequence,
        ...(metadata.parent ? { parentUnitId: metadata.parent } : {}),
        events: [],
        transitions: [],
        children: [],
        toolSteps: [],
        subchecks: [],
        ...(metadata.legacy ? { virtual: false, legacy: true } : {}),
      }
      units.set(metadata.id, unit)
      transitionIndexes.set(metadata.id, new Set())
      checkIndexes.set(metadata.id, new Set())
    }
    unit.events.push(event)
    unit.firstSequence = Math.min(unit.firstSequence, event.sequence)
    unit.lastSequence = Math.max(unit.lastSequence, event.sequence)
    if (metadata.parent && !unit.parentUnitId) unit.parentUnitId = metadata.parent
    if (!unit.legacy) {
      unit.phase = metadata.phase !== 'unknown' ? metadata.phase : unit.phase
      unit.actor = metadata.actor !== 'unknown' ? metadata.actor : unit.actor
      unit.role = metadata.role !== 'legacy' ? metadata.role : unit.role
      const action = actionValue(correlationValue(payload, 'next_action', 'nextAction'))
      if (action) unit.nextAction = action
    }
    unit.status = unitStatus(event, payload, unit.status)
    const transition = correlationValue(payload, 'transition_id', 'transitionId')
    const transitionKey = typeof transition === 'string' && transition ? transition : `event:${event.sequence}`
    const transitionSet = transitionIndexes.get(unit.id)!
    if (!transitionSet.has(transitionKey)) {
      transitionSet.add(transitionKey)
      unit.transitions.push(event)
    }
    if (event.kind === 'review_subcheck') {
      const checkType = String(payload.check_type || payload.checkType || 'unknown')
      const checkKey = `${checkType}:${transitionKey}`
      const checkSet = checkIndexes.get(unit.id)!
      if (!checkSet.has(checkKey)) {
        checkSet.add(checkKey)
        unit.subchecks.push({ id: checkKey, checkType, status: String(payload.status || payload.state || 'unknown'), event })
      }
    }
  }
  // Missing parent units are represented as virtual containers.  No status is
  // inferred for a legacy parent; collection/lineage parents are aggregated
  // only from their visible children.
  for (const unit of [...units.values()]) {
    if (!unit.parentUnitId || units.has(unit.parentUnitId)) continue
    const isCollection = unit.parentUnitId.startsWith('review:collection:')
    units.set(unit.parentUnitId, {
      id: unit.parentUnitId,
      unitType: isCollection ? 'review' : 'unknown',
      phase: isCollection ? 'review' : 'unknown',
      actor: 'system',
      role: isCollection ? 'review' : 'legacy',
      status: 'unknown',
      label: isCollection ? '集合审核批次' : '父级关联（详情不可用）',
      firstSequence: unit.firstSequence,
      lastSequence: unit.lastSequence,
      children: [],
      toolSteps: [],
      events: [],
      transitions: [],
      subchecks: [],
      virtual: true,
    })
    transitionIndexes.set(unit.parentUnitId, new Set())
    checkIndexes.set(unit.parentUnitId, new Set())
  }
  const roots: DecisionUnit[] = []
  for (const unit of units.values()) {
    if (unit.virtual) continue
    unit.toolSteps = buildUnitToolSteps(unit.events)
    if (unit.parentUnitId) {
      const parent = units.get(unit.parentUnitId)
      if (parent) parent.children.push(unit)
      else roots.push(unit)
    } else roots.push(unit)
  }
  for (const parent of units.values()) {
    if (!parent.virtual) continue
    parent.children.sort((left, right) => left.firstSequence - right.firstSequence)
    const states = parent.children.map((child) => child.status)
    parent.firstSequence = Math.min(...parent.children.map((child) => child.firstSequence), parent.firstSequence)
    parent.lastSequence = Math.max(...parent.children.map((child) => child.lastSequence), parent.lastSequence)
    parent.status = states.some((state) => state === 'failed' || state === 'blocked') ? 'partial' : states.length > 0 && states.every((state) => state === 'completed') ? 'completed' : 'pending'
    roots.push(parent)
  }
  return roots.sort((left, right) => left.firstSequence - right.firstSequence)
}

export function normalizeTimeline(events: AgentRunEvent[]): TimelineRow[] {
  const rows: TimelineRow[] = []
  const steps = new Map<string, ToolStep>()
  const unique = new Map<string, AgentRunEvent>()
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) unique.set(`${event.runId}:${event.sequence}`, event)
  const ordered = [...unique.values()].sort((left, right) => left.sequence - right.sequence)

  const findFallbackStep = (toolName: string, sequence: number): ToolStep | undefined => {
    const candidates = [...steps.values()].filter((step) => !step.result && step.toolName === toolName && (step.call?.sequence || 0) < sequence)
    return candidates.sort((left, right) => (right.call?.sequence || 0) - (left.call?.sequence || 0))[0]
  }

  for (const event of ordered) {
    const payload = eventPayload(event)
    if (event.kind === 'tool_call' || event.kind === 'tool_result') {
      const explicitCallId = typeof payload.call_id === 'string' && payload.call_id ? payload.call_id : ''
      const toolName = String(payload.tool_name || '未知工具')
      const fallbackStep = !explicitCallId && event.kind === 'tool_result' ? findFallbackStep(toolName, event.sequence) : undefined
      const stableCallId = explicitCallId || fallbackStep?.callId || `sequence-${event.sequence}`
      let step = steps.get(stableCallId)
      if (!step) {
        step = { id: `${event.runId}-${stableCallId}`, callId: stableCallId, toolName, toolLabel: typeof payload.tool_label === 'string' ? payload.tool_label : undefined, observations: [], status: 'running' }
        steps.set(stableCallId, step)
        rows.push({ kind: 'tool', step })
      }
      if (typeof payload.tool_name === 'string' && payload.tool_name) step.toolName = payload.tool_name
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
      const observations = Array.isArray(payload.observations)
        ? payload.observations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
        : payload.observation && typeof payload.observation === 'object'
          ? [payload.observation as Record<string, unknown>]
          : []
      const step = callId ? steps.get(callId) : undefined
      if (step) { step.observations.push(...observations); continue }
      if (callId) {
        const pending: ToolStep = { id: `${event.runId}-${callId}`, callId, toolName: String(payload.tool_name || '未知工具'), toolLabel: typeof payload.tool_label === 'string' ? payload.tool_label : undefined, observations, status: 'running' }
        steps.set(callId, pending)
        rows.push({ kind: 'tool', step: pending })
        continue
      }
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
