import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, FileImage, LoaderCircle, Terminal } from 'lucide-react'
import { providerLabel, timestampLabel } from '../../domain/display'
import type { RunSummary } from '../../types/protocol'
import type {
  FiguraToolCallDetailDto,
  FiguraToolTimelineSnapshotDto,
} from '../../api/figura/types'
import {
  figuraToolAttemptStatusLabel,
  mapFiguraToolTimelineStep,
  type FiguraToolTimelineStepViewModel,
} from '../../domain/figura/timeline'
import type { PreviewOpener } from '../types'
import { PreviewImage } from '../preview'

function summaryStatus(run: RunSummary): string {
  if (run.executionState === 'needs_reconciliation') return '等待工具核对'
  if (run.status === 'completed') return '已完成'
  if (run.status === 'failed') return '失败'
  if (run.status === 'interrupted') return '已中断'
  return '运行中'
}

function ToolStep(props: {
  step: FiguraToolTimelineStepViewModel
  loadDetail: (callId: string) => Promise<FiguraToolCallDetailDto>
  sourceContentUrl: (source: NonNullable<FiguraToolCallDetailDto['source']>) => string
  observationContentUrl: (callId: string) => string
  onPreview?: PreviewOpener
}) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<FiguraToolCallDetailDto | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const detailRequest = useRef(0)

  const fetchDetail = () => {
    const requestId = ++detailRequest.current
    setLoading(true)
    setFailed(false)
    void props.loadDetail(props.step.callId)
      .then((value) => {
        if (detailRequest.current === requestId) setDetail(value)
      })
      .catch(() => {
        if (detailRequest.current === requestId) setFailed(true)
      })
      .finally(() => {
        if (detailRequest.current === requestId) setLoading(false)
      })
  }

  useEffect(() => {
    if (open) fetchDetail()
  }, [open, props.step.updatedAt, props.step.status])

  const label = props.step.label
  return <details
    className={'user-timeline-item user-timeline-tool user-timeline-' + props.step.status}
    open={open}
    onToggle={(event) => setOpen(event.currentTarget.open)}
  >
    <summary>
      <span className="user-timeline-marker" />
      <span className="user-timeline-heading">
        <strong>{label}</strong>
        <small>{timestampLabel(props.step.createdAt)} · {props.step.summary}</small>
      </span>
      <span className={'run-status ' + props.step.status}>{props.step.statusLabel}</span>
      <ChevronRight className="user-timeline-chevron" size={14} />
    </summary>
    <div className="user-timeline-detail figura-tool-detail">
      {loading && <div className="figura-tool-loading"><LoaderCircle className="spin-icon" size={13} />正在读取工具详情</div>}
      {failed && <div className="trace-warning" role="status">工具详情暂时无法读取。</div>}
      {detail && <>
        {detail.argumentSummary && <div><strong>执行内容：</strong>{detail.argumentSummary}</div>}
        {detail.resultSummary && <div><strong>结果摘要：</strong>{detail.resultSummary}</div>}
        {detail.errorSummary && <div className="user-timeline-failure">{detail.errorSummary}</div>}
        {detail.attempts?.length ? <div className="figura-tool-attempts">
          <strong>执行尝试</strong>
          {detail.attempts.map((attempt) => <small key={attempt.attemptNumber}>
            第 {attempt.attemptNumber} 次 · {figuraToolAttemptStatusLabel(attempt.status)}
            {' · '}{timestampLabel(attempt.startedAt)}
            {attempt.finishedAt ? ' → ' + timestampLabel(attempt.finishedAt) : ''}
            {attempt.errorSummary ? ' · ' + attempt.errorSummary : ''}
          </small>)}
        </div> : null}
        {detail.source && <div className="figura-tool-preview">
          <strong><FileImage size={12} />来源图像 · {detail.source.name}</strong>
          <PreviewImage
            loader={null}
            fallbackUrl={props.sourceContentUrl(detail.source)}
            alt={detail.source.name}
            title={detail.source.name}
            sourceLabel="工具来源"
            onPreview={props.onPreview}
          />
        </div>}
        {detail.observationAvailable && <div className="figura-tool-preview">
          <strong><FileImage size={12} />观察标注</strong>
          <PreviewImage
            loader={null}
            fallbackUrl={props.observationContentUrl(props.step.callId)}
            alt={label + '观察标注'}
            title={label + '观察标注'}
            sourceLabel="观察结果"
            onPreview={props.onPreview}
          />
        </div>}
        {!detail.argumentSummary && !detail.resultSummary && !detail.attempts?.length && !detail.source && !detail.errorSummary
          ? <small className="figura-tool-minimal">此工具仅展示标识、状态和时间。</small>
          : null}
      </>}
    </div>
  </details>
}

export function ToolTimeline(props: {
  summary: RunSummary
  snapshot?: FiguraToolTimelineSnapshotDto
  expanded: boolean
  onToggle: () => void
  loadSnapshot: () => Promise<FiguraToolTimelineSnapshotDto>
  onSnapshotLoaded: (snapshot: FiguraToolTimelineSnapshotDto) => void
  loadDetail: (callId: string) => Promise<FiguraToolCallDetailDto>
  sourceContentUrl: (source: NonNullable<FiguraToolCallDetailDto['source']>) => string
  observationContentUrl: (callId: string) => string
  onPreview?: PreviewOpener
}) {
  const { summary } = props
  const [snapshotLoading, setSnapshotLoading] = useState(false)
  const [snapshotFailed, setSnapshotFailed] = useState(false)
  const [snapshotRequested, setSnapshotRequested] = useState(false)
  const steps = props.snapshot?.steps.map((step) => mapFiguraToolTimelineStep(summary.runId, step)) ?? []

  useEffect(() => {
    if (!props.expanded || props.snapshot || snapshotRequested) return
    setSnapshotRequested(true)
    setSnapshotLoading(true)
    void props.loadSnapshot()
      .then(props.onSnapshotLoaded)
      .catch(() => setSnapshotFailed(true))
      .finally(() => setSnapshotLoading(false))
  }, [props.expanded, props.snapshot, props.loadSnapshot, props.onSnapshotLoaded, snapshotRequested])

  return <section className={'run-timeline ' + summary.status + (props.expanded ? ' expanded' : '')}>
    <button
      className="run-summary"
      onClick={props.onToggle}
      aria-expanded={props.expanded}
      aria-controls={'figura-tools-' + summary.runId}
    >
      <span className="run-arrow">{props.expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span>
      <span className="run-summary-icon"><Terminal size={14} /></span>
      <span className="run-summary-copy">
        <strong>执行过程</strong>
        <small>{timestampLabel(summary.createdAt)} · {props.snapshot ? steps.length + ' 个工具调用' : '展开查看工具步骤'}{summary.provider ? ' · ' + providerLabel(summary.provider) + (summary.model ? ' · ' + summary.model : '') : ''}</small>
      </span>
      <span className={'run-status ' + summary.status}>{summaryStatus(summary)}</span>
    </button>
    {summary.executionState === 'needs_reconciliation' && <div className="trace-warning" role="status">工具执行结果尚未核对。Figura 会保留当前 Run，暂不自动重放该工具。</div>}
    {summary.status === 'failed' && summary.terminalMessage && <div className="trace-warning" role="status">{summary.terminalMessage}</div>}
    {props.expanded && <div className="run-trace figura-tool-timeline" id={'figura-tools-' + summary.runId}>
      {snapshotLoading && <div className="trace-empty">正在加载已提交的工具调用……</div>}
      {snapshotFailed && <div className="trace-empty" role="status">工具时间线暂时无法读取。<button type="button" className="small-action" onClick={() => { setSnapshotFailed(false); setSnapshotRequested(false) }}>重试</button></div>}
      {!snapshotLoading && !snapshotFailed && props.snapshot && steps.length === 0
        ? <div className="trace-empty">当前 Run 还没有已提交的工具调用。</div>
        : steps.map((step) => <ToolStep
          key={step.id}
          step={step}
          loadDetail={props.loadDetail}
          sourceContentUrl={props.sourceContentUrl}
          observationContentUrl={props.observationContentUrl}
          onPreview={props.onPreview}
        />)}
    </div>}
  </section>
}
