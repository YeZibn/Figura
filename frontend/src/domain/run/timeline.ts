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

export type DecisionUnitStatus = 'unknown' | 'pending' | 'completed' | 'failed' | 'partial' | 'blocked' | 'abandoned'
export type DecisionUnitType = 'measurement' | 'generation' | 'review' | 'publication' | 'observation' | 'legacy' | 'unknown'
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
  measurement: '测量决策',
  generation: '图表生成',
  review: '审核周期',
  publication: '发布状态',
  observation: '工具观察',
  legacy: '历史记录（关联不可用）',
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

function legacyUnitId(event: AgentRunEvent): string {
  return `legacy:${event.runId}:${event.kind}:${event.sequence}`
}

function unitStatus(event: AgentRunEvent, payload: Record<string, unknown>, current: DecisionUnitStatus): DecisionUnitStatus {
  const action = actionValue(correlationValue(payload, 'next_action', 'nextAction'))
  if (action?.required) return 'pending'
  if (event.kind === 'measurement_focus_applied' || event.kind === 'measurement_focus_requested' || event.kind === 'review_started' || event.kind === 'chart_review_started' || event.kind === 'review_subcheck' && payload.status === 'running') return 'pending'
  if (event.kind === 'measurement_focus_failed' || event.kind === 'measurement_repair_rejected' || event.kind === 'measurement_repair_exhausted' || event.kind === 'review_failed' || event.kind === 'generated_chart_rejected' || event.kind === 'run_failed') return 'failed'
  if (event.kind === 'generated_chart_published' || event.kind === 'review_completed' || event.kind === 'chart_review_completed') {
    const state = String(payload.state || payload.publication_status || payload.publicationStatus || '')
    return state.includes('warning') ? 'completed' : state.includes('fail') || state.includes('reject') ? 'failed' : 'completed'
  }
  if (event.kind === 'measurement_evidence_selected' || event.kind === 'measurement_evidence_discarded') return 'completed'
  if (event.kind === 'measurement_observed') return String(payload.decision_status || payload.decisionStatus || '') === 'pending' ? 'pending' : 'completed'
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
  return ['measurement', 'generation', 'review', 'publication', 'observation', 'legacy', 'unknown'].includes(text) ? text as DecisionUnitType : 'unknown'
}

function phaseValue(value: unknown): DecisionPhase {
  const text = String(value || 'unknown')
  return ['observe', 'decide', 'assemble', 'render', 'review', 'repair', 'publish', 'action', 'unknown'].includes(text) ? text as DecisionPhase : 'unknown'
}

function roleValue(value: unknown): DecisionRole {
  const text = String(value || 'legacy')
  return ['observation', 'decision', 'action', 'gate', 'review', 'publication', 'legacy'].includes(text) ? text as DecisionRole : 'legacy'
}

function buildUnitToolSteps(events: AgentRunEvent[]): ToolStep[] {
  const rows = normalizeTimeline(events)
  return rows.filter((row): row is { kind: 'tool'; step: ToolStep } => row.kind === 'tool').map((row) => row.step)
}

function unitEventMetadata(event: AgentRunEvent): { id: string; type: DecisionUnitType; phase: DecisionPhase; actor: string; role: DecisionRole; parent?: string; legacy: boolean } {
  const payload = eventPayload(event)
  const rawId = correlationValue(payload, 'unit_id', 'unitId')
  const legacy = typeof rawId !== 'string' || !rawId
  return {
    id: legacy ? legacyUnitId(event) : String(rawId),
    type: legacy ? 'legacy' : unitType(correlationValue(payload, 'unit_type', 'unitType')),
    phase: legacy ? 'unknown' : phaseValue(payload.phase),
    actor: legacy ? 'unknown' : String(payload.actor || 'unknown'),
    role: legacy ? 'legacy' : roleValue(payload.role),
    parent: legacy ? undefined : (typeof correlationValue(payload, 'parent_unit_id', 'parentUnitId') === 'string' ? String(correlationValue(payload, 'parent_unit_id', 'parentUnitId')) : undefined),
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
