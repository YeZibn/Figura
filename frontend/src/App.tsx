import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { BarChart3, Check, ChevronDown, ChevronRight, Download, FileImage, LoaderCircle, MessageSquare, Paperclip, Plus, RefreshCw, Send, Sparkles, Terminal, Trash2, X } from 'lucide-react'
import { GatewayClientError, gatewayClient } from './api/gatewayClient'
import type { ChartAgentClient, RunSubscription } from './api/client'
import { mockClient } from './api/mockClient'
import { formatBytes, mediaTypeForFile, validateImageFile } from './attachments'
import { getGatewayRuntimeStatus, type GatewayRuntimeStatus } from './runtime'
import type { AgentRunEvent, Attachment, AttachmentStatus, ConversationItem, GatewayHealth, GeneratedChartReference, RunState, RunSummary, Session, SessionData } from './types/protocol'
import './styles/global.css'
import './styles/error.css'

type PendingAttachment = {
  key: string
  file: File
  previewUrl: string
  status: 'uploading' | 'error'
  error?: string
}

type ConfirmAction =
  | { kind: 'session'; session: Session }
  | { kind: 'attachment'; attachment: Attachment }

function statusLabel(status: AttachmentStatus): string {
  if (status === 'uploading') return '正在上传'
  if (status === 'registered') return '已登记'
  if (status === 'unavailable') return '源文件不可用'
  if (status === 'loaded') return '已加载到模型'
  if (status === 'observation') return '已有视觉观察'
  if (status === 'error') return '上传失败'
  return '待处理'
}

function toolStatusLabel(status: 'success' | 'running' | 'error'): string {
  if (status === 'success') return '完成'
  if (status === 'running') return '运行中'
  return '失败'
}

function runStateLabel(state: RunState): string {
  if (state === 'connecting') return '正在连接'
  if (state === 'running') return '运行中'
  if (state === 'completed') return '已完成'
  if (state === 'failed') return '运行失败'
  if (state === 'interrupted') return '已中断'
  if (state === 'unavailable') return '服务不可用'
  return '准备就绪'
}

function currentTime(): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function eventPayload(event: AgentRunEvent): Record<string, unknown> {
  return event.payload || {}
}

function textDetail(value: unknown): string {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return '事件内容不可显示' }
}

type RunTimeline = {
  summary: RunSummary
  events: AgentRunEvent[]
  historyGap: boolean
}

type ToolStep = {
  id: string
  callId: string
  toolName: string
  call?: AgentRunEvent
  result?: AgentRunEvent
  observations: Record<string, unknown>[]
  status: 'running' | 'success' | 'error'
}

type TimelineRow = { kind: 'event'; event: AgentRunEvent } | { kind: 'tool'; step: ToolStep }

function timestampLabel(timestamp: string): string {
  if (!timestamp) return currentTime()
  const parsed = new Date(timestamp)
  return Number.isNaN(parsed.valueOf()) ? timestamp : parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function normalizeTimeline(events: AgentRunEvent[]): TimelineRow[] {
  const rows: TimelineRow[] = []
  const steps = new Map<string, ToolStep>()
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    const payload = eventPayload(event)
    if (event.kind === 'tool_call' || event.kind === 'tool_result') {
      const callId = typeof payload.call_id === 'string' && payload.call_id ? payload.call_id : `sequence-${event.sequence}`
      let step = steps.get(callId)
      if (!step) {
        step = { id: `${event.runId}-${callId}`, callId, toolName: String(payload.tool_name || '未知工具'), observations: [], status: 'running' }
        steps.set(callId, step)
        rows.push({ kind: 'tool', step })
      }
      step.toolName = String(payload.tool_name || step.toolName)
      if (event.kind === 'tool_call') step.call = event
      else { step.result = event; step.status = payload.status === 'error' ? 'error' : 'success' }
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

function generatedArtifacts(events: AgentRunEvent[]): GeneratedChartReference[] {
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

function mergeEvents(current: AgentRunEvent[], incoming: AgentRunEvent[]): AgentRunEvent[] {
  const bySequence = new Map(current.map((event) => [event.sequence, event]))
  incoming.forEach((event) => bySequence.set(event.sequence, event))
  return [...bySequence.values()].sort((left, right) => left.sequence - right.sequence)
}

function isSafeLink(value: string): boolean {
  return /^(https?:\/\/|mailto:)/i.test(value)
}

function inlineMarkdown(value: string, keyPrefix: string): ReactNode[] {
  const parts = value.split(/(\[[^\]]+\]\([^\)]+\)|\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_)/g).filter(Boolean)
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`
    const link = part.match(/^\[([^\]]+)\]\(([^\)]+)\)$/)
    if (link) return isSafeLink(link[2]) ? <a key={key} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a> : <span key={key}>{link[1]}</span>
    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) return <strong key={key}>{part.slice(2, -2)}</strong>
    if ((part.startsWith('*') && part.endsWith('*')) || (part.startsWith('_') && part.endsWith('_'))) return <em key={key}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={key}>{part.slice(1, -1)}</code>
    return <span key={key}>{part}</span>
  })
}

function SafeMarkdown({ source }: { source: string }) {
  const text = source.slice(0, 12000)
  const lines = text.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (line.startsWith('```')) {
      const language = line.slice(3).trim()
      const code: string[] = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) { code.push(lines[index]); index += 1 }
      blocks.push(<pre className="markdown-code" key={`code-${index}`}><code data-language={language || undefined}>{code.join('\n')}</code></pre>)
      index += 1
      continue
    }
    if (!line.trim()) { index += 1; continue }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) { const Tag = `h${heading[1].length}` as 'h1' | 'h2' | 'h3'; blocks.push(<Tag key={`heading-${index}`}>{inlineMarkdown(heading[2], `heading-${index}`)}</Tag>); index += 1; continue }
    if (/^\|.*\|$/.test(line) && index + 1 < lines.length && /^\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const rows: string[][] = []
      while (index < lines.length && /^\|.*\|$/.test(lines[index]) && !/^\|?\s*:?-{3,}/.test(lines[index])) {
        rows.push(lines[index].replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim())); index += 1
        if (index < lines.length && /^\|?\s*:?-{3,}/.test(lines[index])) index += 1
      }
      blocks.push(<table className="markdown-table" key={`table-${index}`}><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => rowIndex === 0 ? <th key={cellIndex}>{inlineMarkdown(cell, `table-${index}-${rowIndex}-${cellIndex}`)}</th> : <td key={cellIndex}>{inlineMarkdown(cell, `table-${index}-${rowIndex}-${cellIndex}`)}</td>)}</tr>)}</tbody></table>)
      continue
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line)
      const items: string[] = []
      while (index < lines.length && (ordered ? /^\s*\d+\.\s+/.test(lines[index]) : /^\s*[-*]\s+/.test(lines[index]))) items.push(lines[index].replace(ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/, '')), index += 1
      const List = ordered ? 'ol' : 'ul'
      blocks.push(<List key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item, `list-${index}-${itemIndex}`)}</li>)}</List>)
      continue
    }
    const paragraph: string[] = [line]
    index += 1
    while (index < lines.length && lines[index].trim() && !lines[index].startsWith('```') && !/^(#{1,3})\s+/.test(lines[index])) { paragraph.push(lines[index]); index += 1 }
    blocks.push(<p key={`paragraph-${index}`}>{paragraph.map((part, partIndex) => <span key={partIndex}>{partIndex > 0 && <br />}{inlineMarkdown(part, `paragraph-${index}-${partIndex}`)}</span>)}</p>)
  }
  return <div className="markdown-content">{blocks}</div>
}

function ObservationView({ observation }: { observation: Record<string, unknown> }) {
  const imageUrl = typeof observation.imageUrl === 'string' ? observation.imageUrl : ''
  const caption = String(observation.caption || '视觉观察')
  return <div className="trace-observation"><div className="observation-label"><FileImage size={13} /><strong>视觉观察</strong></div>{imageUrl ? <img src={imageUrl} alt={caption} /> : <div className="observation-placeholder">视觉证据不可用或已过期</div>}<small>{caption}</small></div>
}

function chartTypeLabel(value: string): string {
  return ({ bar: '柱状图', line: '折线图', pie: '饼图', scatter: '散点图' } as Record<string, string>)[value] || value || '图表'
}

function GeneratedChartView({ artifact }: { artifact: GeneratedChartReference }) {
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const [imageFailed, setImageFailed] = useState(false)
  useEffect(() => setImageFailed(false), [artifact.imageUrl])
  const status = artifact.status === 'failed' ? 'failed' : artifact.status === 'pending' ? 'pending' : artifact.status === 'warning' ? 'warning' : artifact.status === 'unavailable' || !artifact.imageUrl || imageFailed ? 'unavailable' : 'available'
  const statusLabel = status === 'available' ? '已验证' : status === 'warning' ? '已发布·有警告' : status === 'pending' ? '审核中' : status === 'failed' ? '审核未通过' : '暂不可用'
  const metadata = [
    artifact.chartType ? chartTypeLabel(artifact.chartType) : '',
    artifact.width && artifact.height ? `${artifact.width} × ${artifact.height}` : '',
    typeof artifact.byteCount === 'number' ? formatBytes(artifact.byteCount) : '',
  ].filter(Boolean).join(' · ')
  const download = async () => {
    if (!artifact.downloadUrl || downloading) return
    setDownloading(true)
    setDownloadError('')
    try {
      const response = await fetch(artifact.downloadUrl)
      if (!response.ok) throw new Error('download failed')
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = `${artifact.title || 'figura-chart'}.png`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
    } catch {
      setDownloadError('下载失败，请稍后重试')
    } finally {
      setDownloading(false)
    }
  }
  return <article className={'generated-chart ' + status}>
    <div className="generated-chart-heading"><div className="observation-label"><BarChart3 size={13} /><strong>生成图表</strong><span>{statusLabel}</span></div>{artifact.downloadUrl && (status === 'available' || status === 'warning') && <button className="chart-download" type="button" onClick={() => void download()} disabled={downloading} title="下载生成图表"><Download size={13} />{downloading ? '正在下载' : '下载 PNG'}</button>}</div>
    {artifact.imageUrl && (status === 'available' || status === 'warning' || status === 'pending') ? <img src={artifact.imageUrl} alt={artifact.title || artifact.caption || '生成图表'} onError={() => setImageFailed(true)} /> : <div className="observation-placeholder">{status === 'failed' ? '图表审核未通过，未产生可下载文件' : '图表文件已过期或暂不可用'}</div>}
    <div className="generated-chart-copy"><strong>{artifact.title || artifact.caption || '未命名图表'}</strong>{metadata && <small>{metadata}</small>}{artifact.reason && <small className="generated-chart-reason">{artifact.reason}</small>}{downloadError && <small className="generated-chart-reason">{downloadError}</small>}</div>
  </article>
}

function eventLabel(event: AgentRunEvent): string {
  const labels: Record<string, string> = { run_started: '运行已开始', model_started: '模型轮次开始', model_completed: '模型轮次完成', progress: '处理中', generated_chart: '图表状态已更新', chart_review_required: '等待图表审核', generated_chart_published: '图表已发布', chart_review_completed: '图表审核完成', final_answer: '最终回答已生成', budget_exhausted: '达到预算上限', run_failed: '运行失败', history_gap: '历史记录不完整' }
  return labels[event.kind] || event.kind
}

function RunTimeline({ timeline, expanded, onToggle }: { timeline: RunTimeline; expanded: boolean; onToggle: () => void }) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const rows = normalizeTimeline(timeline.events)
  const summary = timeline.summary
  const status = summary.status
  const statusText = status === 'completed' ? '已完成' : status === 'failed' ? '失败' : status === 'interrupted' ? '已中断' : '运行中'
  return <section className={'run-timeline ' + status + (expanded ? ' expanded' : '')}>
    <button className="run-summary" onClick={onToggle} aria-expanded={expanded} aria-controls={`trace-${summary.runId}`}><span className="run-arrow">{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span><span className="run-summary-icon"><Terminal size={14} /></span><span className="run-summary-copy"><strong>执行过程</strong><small>{timestampLabel(summary.createdAt)} · {summary.eventCount || timeline.events.length} 个事件</small></span><span className={'run-status ' + status}>{statusText}</span></button>
    {expanded && <div className="run-trace" id={`trace-${summary.runId}`}>
      {summary.historyWarning && <div className="trace-warning" role="status">部分执行记录未能持久化，当前显示的过程可能不完整。</div>}
      {timeline.historyGap && <div className="trace-warning" role="status">历史记录存在缺口，未显示缺失的执行步骤。</div>}
      {rows.length === 0 && <div className="trace-empty">没有可恢复的执行事件。</div>}
      {rows.map((row) => row.kind === 'event' ? <div className={'trace-event ' + (row.event.kind === 'run_failed' || row.event.kind === 'history_gap' ? 'error' : '')} key={`${row.event.runId}-${row.event.sequence}`}><span className="trace-event-dot" /><span className="trace-event-copy"><strong>{eventLabel(row.event)}</strong><small>{timestampLabel(row.event.timestamp)}</small><span>{textDetail(eventPayload(row.event).message || eventPayload(row.event).status || eventPayload(row.event).reason || (row.event.kind === 'generated_chart' ? '生成图表结果已移至最终结果区域' : ''))}</span></span></div> : <div className="trace-tool" key={row.step.id}><button className="trace-tool-header" onClick={() => setExpandedSteps((current) => { const next = new Set(current); next.has(row.step.id) ? next.delete(row.step.id) : next.add(row.step.id); return next })} aria-expanded={expandedSteps.has(row.step.id)}><span className="trace-event-dot" /><span className="trace-tool-name"><strong>{row.step.toolName}</strong><small>{row.step.callId}</small></span><span className={'run-status ' + row.step.status}>{row.step.status === 'running' ? '运行中' : row.step.status === 'success' ? '完成' : '失败'}</span>{expandedSteps.has(row.step.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>{expandedSteps.has(row.step.id) && <div className="trace-tool-detail">{row.step.call && <div><label>调用参数</label><pre>{textDetail(eventPayload(row.step.call).arguments)}</pre></div>}{row.step.result && <div><label>工具结果</label><pre>{textDetail(eventPayload(row.step.result).result || eventPayload(row.step.result).message)}</pre></div>}{row.step.observations.map((observation, index) => <ObservationView key={index} observation={observation} />)}</div>}</div>)}
    </div>}
  </section>
}

function gatewayStatusText(mode: 'mock' | 'gateway', runtimeStatus: GatewayRuntimeStatus | null, health: GatewayHealth | null): string {
  if (mode === 'mock') return '可离线使用'
  if (runtimeStatus?.state === 'unavailable') return '本地服务不可用'
  const agentState = runtimeStatus?.agentState || health?.agent?.status
  if (agentState === 'unavailable') return 'Agent 配置不可用'
  if (agentState === 'ready') return 'Agent 已就绪'
  if (agentState === 'starting') return 'Agent 正在启动'
  if (runtimeStatus?.state === 'ready') return '本地服务已就绪'
  return '本地服务连接中'
}

function SessionSidebar(props: { sessions: Session[]; activeId: string; onSelect: (id: string) => void; onCreate: () => void; onDelete: (id: string) => void; mode: 'mock' | 'gateway'; runtimeStatus: GatewayRuntimeStatus | null; health: GatewayHealth | null }) {
  const statusUnavailable = props.runtimeStatus?.state === 'unavailable' || props.runtimeStatus?.agentState === 'unavailable' || props.health?.agent?.status === 'unavailable'
  return <aside className="sidebar panel">
    <div className="brand"><div className="brand-mark"><BarChart3 size={19} /></div><div><strong>Figura</strong><span>图表分析工作台</span></div></div>
    <div className="section-heading"><div><span className="eyebrow">工作区</span><strong>会话</strong></div><button className="icon-button" onClick={props.onCreate} title="新建会话" aria-label="新建会话"><Plus size={16} /></button></div>
    <div className="session-list">{props.sessions.length ? props.sessions.map((session) => <div key={session.id} className={'session-item ' + (session.id === props.activeId ? 'selected' : '')}><button className="session-select" onClick={() => props.onSelect(session.id)} aria-current={session.id === props.activeId ? 'page' : undefined}><span className="session-dot" /><span className="session-copy"><strong>{session.name}</strong><small>{session.updatedAt}</small></span><span className="session-count">{session.runCount}</span></button><button className="session-more" onClick={() => props.onDelete(session.id)} title={`删除会话：${session.name}`} aria-label={`删除会话：${session.name}`}><Trash2 size={14} /></button></div>) : <div className="session-empty"><MessageSquare size={16} /><span>还没有会话</span><small>新建一个会话开始分析。</small></div>}</div>
    <div className="sidebar-footer"><span className={'status-dot ' + (statusUnavailable ? 'status-error' : '')} />{props.mode === 'gateway' ? 'Gateway 模式' : '模拟模式'} <span className="muted">·</span> {gatewayStatusText(props.mode, props.runtimeStatus, props.health)}</div>
  </aside>
}

function Message(props: { item: ConversationItem; expanded: boolean; onToggle: (id: string) => void }) {
  const item = props.item
  const associationWarning = (item.kind === 'user' || item.kind === 'assistant') && item.associationStatus === 'legacy_unassociated' ? <span className="message-association-warning">历史关联不完整</span> : null
  if (item.kind === 'user') return <div className="message-row user-row"><div className="avatar user-avatar">我</div><div className="message-body"><div className="message-meta"><strong>你</strong>{associationWarning}<time>{item.timestamp}</time></div><div className="bubble user-bubble">{item.text}{item.attachmentIds?.length ? <div className="inline-attachment"><Paperclip size={13} /> {item.attachmentIds.length} 个附件</div> : null}</div></div></div>
  if (item.kind === 'assistant') return <div className="message-row assistant-row"><div className="avatar agent-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-meta"><strong>Figura Agent</strong>{associationWarning}<time>{item.timestamp}</time></div><div className="bubble assistant-bubble"><SafeMarkdown source={item.text} /><details className="answer-source"><summary>查看原文</summary><pre>{item.text.slice(0, 12000)}</pre></details></div></div></div>
  if (item.kind === 'visual_observation') return <div className="visual-observation"><div className="observation-label"><FileImage size={14} /> <strong>视觉观察</strong><span>{item.toolName}</span></div>{item.imageUrl ? <img src={item.imageUrl} alt={item.caption} /> : <div className="observation-placeholder">临时视觉证据不可用</div>}<small>{item.caption}</small></div>
  if (item.kind === 'error') return <div className="error-banner" role="alert">{item.text}</div>
  const label = item.kind === 'tool_call' ? '工具调用' : '工具结果'
  return <div className={'execution-item ' + (props.expanded ? 'expanded' : '')}><button className="execution-header" onClick={() => props.onToggle(item.id)} aria-expanded={props.expanded}><span className="execution-icon"><Terminal size={14} /></span><span><strong>{label}</strong><b>{item.toolName}</b></span><span className={'execution-status ' + item.status}>{toolStatusLabel(item.status)}</span>{props.expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>{props.expanded && <div className="execution-detail">{item.detail}</div>}</div>
}

function RunBlock(props: {
  timeline: RunTimeline
  user?: ConversationItem
  assistant?: ConversationItem
  expanded: boolean
  onToggleRun: () => void
  expandedMessage: string | null
  onToggleMessage: (id: string) => void
}) {
  const { timeline, user, assistant } = props
  const answer = assistant?.kind === 'assistant' ? assistant.text : timeline.summary.answer || ''
  const answerTimestamp = assistant?.kind === 'assistant' ? assistant.timestamp : timestampLabel(timeline.summary.updatedAt)
  const artifacts = generatedArtifacts(timeline.events)
  return <section className={'run-block run-' + timeline.summary.status}>
    {user && <Message item={user} expanded={props.expandedMessage === user.id} onToggle={props.onToggleMessage} />}
    <RunTimeline timeline={timeline} expanded={props.expanded} onToggle={props.onToggleRun} />
    {(answer || artifacts.length > 0) && <section className="run-result" aria-label="最终结果">
      <div className="run-result-heading"><Sparkles size={14} /><strong>最终结果</strong><span>{answer ? answerTimestamp : '图表输出'}</span></div>
      {answer && <Message item={{ id: `${timeline.summary.runId}:assistant`, kind: 'assistant', text: answer, timestamp: answerTimestamp }} expanded={props.expandedMessage === `${timeline.summary.runId}:assistant`} onToggle={props.onToggleMessage} />}
      {artifacts.length > 0 && <div className="run-result-artifacts">{artifacts.map((artifact, index) => <GeneratedChartView key={`${timeline.summary.runId}-artifact-${artifact.artifactId || index}`} artifact={artifact} />)}</div>}
    </section>}
  </section>
}

function ConversationPanel(props: { data: SessionData | null; timelines: RunTimeline[]; pendingUser: ConversationItem | null; runState: RunState; selectedAttachmentIds: string[]; onSubmit: (text: string, attachmentIds: string[]) => Promise<boolean>; loading: boolean; loadingSession: boolean; error: string | null; onToggleRun: (runId: string, status: RunSummary['status']) => void; expandedRuns: Set<string> }) {
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const messages = [...(props.data?.messages ?? []), ...(props.pendingUser ? [props.pendingUser] : [])]
  const linkedMessageIds = new Set<string>()
  const send = async () => {
    const value = text.trim()
    if (!value || props.loading) return
    const submitted = await props.onSubmit(value, props.selectedAttachmentIds)
    if (submitted) setText('')
  }
  const sortedTimelines = [...props.timelines].sort((left, right) => left.summary.createdAt.localeCompare(right.summary.createdAt))
  const runBlocks = sortedTimelines.map((timeline) => {
    const user = messages.find((item) => item.id === `${timeline.summary.runId}:user`)
    const assistant = messages.find((item) => item.id === `${timeline.summary.runId}:assistant`)
    if (user) linkedMessageIds.add(user.id)
    if (assistant) linkedMessageIds.add(assistant.id)
    return { timeline, user, assistant }
  })
  const orphanMessages = messages.filter((item) => !linkedMessageIds.has(item.id))
  const toggleMessage = (id: string) => setExpanded((current) => current === id ? null : id)
  return <main className="conversation panel"><header className="conversation-header"><div className="conversation-title"><span className="eyebrow">当前会话</span><h1>{props.data?.session.name ?? (props.loadingSession ? '正在加载会话' : '暂无活动会话')}</h1>{props.data && <span className="conversation-meta">{props.data.session.runCount} 次运行 · 执行记录保存在本机</span>}</div><span className={'run-chip ' + props.runState}><span className="status-dot" />{runStateLabel(props.runState)} · {props.data?.session.runCount ?? 0} 次运行</span></header><div className="message-scroll">{props.loadingSession ? <div className="loading-state"><span className="spinner" />正在加载会话...</div> : props.error && !props.data && messages.length === 0 ? <div className="error-state"><div className="empty-icon"><MessageSquare size={22} /></div><h2>无法连接本地服务</h2><p>{props.error}</p></div> : !props.data && messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>创建第一个会话</h2><p>请从左侧新建会话，开始使用 Figura。</p></div> : messages.length === 0 && props.timelines.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>开始新的分析</h2><p>提出问题或添加图片，开始使用 Figura。</p></div> : <>{runBlocks.map(({ timeline, user, assistant }) => <RunBlock key={timeline.summary.runId} timeline={timeline} user={user} assistant={assistant} expanded={props.expandedRuns.has(timeline.summary.runId) || timeline.summary.status === 'running'} onToggleRun={() => props.onToggleRun(timeline.summary.runId, timeline.summary.status)} expandedMessage={expanded} onToggleMessage={toggleMessage} />)}{orphanMessages.map((item) => <Message key={item.id} item={item} expanded={expanded === item.id} onToggle={toggleMessage} />)}</>}{props.loading && <div className="typing"><span /><span /><span /> Figura Agent 正在思考</div>}{props.error && <div className="error-banner" role="alert">{props.error}</div>}</div><div className="composer"><div className="composer-label"><Sparkles size={13} /><span>向 Figura Agent 提问</span></div><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder="例如：比较这张图中各系列的变化趋势..." rows={1} /><div className="composer-actions"><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" onClick={() => void send()} disabled={!text.trim() || props.loading || props.loadingSession} title="发送消息" aria-label="发送消息"><Send size={16} /></button></div></div></main>
}

function AttachmentPreview({ attachment }: { attachment: Attachment }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [attachment.previewUrl])
  return attachment.previewUrl && !failed ? <img src={attachment.previewUrl} alt={attachment.filename} onError={() => setFailed(true)} /> : <div className="attachment-placeholder"><FileImage size={24} /><span>{attachment.status === 'unavailable' || failed ? '源文件不可用' : '暂无预览'}</span></div>
}

function AttachmentPanel(props: { attachments: Attachment[]; pending: PendingAttachment[]; selectedIds: string[]; error: string | null; onAdd: (files: File[]) => void; onToggle: (id: string) => void; onRemovePending: (key: string) => void; onRetryPending: (item: PendingAttachment) => void; onRemove: (attachment: Attachment) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  return <aside className="right-panel panel"><div className="panel-heading"><div><span className="eyebrow">会话数据</span><h2>附件</h2></div><button className="attachment-add" onClick={() => inputRef.current?.click()} title="添加图片"><Plus size={14} />添加图片</button><input ref={inputRef} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple onChange={(event) => { props.onAdd(Array.from(event.currentTarget.files ?? [])); event.currentTarget.value = '' }} /></div>{props.error && <div className="attachment-error" role="alert">{props.error}</div>}{props.pending.length === 0 && props.attachments.length === 0 ? <div className="empty-attachments"><Paperclip size={19} /><span>暂无附件</span><small>选择图片后会显示在这里。</small></div> : <div className="attachment-list">{props.pending.map((item) => <div className="attachment-card pending-card" key={item.key}><img src={item.previewUrl} alt={item.file.name} /><div className="attachment-info"><strong>{item.file.name}</strong><span>{mediaTypeForFile(item.file).replace('image/', '').toUpperCase()} · {formatBytes(item.file.size)}</span><div className={'attachment-status ' + (item.status === 'error' ? 'error' : '')}>{item.status === 'uploading' ? <><LoaderCircle className="spin-icon" size={12} />正在上传</> : <><X size={12} />{item.error || '上传失败'}</>}</div><div className="attachment-actions">{item.status === 'error' && <button className="small-action" onClick={() => props.onRetryPending(item)} title="重新上传"><RefreshCw size={12} />重试</button>}<button className="small-action" onClick={() => props.onRemovePending(item.key)} title="移除待处理附件"><X size={12} />移除</button></div></div></div>)}{props.attachments.map((attachment) => { const selectable = attachment.status !== 'unavailable'; const selected = props.selectedIds.includes(attachment.id); return <div className={'attachment-card ' + (selected ? 'selected' : '')} key={attachment.id}><AttachmentPreview attachment={attachment} /><div className="attachment-info"><strong>{attachment.filename}</strong><span>{attachment.mediaType.replace('image/', '').toUpperCase()} · {formatBytes(attachment.byteCount)}</span><div className={'attachment-status ' + (attachment.status === 'unavailable' ? 'error' : '')}><span className="status-dot" />{statusLabel(attachment.status)}{attachment.previewUrl && <em>可预览</em>}</div>{selectable && <label className="attachment-select"><input type="checkbox" checked={selected} onChange={() => props.onToggle(attachment.id)} />附加到下一条消息{selected && <Check size={12} />}</label>}<div className="attachment-actions"><button className="small-action danger-action" onClick={() => props.onRemove(attachment)} title="删除附件"><Trash2 size={12} />删除</button></div></div></div> })}</div>}<div className="details-divider" /><div className="panel-heading compact"><h2>执行详情</h2><span className="detail-count">{props.attachments.length ? `${props.attachments.length} 个附件` : '—'}</span></div><p className="details-note">工具活动和视觉观察会在后续运行中显示。</p></aside>
}

export default function App() {
  const mode = import.meta.env.VITE_CHARTAGENT_MODE === 'gateway' ? 'gateway' : 'mock'
  const client: ChartAgentClient = mode === 'gateway' ? gatewayClient : mockClient
  const [runtimeStatus, setRuntimeStatus] = useState<GatewayRuntimeStatus | null>(null)
  const [gatewayHealth, setGatewayHealth] = useState<GatewayHealth | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [data, setData] = useState<SessionData | null>(null)
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [timelines, setTimelines] = useState<RunTimeline[]>([])
  const [pendingUser, setPendingUser] = useState<ConversationItem | null>(null)
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set())
  const [runState, setRunState] = useState<RunState>('idle')
  const [loading, setLoading] = useState(false)
  const [loadingSession, setLoadingSession] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)
  const [newSessionName, setNewSessionName] = useState('')
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null)
  const [deleting, setDeleting] = useState(false)
  const activeIdRef = useRef(activeId)
  const localPreviews = useRef(new Map<string, string>())
  const subscriptionRef = useRef<RunSubscription | null>(null)

  useEffect(() => { activeIdRef.current = activeId }, [activeId])
  useEffect(() => () => { subscriptionRef.current?.close(); localPreviews.current.forEach((url) => URL.revokeObjectURL(url)); localPreviews.current.clear() }, [])
  useEffect(() => {
    if (mode !== 'gateway') return
    let current = true
    void getGatewayRuntimeStatus().then((status) => { if (current) setRuntimeStatus(status) })
    void gatewayClient.getHealth().then((health) => {
      if (!current) return
      setGatewayHealth(health)
      if (health.agent?.status === 'unavailable') {
        setError(toUserMessage(new GatewayClientError('agent_unavailable', 'Agent service is unavailable', 503, health.agent.reason)))
      }
    }).catch((reason) => { if (current) setError(toUserMessage(reason)) })
    return () => { current = false }
  }, [mode])

  const withLocalPreviews = (value: SessionData): SessionData => ({ ...value, attachments: value.attachments.map((attachment) => ({ ...attachment, previewUrl: attachment.previewUrl || localPreviews.current.get(attachment.id) || '' })) })

  useEffect(() => { setLoadingSession(true); client.listSessions().then((items) => { setSessions(items); setActiveId(items[0]?.id ?? '') }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false)) }, [client])
  useEffect(() => {
    if (!activeId) { setData(null); setTimelines([]); return }
    setData(null)
    setTimelines([])
    setLoadingSession(true)
    void client.getSession(activeId).then(async (value) => {
      if (activeIdRef.current !== activeId) return
      setData(withLocalPreviews(value))
      const hydrated = await Promise.all(value.runs.map(async (summary) => {
        try {
          const history = await client.getRunHistory(activeId, summary.runId)
          return { summary: history.run, events: history.events, historyGap: history.historyGap }
        } catch {
          return { summary, events: [], historyGap: true }
        }
      }))
      if (activeIdRef.current === activeId) {
        setTimelines(hydrated)
        const current = hydrated.find((item) => item.summary.status === 'running')
        if (current) {
          setRunState('running')
          setLoading(true)
          const cursor = Math.max(...current.events.map((event) => event.sequence), 0)
          subscriptionRef.current = client.subscribeRun(activeId, current.summary.runId, {
            onEvent(event) {
              if (activeIdRef.current !== activeId) return
              if (event.kind === 'history_gap') {
                setTimelines((items) => items.map((item) => item.summary.runId === current.summary.runId ? { ...item, historyGap: true } : item))
                return
              }
              setTimelines((items) => items.map((item) => item.summary.runId === current.summary.runId ? { ...item, events: mergeEvents(item.events, [event]), summary: { ...item.summary, eventCount: Math.max(item.summary.eventCount, event.sequence), updatedAt: event.timestamp } } : item))
            },
            onError(reason) {
              if (activeIdRef.current !== activeId) return
              setRunState('unavailable')
              setLoading(false)
              setError(toUserMessage(reason))
            },
            onComplete() {
              subscriptionRef.current = null
              void client.getSession(activeId).then(async (updated) => {
                if (activeIdRef.current !== activeId) return
                setData(withLocalPreviews(updated))
                setSessions((items) => items.map((item) => item.id === updated.session.id ? updated.session : item))
                const history = await client.getRunHistory(activeId, current.summary.runId)
                setTimelines((items) => items.map((item) => item.summary.runId === current.summary.runId ? { ...item, summary: history.run, events: mergeEvents(item.events, history.events), historyGap: item.historyGap || history.historyGap } : item))
                setPendingUser(null)
                setRunState(history.run.status === 'interrupted' ? 'interrupted' : history.run.status === 'failed' ? 'failed' : 'completed')
                setLoading(false)
              }).catch((reason) => { setRunState('unavailable'); setLoading(false); setError(toUserMessage(reason)) })
            },
          }, cursor)
        } else {
          setRunState('idle')
          setLoading(false)
        }
      }
    }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false))
  }, [activeId, client])

  const clearPending = () => { pending.forEach((item) => URL.revokeObjectURL(item.previewUrl)); setPending([]) }
  const selectSession = (id: string) => { subscriptionRef.current?.close(); subscriptionRef.current = null; clearPending(); setSelectedIds([]); setPendingUser(null); setTimelines([]); setExpandedRuns(new Set()); setRunState('idle'); setAttachmentError(null); setError(null); setActiveId(id) }
  const create = async () => { setNewSessionName(''); setCreatingSession(true) }
  const confirmCreate = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const name = newSessionName.trim(); if (!name) return; setError(null); try { subscriptionRef.current?.close(); subscriptionRef.current = null; clearPending(); setSelectedIds([]); setPendingUser(null); setTimelines([]); setRunState('idle'); const created = await client.createSession(name); setSessions(await client.listSessions()); setActiveId(created.session.id); setCreatingSession(false) } catch (reason) { setError(toUserMessage(reason)) } }

  const forgetLocalPreview = (attachmentId: string) => {
    const url = localPreviews.current.get(attachmentId)
    if (url?.startsWith('blob:')) URL.revokeObjectURL(url)
    localPreviews.current.delete(attachmentId)
  }

  const requestDeleteSession = (id: string) => {
    const session = sessions.find((item) => item.id === id)
    if (session) setConfirmAction({ kind: 'session', session })
  }

  const requestDeleteAttachment = (attachment: Attachment) => setConfirmAction({ kind: 'attachment', attachment })

  const confirmDelete = async () => {
    const action = confirmAction
    if (!action || deleting) return
    setDeleting(true)
    setError(null)
    setAttachmentError(null)
    try {
      if (action.kind === 'session') {
        const deletedIndex = sessions.findIndex((item) => item.id === action.session.id)
        await client.deleteSession(action.session.id)
        const remaining = sessions.filter((item) => item.id !== action.session.id)
        setSessions(remaining)
        if (activeIdRef.current === action.session.id) {
          subscriptionRef.current?.close()
          subscriptionRef.current = null
          data?.attachments.forEach((attachment) => forgetLocalPreview(attachment.id))
          clearPending()
          setSelectedIds([])
          setPendingUser(null)
          setTimelines([])
          setExpandedRuns(new Set())
          setRunState('idle')
          setLoading(false)
          setData(null)
          const next = remaining[deletedIndex] || remaining[deletedIndex - 1]
          setActiveId(next?.id ?? '')
        }
      } else {
        const sessionId = activeIdRef.current
        await client.deleteAttachment(sessionId, action.attachment.id)
        forgetLocalPreview(action.attachment.id)
        setSelectedIds((ids) => ids.filter((id) => id !== action.attachment.id))
        setData((current) => current ? { ...current, attachments: current.attachments.filter((item) => item.id !== action.attachment.id) } : current)
      }
      setConfirmAction(null)
    } catch (reason) {
      const message = toUserMessage(reason)
      if (action.kind === 'attachment') setAttachmentError(message)
      else setError(message)
    } finally {
      setDeleting(false)
    }
  }

  const uploadPending = async (target: PendingAttachment) => {
    const sessionId = activeIdRef.current
    setPending((items) => items.map((item) => item.key === target.key ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const uploaded = await client.uploadAttachment(sessionId, target.file)
      if (activeIdRef.current !== sessionId) { URL.revokeObjectURL(target.previewUrl); return }
      const previewUrl = mode === 'mock' ? target.previewUrl : uploaded.previewUrl || ''
      if (mode === 'mock') localPreviews.current.set(uploaded.id, target.previewUrl)
      else URL.revokeObjectURL(target.previewUrl)
      setData((current) => current ? { ...current, attachments: [...current.attachments.filter((item) => item.id !== uploaded.id), { ...uploaded, previewUrl, previewAvailable: Boolean(previewUrl) }] } : current)
      setSelectedIds((ids) => ids.includes(uploaded.id) ? ids : [...ids, uploaded.id])
      setPending((items) => items.filter((item) => item.key !== target.key))
      setAttachmentError(null)
    } catch (reason) {
      const message = toUserMessage(reason)
      setPending((items) => items.map((item) => item.key === target.key ? { ...item, status: 'error', error: message } : item))
      setAttachmentError(message)
    }
  }

  const addFiles = (files: File[]) => {
    if (!activeIdRef.current) return
    const accepted: PendingAttachment[] = []
    for (const file of files) {
      const validationError = validateImageFile(file)
      if (validationError) { setAttachmentError(validationError); continue }
      const pendingItem: PendingAttachment = { key: `${Date.now()}-${accepted.length}-${file.name}`, file, previewUrl: URL.createObjectURL(file), status: 'uploading' }
      accepted.push(pendingItem)
    }
    if (accepted.length) { setPending((items) => [...items, ...accepted]); accepted.forEach((item) => void uploadPending(item)) }
  }

  const removePending = (key: string) => { const item = pending.find((candidate) => candidate.key === key); if (item) URL.revokeObjectURL(item.previewUrl); setPending((items) => items.filter((candidate) => candidate.key !== key)) }
  const toggleAttachment = (id: string) => setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id])

  const submit = async (text: string, attachmentIds: string[]): Promise<boolean> => {
    if (!activeId) return false
    const sessionId = activeId
    subscriptionRef.current?.close()
    setLoading(true)
    setRunState('connecting')
    setError(null)
    setSelectedIds([])
    setPendingUser({ id: `pending-${Date.now()}`, kind: 'user', text, timestamp: currentTime(), attachmentIds: attachmentIds.length ? attachmentIds : undefined })
    try {
      const handle = await client.startRun(sessionId, text, attachmentIds)
      if (activeIdRef.current !== sessionId) return false
      setPendingUser((current) => current ? { ...current, id: `${handle.runId}:user` } : current)
      setRunState('running')
      const startedAt = new Date().toISOString()
      setTimelines((current) => current.some((item) => item.summary.runId === handle.runId) ? current : [...current, { summary: { runId: handle.runId, sessionId, status: 'running', createdAt: startedAt, updatedAt: startedAt, eventCount: 0 }, events: [], historyGap: false }])
      let terminalFailure = false
      let reconnectAttempts = 0
      const applyHistory = (history: Awaited<ReturnType<ChartAgentClient['getRunHistory']>>) => {
        setTimelines((current) => current.map((item) => item.summary.runId === handle.runId ? { summary: history.run, events: mergeEvents(item.events, history.events), historyGap: item.historyGap || history.historyGap } : item))
        return history
      }
      const connect = (afterSequence = 0) => {
        subscriptionRef.current = client.subscribeRun(sessionId, handle.runId, {
          onEvent(event) {
            if (activeIdRef.current !== sessionId) return
            if (event.kind === 'history_gap') {
              setTimelines((current) => current.map((item) => item.summary.runId === handle.runId ? { ...item, historyGap: true } : item))
              return
            }
            if (event.kind === 'run_failed') {
              terminalFailure = true
              setRunState('failed')
              setLoading(false)
              setError(toUserMessage(new GatewayClientError(String(event.payload.code || 'agent_failed'), String(event.payload.message || 'Agent 执行失败'), 502, typeof event.payload.reason === 'string' ? event.payload.reason : undefined)))
            } else if (event.kind !== 'run_started') setRunState('running')
            setTimelines((current) => current.map((item) => item.summary.runId === handle.runId ? { ...item, events: mergeEvents(item.events, [event]), summary: { ...item.summary, eventCount: Math.max(item.summary.eventCount, event.sequence), updatedAt: event.timestamp }, historyGap: item.historyGap || event.kind === 'history_gap' } : item))
          },
          async onError(reason) {
            if (activeIdRef.current !== sessionId) return
            setRunState('connecting')
            try {
              const currentTimeline = await client.getRunHistory(sessionId, handle.runId)
              const history = applyHistory(currentTimeline)
              if (history.run.status === 'running' && reconnectAttempts < 2) { reconnectAttempts += 1; const latest = Math.max(...history.events.map((event) => event.sequence), 0); connect(latest); return }
              if (history.run.status === 'completed') { setRunState('completed'); setLoading(false); setPendingUser(null); return }
              if (history.run.status === 'failed') terminalFailure = true
            } catch { /* The visible error below preserves all events already rendered. */ }
            setRunState('unavailable')
            setLoading(false)
            setError(toUserMessage(reason))
          },
          onComplete() {
            subscriptionRef.current = null
            if (activeIdRef.current !== sessionId || terminalFailure) return
            void client.getSession(sessionId).then(async (updated) => {
              if (activeIdRef.current !== sessionId) return
              setData(withLocalPreviews(updated))
              setSessions((current) => current.map((item) => item.id === updated.session.id ? updated.session : item))
              let history = await client.getRunHistory(sessionId, handle.runId)
              for (let attempt = 0; attempt < 5 && history.run.status === 'running'; attempt += 1) {
                await delay(40)
                history = await client.getRunHistory(sessionId, handle.runId)
              }
              applyHistory(history)
              setPendingUser(null)
              setRunState(history.run.status === 'interrupted' ? 'interrupted' : 'completed')
              setLoading(false)
            }).catch((reason) => { setRunState('failed'); setLoading(false); setError(toUserMessage(reason)) })
          },
        }, afterSequence)
      }
      connect()
      return true
    } catch (reason) {
      setRunState('unavailable')
      setError(toUserMessage(reason))
      setLoading(false)
      return false
    }
  }

  const toggleRun = (runId: string, status: RunSummary['status']) => setExpandedRuns((current) => { const next = new Set(current); if (status === 'running') { next.has(runId) ? next.delete(runId) : next.add(runId) } else { next.has(runId) ? next.delete(runId) : next.add(runId) } return next })
  return <><div className="app-shell"><SessionSidebar sessions={sessions} activeId={activeId} onSelect={selectSession} onCreate={create} onDelete={requestDeleteSession} mode={mode} runtimeStatus={runtimeStatus} health={gatewayHealth} /><ConversationPanel data={data} timelines={timelines} pendingUser={pendingUser} runState={runState} selectedAttachmentIds={selectedIds} onSubmit={submit} loading={loading} loadingSession={loadingSession} error={error} onToggleRun={toggleRun} expandedRuns={expandedRuns} /><AttachmentPanel attachments={data?.attachments ?? []} pending={pending} selectedIds={selectedIds} error={attachmentError} onAdd={addFiles} onToggle={toggleAttachment} onRemovePending={removePending} onRetryPending={(item) => void uploadPending(item)} onRemove={requestDeleteAttachment} /></div>{creatingSession && <div className="dialog-backdrop"><form className="session-dialog" onSubmit={(event) => void confirmCreate(event)}><h2>新建会话</h2><label htmlFor="session-name">会话名称</label><input id="session-name" value={newSessionName} onChange={(event) => setNewSessionName(event.target.value)} placeholder="例如：季度销售分析" autoFocus /><div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={() => setCreatingSession(false)}>取消</button><button type="submit" className="dialog-primary" disabled={!newSessionName.trim()}>创建会话</button></div></form></div>}{confirmAction && <div className="dialog-backdrop"><div className="session-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title"><h2 id="delete-dialog-title">{confirmAction.kind === 'session' ? '删除会话？' : '删除附件？'}</h2><p className="dialog-message">{confirmAction.kind === 'session' ? `将永久删除“${confirmAction.session.name}”及其运行记录和附件。` : `将删除“${confirmAction.attachment.filename}”及其源文件。`}</p><div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={() => setConfirmAction(null)} disabled={deleting}>取消</button><button type="button" className="dialog-danger" onClick={() => void confirmDelete()} disabled={deleting}><Trash2 size={13} />{deleting ? '正在删除' : '确认删除'}</button></div></div></div>}</>
}

function toUserMessage(error: unknown): string {
  if (error instanceof GatewayClientError) {
    if (error.code === 'gateway_unavailable') return '无法连接到本地 Gateway，请先启动 Python 服务。'
    if (error.code === 'agent_unavailable' && error.reason === 'missing_configuration') return 'Agent 未配置，请检查项目根目录 .env 中的模型配置。'
    if (error.code === 'agent_unavailable' && error.reason === 'invalid_configuration') return 'Agent 配置无效，请检查模型地址和参数。'
    if (error.code === 'agent_unavailable') return 'Agent 当前不可用，请稍后重试。'
    if (error.code === 'session_not_found') return '会话不存在，可能已被删除。'
    if (error.code === 'session_exists') return '会话名称已存在，请换一个名称。'
    if (error.code === 'session_busy') return '会话正在运行 Agent，请等待本次运行结束后再删除。'
    if (error.code === 'run_unavailable' || error.code === 'event_history_unavailable') return '这条执行记录已不可用，当前只保留可恢复的会话内容。'
    if (error.code === 'attachment_not_found') return '附件不存在或不属于当前会话。'
    if (error.code === 'attachment_unavailable') return '附件源文件不可用，请重新上传。'
    if (error.code === 'attachment_storage_error') return '附件文件操作失败，请稍后重试。'
    if (error.code === 'unsupported_media_type' || error.code === 'invalid_image') return '图片格式无法识别，请选择 PNG、JPEG、GIF 或 WebP。'
    if (error.code === 'attachment_too_large' || error.code === 'attachment_storage_limit') return '图片或当前会话的附件总量超过限制。'
    if (error.code === 'invalid_filename') return '图片文件名无效，请重命名后重试。'
    if (error.code === 'invalid_request') return '请求内容无效，请检查后重试。'
    return '本地服务处理失败，请稍后重试。'
  }
  return '操作失败，请稍后重试。'
}
