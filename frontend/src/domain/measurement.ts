import type { AgentRunEvent, MeasurementRepairSummary } from '../types/protocol'
import { boundedDisplayText, eventPayload, recordValue } from './records'

function repairField(sources: Record<string, unknown>[], keys: string[]): string | undefined {
  for (const source of sources) {
    for (const key of keys) {
      const value = boundedDisplayText(source[key])
      if (value) return value
    }
  }
  return undefined
}

function repairNumberField(sources: Record<string, unknown>[], keys: string[]): number | undefined {
  for (const source of sources) {
    for (const key of keys) {
      const value = source[key]
      if (typeof value === 'number' && Number.isFinite(value)) return value
    }
  }
  return undefined
}

export function measurementRepairSummary(event: AgentRunEvent): MeasurementRepairSummary | null {
  const repairKinds = new Set(['measurement_observed', 'measurement_repair_required', 'measurement_repair_rejected', 'measurement_repair_exhausted', 'measurement_decision_required', 'measurement_focus_requested', 'measurement_focus_applied', 'measurement_focus_failed', 'measurement_evidence_selected', 'measurement_evidence_discarded'])
  if (!repairKinds.has(event.kind)) return null
  const payload = eventPayload(event)
  const repair = recordValue(payload.repair) || payload
  const target = recordValue(repair.target) || recordValue(payload.target) || {}
  const sources = [repair, payload, target]
  return {
    panelId: repairField(sources, ['panel_id', 'panelId']),
    attemptId: repairField(sources, ['attempt_id', 'attemptId']),
    parentAttemptId: repairField(sources, ['parent_attempt_id', 'parentAttemptId']),
    targetType: repairField(sources, ['region_kind', 'target_type', 'targetType', 'kind']),
    status: repairField(sources, ['status']),
    code: repairField(sources, ['code']),
    reason: repairField(sources, ['reason', 'message']),
    nextAction: repairField(sources, ['next_action', 'nextAction']),
    budgetRemaining: repairNumberField(sources, ['budget_remaining', 'budgetRemaining']),
    selectedRefs: Array.isArray(repair.selected_refs) ? repair.selected_refs.map(String).slice(0, 64) : undefined,
    discardedRefs: Array.isArray(repair.discarded_refs) ? repair.discarded_refs.map(String).slice(0, 64) : undefined,
    observationScope: recordValue(repair.observation_scope) || recordValue(payload.observation_scope) || undefined,
  }
}

export function measurementRepairDetail(event: AgentRunEvent): string {
  const payload = eventPayload(event)
  if (event.kind === 'measurement_decision_required') {
    const decision = recordValue(payload.decision) || payload
    const refs = Array.isArray(decision.refs) ? decision.refs.map((item) => {
      const value = recordValue(item)
      return value?.ref || item
    }).filter(Boolean).slice(0, 12).join('、') : ''
    const issues = Array.isArray(decision.issues) ? decision.issues.map((item) => {
      const value = recordValue(item)
      return value?.message || value?.code || item
    }).filter(Boolean).slice(0, 2).join('；') : ''
    return [
      decision.panel_id || decision.panelId ? `面板：${String(decision.panel_id || decision.panelId)}` : '',
      decision.attempt_id || decision.attemptId ? `attempt：${String(decision.attempt_id || decision.attemptId)}` : '',
      refs ? `候选：${refs}` : '',
      issues ? `问题：${issues}` : '',
      '等待主 Agent 选择、舍弃或定向补充',
    ].filter(Boolean).join(' · ')
  }
  if (event.kind === 'measurement_focus_requested' || event.kind === 'measurement_focus_applied' || event.kind === 'measurement_focus_failed') {
    const target = recordValue(payload.target) || payload
    const focus = recordValue(payload.focus)
    const refs = Array.isArray(target.resolved_refs) ? target.resolved_refs.join('、') : Array.isArray(focus?.target_refs) ? focus.target_refs.join('、') : ''
    const mode = target.mode || focus?.mode
    const scope = focus?.search_scope || target.region_kind
    const status = focus?.status || payload.status
    return [
      refs ? `候选：${String(refs)}` : '',
      mode ? `模式：${String(mode)}` : '',
      scope ? `范围：${String(scope)}` : '',
      status ? `状态：${String(status)}` : '',
      event.kind === 'measurement_focus_failed' ? '局部证据不足，未扩大到完整面板' : event.kind === 'measurement_focus_applied' ? '局部范围已应用' : '已请求局部范围',
    ].filter(Boolean).join(' · ')
  }
  if (event.kind === 'measurement_evidence_selected') {
    const selected = Array.isArray(payload.selected_refs) ? payload.selected_refs.join('、') : ''
    const discarded = Array.isArray(payload.discarded_refs) ? payload.discarded_refs.join('、') : ''
    return [selected ? `采用：${selected}` : '', discarded ? `舍弃：${discarded}` : '', '已记录主 Agent 证据选择'].filter(Boolean).join(' · ')
  }
  if (event.kind === 'measurement_evidence_discarded') {
    const discarded = Array.isArray(payload.discarded_refs) ? payload.discarded_refs.join('、') : ''
    const reason = boundedDisplayText(payload.evidence_basis) || '当前测量候选未被采用'
    return [discarded ? `舍弃：${discarded}` : '明确放弃当前候选', `依据：${reason}`].join(' · ')
  }
  if (event.kind === 'measurement_observed') {
    const scope = recordValue(payload.observation_scope)
    const applied = scope?.applied === true ? '局部范围已应用' : scope ? '已记录观察范围' : '面板范围内观察'
    const panel = payload.panel_id || payload.panelId
    const status = payload.measurement_status || payload.status
    return [panel ? `面板：${String(panel)}` : '', status ? `测量：${String(status)}` : '', applied].filter(Boolean).join(' · ')
  }
  if (event.kind === 'assembly_validation_failure') {
    const issues = Array.isArray(payload.issues) ? payload.issues.map(String).slice(0, 3).join('；') : ''
    return [payload.error ? `原因：${String(payload.error)}` : 'ChartSpec 组装校验未通过', issues ? `细节：${issues}` : ''].filter(Boolean).join(' · ')
  }
  const summary = measurementRepairSummary(event)
  if (!summary) return ''
  const details = [
    summary.panelId ? `面板：${summary.panelId}` : '',
    summary.targetType ? `目标：${summary.targetType}` : '',
    summary.attemptId ? `attempt：${summary.attemptId}` : '',
    summary.parentAttemptId ? `父 attempt：${summary.parentAttemptId}` : '',
    summary.budgetRemaining !== undefined ? `剩余次数：${summary.budgetRemaining}` : '',
    summary.reason ? `原因：${summary.reason}` : '',
    summary.nextAction ? `下一步：${summary.nextAction}` : '',
  ].filter(Boolean)
  if (details.length) return details.join(' · ')
  if (event.kind === 'measurement_repair_required') return '等待同一面板内的定向补充。'
  if (event.kind === 'measurement_repair_rejected') return '定向补充未被接受，保留当前测量证据。'
  return '定向补充次数已用尽，当前候选不会自动发布。'
}

export function measurementEventClass(kind: string): string {
  const measurementKinds = new Set(['measurement_observed', 'measurement_repair_required', 'measurement_repair_rejected', 'measurement_repair_exhausted', 'measurement_decision_required', 'measurement_focus_requested', 'measurement_focus_applied', 'measurement_focus_failed', 'measurement_evidence_selected', 'measurement_evidence_discarded'])
  if (!measurementKinds.has(kind)) return ''
  if (kind === 'measurement_focus_applied' || kind === 'measurement_evidence_selected') return 'repair success'
  if (kind === 'measurement_focus_failed' || kind === 'measurement_repair_rejected' || kind === 'measurement_repair_exhausted') return 'repair error'
  return 'repair pending'
}
