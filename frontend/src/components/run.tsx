import { useState } from 'react'
import { ChevronDown, ChevronRight, Terminal } from 'lucide-react'
import { eventLabel, providerLabel, timestampLabel, toolResultIntegrityDetail } from '../domain/display'
import { eventPayload, recordValue, textDetail } from '../domain/records'
import { isReviewEvent, reviewGateFromPayload, reviewIssues, reviewStateLabel, reviewTypeLabel } from '../domain/review'
import { measurementEventClass } from '../domain/measurement'
import { executionGateValue, normalizeTimeline, type RunTimeline as RunTimelineModel } from '../domain/run/timeline'
import { isMeasurementRepairEventKind } from '../types/protocol'
import type { AgentRunEvent, GeneratedChartReference } from '../types/protocol'
import type { PreviewResourceLoader } from '../previewResources'
import type { PreviewOpener } from './types'
import { CopyDetailButton, EvaluationDetailResourceView, traceEventDetail } from './common'
import { GeneratedChartView, ObservationView } from './preview'

export function ReviewTimelineItem({ event }: { event: AgentRunEvent }) {
  const payload = eventPayload(event)
  const domain = recordValue(payload.repair) || payload
  const gate = reviewGateFromPayload(payload)
  const state = payload.state || gate?.state || (event.kind === 'review_started' || event.kind === 'chart_review_started' ? 'reviewing' : undefined)
  const blocking = typeof gate?.blocking === 'boolean' ? gate.blocking : typeof payload.blocking === 'boolean' ? payload.blocking : !['passed', 'passed_with_warning'].includes(String(state || ''))
  const subject = domain.subjectId || domain.subject_id || domain.candidateId || domain.candidate_id || domain.attemptId || domain.attempt_id || gate?.subjectId || gate?.subject_id
  const attempt = domain.attempt || gate?.attempt
  const maxAttempts = domain.maxAttempts || domain.max_attempts || gate?.maxAttempts || gate?.max_attempts
  const nextAction = domain.nextAction || domain.next_action || gate?.nextAction || gate?.next_action
  const issues = reviewIssues(domain, gate)
  const type = payload.reviewType || payload.review_type || gate?.reviewType || gate?.review_type || (event.kind.startsWith('measurement_') ? 'measurement' : event.kind.startsWith('chart_') || event.kind.startsWith('generated_') ? 'generated_chart' : undefined)
  const subjectText = subject === undefined || subject === null ? '' : String(subject)
  const nextActionText = nextAction === undefined || nextAction === null ? '' : String(nextAction)
  const details = { event: event.kind, payload, executionGate: gate }
  return <div className={'review-timeline-item ' + (blocking ? 'blocking' : 'released')}>
    <span className="trace-event-dot" />
    <div className="review-timeline-card">
      <div className="review-timeline-heading"><div><strong>{reviewTypeLabel(type)}</strong><small>{timestampLabel(event.timestamp)} · {reviewStateLabel(state, blocking)}</small></div>{blocking && <span className="review-blocking-badge">主链路已暂停</span>}</div>
      {(subjectText || attempt !== undefined) && <div className="review-timeline-meta">{subjectText && <span>对象：<code>{subjectText}</code></span>}{attempt !== undefined && <span>第 {String(attempt)} / {maxAttempts !== undefined ? String(maxAttempts) : '—'} 次</span>}</div>}
      {issues.length > 0 && <div className="review-timeline-issues">{issues.map((issue, index) => <span key={`${String(issue.code || 'issue')}-${index}`}>{String(issue.message || issue.code || '审核问题')}</span>)}</div>}
      {nextActionText && <div className="review-timeline-next">下一步：{nextActionText}</div>}
      <details className="review-timeline-details"><summary>查看审核详情</summary><CopyDetailButton value={details} /><pre>{textDetail(details)}</pre></details>
    </div>
  </div>
}

export function RunTimeline({ timeline, expanded, onToggle, previewLoader, onPreview, onInterrupt, onRetry, onResume, showSummary = true, evaluationId, caseId }: { timeline: RunTimelineModel; expanded: boolean; onToggle: () => void; previewLoader: PreviewResourceLoader | null; onPreview?: PreviewOpener; onInterrupt?: () => void; onRetry?: () => void; onResume?: () => void; showSummary?: boolean; evaluationId?: string; caseId?: string }) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const rows = normalizeTimeline(timeline.events)
  const summary = timeline.summary
  const status = summary.status
  const statusText = status === 'completed' ? '已完成' : status === 'failed' ? '失败' : status === 'interrupted' ? '已中断' : summary.cancelRequested ? '正在中断' : '运行中'
  const executionGate = executionGateValue(timeline)
  const gateBlocking = executionGate?.blocking === true
  return <section className={'run-timeline ' + status + (expanded ? ' expanded' : '')}>
    {showSummary && <button className="run-summary" onClick={onToggle} aria-expanded={expanded} aria-controls={`trace-${summary.runId}`}><span className="run-arrow">{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span><span className="run-summary-icon"><Terminal size={14} /></span><span className="run-summary-copy"><strong>执行过程</strong><small>{timestampLabel(summary.createdAt)} · {summary.eventCount || timeline.events.length} 个事件{summary.provider ? ` · ${providerLabel(summary.provider)}${summary.model ? ` · ${summary.model}` : ''}` : ''}{summary.retryOf ? ` · 重试自 ${summary.retryOf}` : ''}</small></span><span className={'run-status ' + status}>{statusText}</span></button>}
    {(status === 'running' && onInterrupt) || ((status === 'failed' || status === 'interrupted') && (onRetry || onResume)) ? <div className="run-actions">
      {status === 'running' && onInterrupt && <button type="button" className="small-action" onClick={onInterrupt} disabled={summary.cancelRequested}>{summary.cancelRequested ? '正在中断' : '中断运行'}</button>}
      {status !== 'running' && onResume && summary.recovery?.status === 'available' && <button type="button" className="small-action" onClick={onResume}>继续执行</button>}
      {(status === 'failed' || status === 'interrupted') && onRetry && <button type="button" className="small-action" onClick={onRetry}>重试本次运行</button>}
    </div> : null}
    {expanded && <div className="run-trace" id={`trace-${summary.runId}`}>
      {summary.recovery && summary.recovery.status !== 'unavailable' && <div className={'trace-warning recovery-' + summary.recovery.status} role="status">{summary.recovery.status === 'available' ? `可继续执行：${summary.recovery.phase || '已保存'} · 下一步 ${summary.recovery.nextAction || '继续处理'}` : `暂时无法继续执行：${summary.recovery.blockedReason || '恢复状态受限'}，可使用“重试本次运行”。`}</div>}
      {summary.historyWarning && <div className="trace-warning" role="status">部分执行记录未能持久化，当前显示的过程可能不完整。</div>}
      {timeline.historyGap && <div className="trace-warning" role="status">历史记录存在缺口，未显示缺失的执行步骤。</div>}
      {timeline.integrity && timeline.integrity.status !== 'complete' && <div className="trace-warning" role="status">{timeline.integrity.status === 'unavailable' ? '部分大结果只有摘要，旧 bundle 没有可恢复的完整安全资源。' : timeline.integrity.status === 'redacted' ? '部分字段已按安全边界隐藏；可见内容仍来自脱敏事件。' : '部分事件达到展示上限；可用时可加载完整安全结果。'}</div>}
      {gateBlocking && <div className="trace-warning review-gate-banner" role="status"><strong>主链路已暂停</strong><span>{reviewTypeLabel(executionGate?.reviewType)} · {reviewStateLabel(executionGate?.state, true)}{executionGate?.nextAction ? ` · 下一步：${String(executionGate.nextAction)}` : ''}</span></div>}
      {rows.length === 0 && <div className="trace-empty">没有可恢复的执行事件。</div>}
      {rows.map((row) => row.kind === 'event' ? (
        isReviewEvent(row.event) ? <ReviewTimelineItem key={`${row.event.runId}-${row.event.sequence}`} event={row.event} /> : <div className={'trace-event ' + measurementEventClass(row.event.kind) + (row.event.kind === 'run_failed' || row.event.kind === 'run_interrupted' || row.event.kind === 'history_gap' || row.event.kind === 'assembly_validation_failure' ? ' error' : '')} key={`${row.event.runId}-${row.event.sequence}`}><span className="trace-event-dot" /><span className="trace-event-copy"><strong>{eventLabel(row.event)}</strong><small>{timestampLabel(row.event.timestamp)}{isMeasurementRepairEventKind(row.event.kind) ? ` · ${row.event.kind}` : ''}</small><span>{traceEventDetail(row.event)}</span></span></div>
      ) : <div className="trace-tool" key={row.step.id}><button className="trace-tool-header" onClick={() => setExpandedSteps((current) => { const next = new Set(current); next.has(row.step.id) ? next.delete(row.step.id) : next.add(row.step.id); return next })} aria-expanded={expandedSteps.has(row.step.id)}><span className="trace-event-dot" /><span className="trace-tool-name"><strong>{row.step.toolLabel || row.step.toolName}</strong><small>{row.step.toolName} · {row.step.callId}</small></span><span className={'run-status ' + row.step.status}>{row.step.status === 'running' ? '运行中' : row.step.status === 'success' ? '完成' : '失败'}</span>{expandedSteps.has(row.step.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>{expandedSteps.has(row.step.id) && <div className="trace-tool-detail">{row.step.call && <div><div className="trace-detail-heading"><label>调用参数</label><CopyDetailButton value={eventPayload(row.step.call).arguments} /></div><pre>{textDetail(eventPayload(row.step.call).arguments)}</pre></div>}{row.step.result && <div><div className="trace-detail-heading"><label>工具结果</label><CopyDetailButton value={eventPayload(row.step.result).result || eventPayload(row.step.result).message} /></div>{row.step.resultTruncated && <small className="trace-warning">{toolResultIntegrityDetail(eventPayload(row.step.result))}</small>}<pre>{textDetail(eventPayload(row.step.result).result || eventPayload(row.step.result).message)}</pre>{Boolean(eventPayload(row.step.result).detailResource) && <EvaluationDetailResourceView resource={eventPayload(row.step.result).detailResource as Record<string, unknown>} evaluationId={evaluationId} caseId={caseId} />}</div>}{row.step.observations.map((observation, index) => <ObservationView key={index} observation={observation} loader={previewLoader} onPreview={onPreview} />)}</div>}</div>)}
    </div>}
  </section>
}

export function GeneratedArtifacts({ artifacts, loader, onPreview }: { artifacts: GeneratedChartReference[]; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  return <div className="run-result-artifacts">{artifacts.map((artifact, index) => <GeneratedChartView key={`${artifact.artifactId || artifact.candidateId || index}`} artifact={artifact} loader={loader} onPreview={onPreview} />)}</div>
}
