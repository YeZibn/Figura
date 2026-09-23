import { AlertTriangle, CheckCircle2, ChevronRight, ClipboardList, LoaderCircle, RefreshCw } from 'lucide-react'
import { formatBytes } from '../attachments'
import { evaluationDetailEntryLabel, evaluationDetailSequenceLabel, evaluationResourceLabel, evaluationStatusClass, evaluationStatusLabel, timestampLabel } from '../domain/display'
import { textDetail } from '../domain/records'
import { generatedArtifacts, timelineProtocolStatus } from '../domain/run/timeline'
import type { EvaluationCaseData, EvaluationDetail, EvaluationDetailEntry, EvaluationHistory, EvaluationHistoryDetails, EvaluationStatus, EvaluationSummary } from '../types/protocol'
import type { PreviewResourceLoader } from '../previewResources'
import type { PreviewOpener } from './types'
import { CopyDetailButton, SafeMarkdown } from './common'
import { GeneratedChartView, ObservationView, PreviewImage } from './preview'
import { RunTimeline } from './run'

function EvaluationDetailEntryView(props: { entry: EvaluationDetailEntry; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const entry = props.entry
  const hasContent = entry.content !== undefined && entry.content !== null && entry.content !== ''
  const hasArguments = entry.arguments !== undefined
  const hasResult = entry.result !== undefined
  const hasDetails = entry.details !== undefined
  return <details className={'evaluation-detail-entry ' + (entry.kind === 'tool_result' ? 'tool-result' : '')} open={entry.kind === 'conversation'}>
    <summary><span className="evaluation-detail-entry-title"><strong>{evaluationDetailEntryLabel(entry)}</strong><small>{entry.timestamp ? timestampLabel(entry.timestamp) : '未知时间'} · {evaluationDetailSequenceLabel(entry)}{entry.callId ? ' · ' + entry.callId : ''}</small></span><span className="evaluation-detail-entry-state">{entry.status || (entry.source === 'record' ? '可见记录' : '事件')}</span></summary>
    <div className="evaluation-detail-entry-body">
      {entry.toolName && <div className="evaluation-detail-meta"><span>工具</span><code>{entry.toolName}</code></div>}
      {entry.role && <div className="evaluation-detail-meta"><span>角色</span><code>{entry.role}</code></div>}
      {hasContent && <div className="evaluation-detail-block"><div className="trace-detail-heading"><label>可见内容</label><CopyDetailButton value={entry.content} /></div><pre>{textDetail(entry.content)}</pre></div>}
      {hasArguments && <div className="evaluation-detail-block"><div className="trace-detail-heading"><label>调用参数</label><CopyDetailButton value={entry.arguments} /></div><pre>{textDetail(entry.arguments)}</pre></div>}
      {hasResult && <div className="evaluation-detail-block"><div className="trace-detail-heading"><label>工具结果</label><CopyDetailButton value={entry.result} /></div><pre>{textDetail(entry.result)}</pre></div>}
      {hasDetails && <div className="evaluation-detail-block"><div className="trace-detail-heading"><label>{entry.kind === 'repair' ? '修复详情' : '事件详情'}</label><CopyDetailButton value={entry.details} /></div><pre>{textDetail(entry.details)}</pre></div>}
      {entry.toolCalls !== undefined && <div className="evaluation-detail-block"><div className="trace-detail-heading"><label>工具调用声明</label><CopyDetailButton value={entry.toolCalls} /></div><pre>{textDetail(entry.toolCalls)}</pre></div>}
      {entry.code && <div className="evaluation-detail-meta"><span>代码</span><code>{entry.code}</code></div>}
      {entry.reason && <div className="evaluation-detail-note">{entry.reason}</div>}
      {entry.truncated && <div className="evaluation-detail-note">该条记录已按安全上限截断，未展示完整原始内容。</div>}
      {entry.redacted && <div className="evaluation-detail-note">该条记录包含已隐藏的敏感字段或二进制内容。</div>}
      {entry.observations?.map((observation, index) => <ObservationView key={entry.entryId + '-observation-' + index} observation={observation as unknown as Record<string, unknown>} loader={props.loader} onPreview={props.onPreview} />)}
      {entry.artifacts?.map((artifact, index) => <GeneratedChartView key={entry.entryId + '-artifact-' + index} artifact={artifact} loader={props.loader} onPreview={props.onPreview} />)}
    </div>
  </details>
}

export function EvaluationHistoryView(props: { history: EvaluationHistory | null; details: EvaluationHistoryDetails | null; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener; evaluationId: string; caseId: string; loading: boolean; detailsLoading: boolean; detailsError: string | null; onLoadDetails: () => void }) {
  if (props.loading) return <div className="evaluation-loading"><LoaderCircle className="spin-icon" size={17} />正在加载运行历史</div>
  if (!props.history) return <div className="evaluation-muted">该 case 暂无可读取的运行历史。</div>
  const supplementalEntries = (props.details?.entries || []).filter((entry) => entry.kind === 'conversation' || entry.kind === 'repair' || entry.kind.startsWith('review') || entry.kind.startsWith('chart_review') || (entry.kind === 'tool_message' && !entry.callId) || entry.kind === 'record')
  const artifacts = generatedArtifacts(props.history.events)
  return <div className="evaluation-history">
    <div className="evaluation-section-heading"><div><span className="eyebrow">只读运行记录</span><h3>完整执行时间线</h3></div><div className="evaluation-history-heading-actions"><code>{props.history.run.runId}</code><button type="button" className="small-action" onClick={props.onLoadDetails} disabled={props.detailsLoading}>{props.detailsLoading ? '正在加载对话记录' : props.details ? '刷新对话记录' : '加载对话与补充记录'}</button></div></div>
    {props.history.historyGap && <div className="evaluation-warning"><AlertTriangle size={14} />历史记录存在缺口，以下仅展示已保留事件。</div>}
    <RunTimeline timeline={{ summary: props.history.run, events: props.history.events, historyGap: props.history.historyGap, integrity: props.history.integrity }} expanded={true} onToggle={() => undefined} previewLoader={props.loader} onPreview={props.onPreview} showSummary={false} evaluationId={props.evaluationId} caseId={props.caseId} />
    {artifacts.length > 0 && <section className="evaluation-detail-records"><div className="evaluation-section-heading"><div><span className="eyebrow">生成结果</span><h3>图表输出</h3></div><span className="detail-count">{artifacts.length} 个</span></div><div className="run-result-artifacts">{artifacts.map((artifact, index) => <GeneratedChartView key={`${props.history?.run.runId}-evaluation-artifact-${artifact.artifactId || index}`} artifact={artifact} loader={props.loader} onPreview={props.onPreview} />)}</div></section>}
    {props.detailsError && <div className="evaluation-warning" role="status"><AlertTriangle size={14} />{props.detailsError}<button type="button" className="small-action" onClick={props.onLoadDetails}>重试</button></div>}
    {props.details && <section className="evaluation-detail-records"><div className="evaluation-section-heading"><div><span className="eyebrow">按需加载</span><h3>对话与补充记录</h3></div><span className="detail-count">{supplementalEntries.length} 条</span></div>{props.details.notice && <div className="evaluation-detail-notice">{props.details.notice}</div>}{props.details.historyGap && <div className="evaluation-warning"><AlertTriangle size={14} />详细记录存在缺口，序号较早的内容可能已被清理。</div>}{supplementalEntries.length ? <div className="evaluation-detail-list">{supplementalEntries.map((entry) => <EvaluationDetailEntryView key={entry.entryId} entry={entry} loader={props.loader} onPreview={props.onPreview} />)}</div> : <div className="evaluation-muted">没有额外对话或补充记录；工具调用和结果已在上方统一时间线中展示。</div>}{props.details.truncated && <div className="evaluation-detail-note">本次补充记录受大小上限保护，部分内容已截断。</div>}</section>}
  </div>
}

export function EvaluationPanel(props: {
  evaluations: EvaluationSummary[]
  detail: EvaluationDetail | null
  caseData: EvaluationCaseData | null
  history: EvaluationHistory | null
  historyDetails: EvaluationHistoryDetails | null
  selectedEvaluationId: string
  selectedCaseId: string
  loading: boolean
  caseLoading: boolean
  historyLoading: boolean
  historyDetailsLoading: boolean
  historyDetailsError: string | null
  error: string | null
  stale: boolean
  onRefresh: () => void
  onSelectCase: (id: string) => void
  onLoadHistoryDetails: () => void
  previewLoader: PreviewResourceLoader | null
  onPreview?: PreviewOpener
}) {
  const summary = props.detail?.evaluation || props.evaluations.find((item) => item.evaluationId === props.selectedEvaluationId)
  const currentCase = props.caseData?.case
  const imageResources = (currentCase?.resources || []).filter((resource) => resource.mediaType.startsWith('image/'))
  const failure = currentCase?.firstFailure || currentCase?.timeline.firstFailure || summary?.firstFailure
  const currentHistoryProtocolStatus = props.history && currentCase?.runId === props.history.run.runId
    ? timelineProtocolStatus(props.history.events).status
    : null
  const diagnosticProtocolStatus = currentHistoryProtocolStatus && currentHistoryProtocolStatus !== 'supported'
    ? currentHistoryProtocolStatus
    : currentCase?.timeline.protocolStatus || 'unavailable'
  return <>
    <main className="conversation panel evaluation-main">
      <header className="conversation-header evaluation-header">
        <div className="conversation-title"><span className="eyebrow">评测工作台 · 只读</span><h1>{summary?.evaluationId || '评测记录'}</h1>{summary && <span className="conversation-meta">{summary.provider || '未知来源'} · {summary.model || '未知模型'} · {summary.caseCount} 个 case</span>}</div>
        <div className="conversation-header-actions"><span className={'run-chip ' + (summary ? evaluationStatusClass(summary.status) : '')}><span className="status-dot" />{summary ? evaluationStatusLabel(summary.status) : '未选择评测'}</span><button type="button" className="icon-button" onClick={props.onRefresh} title="刷新评测" aria-label="刷新评测"><RefreshCw size={15} /></button></div>
      </header>
      <div className="evaluation-scroll">
        {props.stale && <div className="evaluation-warning" role="status"><AlertTriangle size={14} />评测数据暂时不可刷新，当前显示最近一次成功快照。<button type="button" className="small-action" onClick={props.onRefresh}>重试</button></div>}
        {props.loading && !props.detail && <div className="evaluation-loading"><LoaderCircle className="spin-icon" size={18} />正在加载评测详情</div>}
        {!props.loading && !summary && <div className="empty-conversation"><div className="empty-icon"><ClipboardList size={22} /></div><h2>还没有评测记录</h2><p>完成一次真实评测后，批次会出现在这里。</p><button type="button" className="dialog-primary" onClick={props.onRefresh}>刷新评测</button></div>}
        {props.error && !props.detail && <div className="error-state"><div className="empty-icon"><ClipboardList size={22} /></div><h2>评测记录不可用</h2><p>{props.error}</p><button type="button" className="dialog-primary" onClick={props.onRefresh}>重试</button></div>}
        {summary && <>
          <section className="evaluation-overview">
            <div className="evaluation-overview-card"><span>开始时间</span><strong>{summary.startedAt || '—'}</strong></div>
            <div className="evaluation-overview-card"><span>结束时间</span><strong>{summary.endedAt || '尚未结束'}</strong></div>
            <div className="evaluation-overview-card"><span>Case 状态</span><strong>{Object.entries(summary.caseCounts).map(([key, value]) => `${key}: ${value}`).join(' · ') || '—'}</strong></div>
          </section>
          {props.caseLoading && <div className="evaluation-loading"><LoaderCircle className="spin-icon" size={16} />正在加载 case 诊断</div>}
          {currentCase && <>
            <section className="evaluation-case-heading"><div><span className="eyebrow">当前 case</span><h2>{currentCase.caseId}</h2></div><span className={'run-status ' + evaluationStatusClass(currentCase.status as EvaluationStatus)}>{currentCase.status}</span></section>
            <div className="evaluation-reference-row"><span>输入：{currentCase.asset || '未记录'}</span>{currentCase.runId && <code>run: {currentCase.runId}</code>}{currentCase.sha256 && <code>sha256: {currentCase.sha256.slice(0, 16)}…</code>}</div>
            {failure && <div className="evaluation-failure"><AlertTriangle size={15} /><div><strong>第一个可确认失败</strong><span>{failure.category || '未知类别'} / {failure.stage || '未知阶段'} · {failure.message || '未提供原因'}</span></div></div>}
            {currentCase.error && <div className="evaluation-failure"><AlertTriangle size={15} /><div><strong>{currentCase.error.code || 'case 错误'}</strong><span>{currentCase.error.message || '评测 case 不可用'}</span></div></div>}
            <section className="evaluation-section"><div className="evaluation-section-heading"><div><span className="eyebrow">阶段诊断</span><h3>链路状态</h3></div>{currentCase.timeline.historyGap && <span className="run-status interrupted">历史不完整</span>}</div>{diagnosticProtocolStatus !== 'supported' && <div className="evaluation-warning" role="status">{diagnosticProtocolStatus === 'unsupported_version' ? '该评测的运行事件来自旧版或当前不支持的时间线协议；Case 摘要、原始安全记录与产物仍保留，阶段诊断不可用。' : diagnosticProtocolStatus === 'malformed' ? '该评测包含不符合当前时间线协议的事件；为避免误报，阶段诊断不可用。' : '该评测没有可验证的时间线协议标记；为避免把旧诊断当作当前状态，阶段诊断不可用。'}</div>}<div className="evaluation-stage-list">{diagnosticProtocolStatus === 'supported' && currentCase.timeline.stages.length ? currentCase.timeline.stages.map((stage) => <div className="evaluation-stage" key={stage.name}><span className={'evaluation-stage-dot ' + (stage.status === 'completed' ? 'success' : stage.status === 'failed' ? 'error' : '')}>{stage.status === 'completed' ? <CheckCircle2 size={13} /> : <span />}</span><div><strong>{stage.name}</strong><small>{stage.status}{stage.sequences.length ? ` · 事件 ${stage.sequences.join(', ')}` : ''}{stage.errors.length ? ` · ${stage.errors.join('；')}` : ''}</small></div></div>) : diagnosticProtocolStatus === 'supported' ? <div className="evaluation-muted">暂无阶段诊断。</div> : null}</div></section>
            <section className="evaluation-section"><div className="evaluation-section-heading"><div><span className="eyebrow">报告</span><h3>{currentCase.report.available ? '评测报告' : '标准诊断摘要'}</h3></div>{currentCase.report.truncated && <span className="run-status interrupted">已截断</span>}</div>{currentCase.report.text ? <SafeMarkdown source={currentCase.report.text} /> : <div className="evaluation-muted">没有自定义 Markdown 报告，当前展示上方的标准摘要与阶段证据。</div>}</section>
            <section className="evaluation-section"><div className="evaluation-section-heading"><div><span className="eyebrow">证据画廊</span><h3>图片证据</h3></div><span className="detail-count">{imageResources.length} 张</span></div>{imageResources.length ? <div className="evaluation-evidence-grid">{imageResources.map((resource) => <div className="evaluation-evidence-card" key={resource.resourceId}><PreviewImage loader={props.previewLoader} resource={resource.previewResource} alt={resource.label} title={resource.label} sourceLabel={evaluationResourceLabel(resource)} onPreview={props.onPreview} /><strong>{evaluationResourceLabel(resource)}</strong><small>{resource.label} · {formatBytes(resource.byteCount)}</small></div>)}</div> : <div className="evaluation-muted">当前 case 没有可预览的图片证据。</div>}</section>
            <EvaluationHistoryView history={props.history} details={props.historyDetails} loader={props.previewLoader} onPreview={props.onPreview} evaluationId={props.selectedEvaluationId} caseId={currentCase.caseId} loading={props.historyLoading} detailsLoading={props.historyDetailsLoading} detailsError={props.historyDetailsError} onLoadDetails={props.onLoadHistoryDetails} />
          </>}
        </>}
        {props.error && props.detail && <div className="evaluation-warning" role="status"><AlertTriangle size={14} />{props.error}</div>}
      </div>
    </main>
    <aside className="right-panel panel evaluation-case-panel"><div className="panel-heading"><div><span className="eyebrow">评测批次</span><h2>Cases</h2></div><span className="detail-count">{props.detail?.cases.length || 0}</span></div>{props.detail?.cases.length ? <div className="evaluation-case-list">{props.detail.cases.map((item) => <button type="button" className={'evaluation-case-item ' + (item.caseId === props.selectedCaseId ? 'selected' : '')} key={item.caseId} onClick={() => props.onSelectCase(item.caseId)}><span className={'status-dot ' + evaluationStatusClass(item.status as EvaluationStatus)} /><span><strong>{item.caseId}</strong><small>{item.status}{item.firstFailure?.stage ? ` · ${item.firstFailure.stage}` : ''}</small></span><ChevronRight size={14} /></button>)}</div> : <div className="empty-attachments"><ClipboardList size={19} /><span>暂无可读 case</span><small>评测批次尚未写入完整索引。</small></div>}<div className="details-divider" /><div className="panel-heading compact"><h2>数据边界</h2></div><p className="details-note">此处只读评测 bundle，不会改变普通会话、运行或附件。</p></aside>
  </>
}
