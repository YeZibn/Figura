import { useState } from 'react'
import { ChevronDown, ChevronRight, Terminal } from 'lucide-react'
import { eventLabel, failureCategoryLabel, providerLabel, timestampLabel, toolResultIntegrityDetail } from '../domain/display'
import { boundedDisplayText, eventPayload, textDetail } from '../domain/records'
import { reviewIssues, reviewStateLabel, reviewTypeLabel } from '../domain/review'
import { executionGateValue, projectUserTimeline, timelineProtocolStatus, type DecisionPhase, type TimelineNodeStatus, type RunTimeline as RunTimelineModel, type UserTimelineItem } from '../domain/run/timeline'
import type { AgentRunEvent, GeneratedChartReference } from '../types/protocol'
import type { PreviewResourceLoader } from '../previewResources'
import type { PreviewOpener } from './types'
import { CopyDetailButton, EvaluationDetailResourceView, traceEventDetail } from './common'
import { GeneratedChartView, ObservationView } from './preview'

export function ReviewTimelineItem({ event }: { event: AgentRunEvent }) {
  const payload = eventPayload(event)
  const state = payload.state
  const blocking = payload.blocking === true
  const subject = payload.subject_id || payload.candidate_id
  const attempt = payload.attempt
  const issues = reviewIssues(payload)
  const type = payload.review_type
  const subjectText = subject === undefined || subject === null ? '' : String(subject)
  const details = { event: event.kind, payload }
  return <div className={'review-timeline-item ' + (blocking ? 'blocking' : 'released')}>
    <span className="trace-event-dot" />
    <div className="review-timeline-card">
      <div className="review-timeline-heading"><div><strong>{reviewTypeLabel(type)}</strong><small>{timestampLabel(event.timestamp)} · {reviewStateLabel(state, blocking)}</small></div>{blocking && <span className="review-blocking-badge">主链路已暂停</span>}</div>
      {(subjectText || attempt !== undefined) && <div className="review-timeline-meta">{subjectText && <span>对象：<code>{subjectText}</code></span>}{attempt !== undefined && <span>第 {String(attempt)} 次</span>}</div>}
      {issues.length > 0 && <div className="review-timeline-issues">{issues.map((issue, index) => <span key={`${String(issue.code || 'issue')}-${index}`}>{String(issue.message || issue.code || '审核问题')}</span>)}</div>}
      <details className="review-timeline-details"><summary>查看审核详情</summary><CopyDetailButton value={details} /><pre>{textDetail(details)}</pre></details>
    </div>
  </div>
}

function decisionStatusLabel(status: TimelineNodeStatus): string {
  return ({ running: '运行中', completed: '已完成', reviewing: '审核中', passed: '审核已通过', published: '已发布', failed: '失败', partial: '部分完成', blocked: '已阻塞', abandoned: '已中断', unknown: '状态未知', skipped: '未执行', unavailable: '产物不可用' } as Record<TimelineNodeStatus, string>)[status]
}

function decisionPhaseLabel(phase: DecisionPhase): string {
  return ({ observe: '观察', decide: '决策', assemble: '组装', render: '渲染', review: '审核', repair: '修复', publish: '发布', action: '执行' } as Record<DecisionPhase, string>)[phase]
}

function timelineStatusLabel(status: UserTimelineItem['status']): string {
  return decisionStatusLabel(status)
}

function UserTimelineItemView({ item, previewLoader, onPreview, evaluationId, caseId }: { item: UserTimelineItem; previewLoader: PreviewResourceLoader | null; onPreview?: PreviewOpener; evaluationId?: string; caseId?: string }) {
  const callPayload = item.call ? eventPayload(item.call) : null
  const resultPayload = item.result ? eventPayload(item.result) : null
  const resultValue = resultPayload?.result ?? resultPayload?.message
  const [open, setOpen] = useState(false)
  const eventRows = item.visibleEvents.length > 0 ? item.visibleEvents : item.event ? [item.event] : []
  const phase = item.phase && item.itemType !== 'error' ? decisionPhaseLabel(item.phase) : ''
  const summaryEvent = item.result || item.event || item.call
  const summaryTimestamp = summaryEvent?.timestamp ? timestampLabel(summaryEvent.timestamp) : ''
  const failureReason = item.failure
    ? boundedDisplayText(item.failure.safeMessage || (item.failure.category ? failureCategoryLabel(item.failure.category) : '执行失败'))
    : undefined
  const failureLabel = item.itemType === 'review' ? '未通过原因' : '失败原因'
  const rawEvents = item.events.map((event) => ({ sequence: event.sequence, kind: event.kind, payload: eventPayload(event) }))
  return <details className={'user-timeline-item user-timeline-' + item.itemType + ' user-timeline-' + item.status} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary><span className="user-timeline-marker" /><span className="user-timeline-heading"><strong>{item.label}</strong><small>{phase || (item.itemType === 'error' ? '需要关注' : item.itemType === 'review' ? '审核流程' : '执行过程')}{summaryTimestamp ? ` · ${summaryTimestamp}` : ''}</small>{failureReason && <small className="user-timeline-failure-summary">{failureLabel}：{failureReason}</small>}</span><span className={'run-status ' + item.status}>{timelineStatusLabel(item.status)}</span>{item.resultTruncated && <span className="user-timeline-truncation" title="工具结果已按安全上限截断">结果已截断</span>}<ChevronRight className="user-timeline-chevron" size={14} /></summary>
    <div className="user-timeline-detail">
      {eventRows.map((event) => <div className="user-timeline-event" key={`${event.runId}-${event.sequence}`}><span><strong>{eventLabel(event)}</strong><small>{timestampLabel(event.timestamp)}</small><span>{traceEventDetail(event)}</span></span></div>)}
      {callPayload && Object.prototype.hasOwnProperty.call(callPayload, 'arguments') && <div><div className="trace-detail-heading"><label>调用参数</label><CopyDetailButton value={callPayload.arguments} /></div><pre>{textDetail(callPayload.arguments)}</pre></div>}
      {item.result && <div><div className="trace-detail-heading"><label>工具结果</label><CopyDetailButton value={resultValue} /></div>{traceEventDetail(item.result) && <div className="trace-detail-summary">{traceEventDetail(item.result)}</div>}{item.resultTruncated && <small className="trace-warning">{toolResultIntegrityDetail(resultPayload || {})}</small>}<pre>{textDetail(resultValue)}</pre>{resultPayload && Boolean(resultPayload.detailResource) && <EvaluationDetailResourceView resource={resultPayload.detailResource as Record<string, unknown>} evaluationId={evaluationId} caseId={caseId} />}</div>}
      {item.observations.map((observation, index) => <ObservationView key={index} observation={observation} loader={previewLoader} onPreview={onPreview} />)}
      {item.failure && <div className="user-timeline-failure">{item.itemType === 'review' ? '审核未通过原因：' : '失败原因：'}{item.failure.safeMessage || item.failure.category || '执行失败'}</div>}
      {rawEvents.length > 0 && <details className="user-timeline-raw"><summary>查看技术详情（{rawEvents.length}）</summary><CopyDetailButton value={rawEvents} /><pre>{textDetail(rawEvents)}</pre></details>}
    </div>
  </details>
}

export function RunTimeline({ timeline, expanded, onToggle, previewLoader, onPreview, onInterrupt, onRetry, onResume, showSummary = true, evaluationId, caseId }: { timeline: RunTimelineModel; expanded: boolean; onToggle: () => void; previewLoader: PreviewResourceLoader | null; onPreview?: PreviewOpener; onInterrupt?: () => void; onRetry?: () => void; onResume?: () => void; showSummary?: boolean; evaluationId?: string; caseId?: string }) {
  const protocolStatus = timelineProtocolStatus(timeline.events)
  const userItems = projectUserTimeline(timeline.events)
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
      {protocolStatus.status === 'unsupported_version' && <div className="trace-warning" role="status">此运行记录使用了当前客户端不支持的时间线版本；摘要和独立产物仍保留，但不会推断或展示执行步骤。</div>}
      {protocolStatus.status === 'malformed' && <div className="trace-warning" role="status">此运行记录包含不符合当前事件协议的内容；为避免误报状态，执行步骤暂不可用。</div>}
      {gateBlocking && <div className="trace-warning review-gate-banner" role="status"><strong>审核阻塞生成发布</strong><span>{reviewTypeLabel(executionGate?.reviewType)} · {reviewStateLabel(executionGate?.state, true)}</span></div>}
      {protocolStatus.status === 'supported' && userItems.length === 0 && <div className="trace-empty">没有可展示的业务执行步骤。</div>}
      {protocolStatus.status === 'supported' && userItems.map((item) => <UserTimelineItemView key={item.id} item={item} previewLoader={previewLoader} onPreview={onPreview} evaluationId={evaluationId} caseId={caseId} />)}
    </div>}
  </section>
}

export function GeneratedArtifacts({ artifacts, loader, onPreview }: { artifacts: GeneratedChartReference[]; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  return <div className="run-result-artifacts">{artifacts.map((artifact, index) => <GeneratedChartView key={`${artifact.artifactId || artifact.candidateId || index}`} artifact={artifact} loader={loader} onPreview={onPreview} />)}</div>
}
