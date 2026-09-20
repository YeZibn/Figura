import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, type RefObject } from 'react'
import { AlertTriangle, BarChart3, Check, CheckCircle2, ChevronDown, ChevronRight, ClipboardList, Download, FileImage, LoaderCircle, Maximize2, MessageSquare, Minus, Paperclip, Plus, RefreshCw, Send, Sparkles, Terminal, Trash2, X } from 'lucide-react'
import { GatewayClientError, configureGatewayBaseUrl, currentGatewayBaseUrl, gatewayClient } from './api/gatewayClient'
import type { ChartAgentClient, RunSubscription } from './api/client'
import { mockClient } from './api/mockClient'
import { formatBytes, mediaTypeForFile, validateImageFile } from './attachments'
import { getGatewayRuntimeStatus, type GatewayRuntimeStatus } from './runtime'
import { createGatewayPreviewLoader, releasePreview, usePreviewResource, type PreviewResourceLoader } from './previewResources'
import { isMeasurementRepairEventKind } from './types/protocol'
import type { AgentRunEvent, Attachment, AttachmentStatus, ConversationItem, EvaluationCaseData, EvaluationDetail, EvaluationDetailEntry, EvaluationHistory, EvaluationHistoryDetails, EvaluationResource, EvaluationStatus, EvaluationSummary, GatewayHealth, GeneratedChartReference, MeasurementRepairSummary, Provider, RunState, RunSummary, Session, SessionData } from './types/protocol'
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

type PreviewDescriptor = {
  resource?: import('./types/protocol').PreviewResource
  fallbackUrl?: string
  alt: string
  title: string
  sourceLabel: string
  statusLabel?: string
  triggerRef: RefObject<HTMLElement>
}

type PreviewOpener = (descriptor: PreviewDescriptor) => void

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
  if (state === 'reconnecting') return '正在重连'
  if (state === 'cancel_requested') return '正在中断'
  if (state === 'completed') return '已完成'
  if (state === 'failed') return '运行失败'
  if (state === 'interrupted') return '已中断'
  if (state === 'history-gap') return '历史记录不完整'
  if (state === 'unavailable') return '服务不可用'
  return '准备就绪'
}

const providerLabels: Record<Provider, string> = {
  openai: 'OpenAI（中转站）',
  qwen: 'Qwen（DashScope）',
  deepseek: 'DeepSeek（V4.1 Flash）',
}

function providerLabel(provider?: Provider | null): string {
  return provider ? providerLabels[provider] : ''
}

function providerStatus(health: GatewayHealth | null, provider: Provider, mode: 'mock' | 'gateway'): 'ready' | 'unavailable' | 'unknown' {
  const status = health?.agent?.providers?.[provider]?.status
  if (status) return status
  if (health?.agent?.provider === provider) return health.agent.status
  return health || mode === 'gateway' ? 'unknown' : 'ready'
}

function currentTime(): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `figura-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function eventPayload(event: AgentRunEvent): Record<string, unknown> {
  return event.payload || {}
}

function textDetail(value: unknown): string {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return '事件内容不可显示' }
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function boundedDisplayText(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim()
  if (!normalized) return undefined
  const redacted = normalized.replace(/(?:[A-Za-z]:[\\/]|\/(?:Users|home|private|tmp|var|opt|etc)\/)[^\s"'`，。；;]+/g, '[已隐藏路径]')
  return redacted.slice(0, 120)
}

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

function measurementRepairSummary(event: AgentRunEvent): MeasurementRepairSummary | null {
  if (!isMeasurementRepairEventKind(event.kind)) return null
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
  }
}

function measurementRepairDetail(event: AgentRunEvent): string {
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
  if (event.kind === 'measurement_repair_required') return '等待同一面板内的定向重测。'
  if (event.kind === 'measurement_repair_rejected') return '定向重测未被接受，保留当前测量证据。'
  return '定向重测次数已用尽，当前候选不会自动发布。'
}

function traceEventDetail(event: AgentRunEvent): string {
  if (isMeasurementRepairEventKind(event.kind)) return measurementRepairDetail(event)
  const payload = eventPayload(event)
  return textDetail(payload.message || payload.status || payload.publication_status || payload.reason || (event.kind === 'generated_chart' ? '生成图表结果已移至最终结果区域' : ''))
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
  toolLabel?: string
  call?: AgentRunEvent
  result?: AgentRunEvent
  resultTruncated?: boolean
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
  const byCursor = new Map(current.map((event) => [`${event.runId}:${event.sequence}`, event]))
  incoming.forEach((event) => {
    const key = `${event.runId}:${event.sequence}`
    if (!byCursor.has(key)) byCursor.set(key, event)
  })
  return [...byCursor.values()].sort((left, right) => left.sequence - right.sequence)
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

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
}

function InteractivePreview({ preview, loader, onClose }: { preview: PreviewDescriptor; loader: PreviewResourceLoader | null; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const [zoom, setZoom] = useState(100)
  const [imageFailed, setImageFailed] = useState(false)
  const resource = usePreviewResource(loader, preview.resource, preview.fallbackUrl)

  useEffect(() => {
    setZoom(100)
    setImageFailed(false)
  }, [preview.resource, preview.fallbackUrl])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const trigger = preview.triggerRef
    const focusTarget = closeRef.current || dialog
    const focusFrame = window.requestAnimationFrame(() => focusTarget.focus())
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const elements = focusableElements(dialog)
      if (elements.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
      window.requestAnimationFrame(() => {
        const element = trigger.current
        if (element?.isConnected) element.focus()
      })
    }
  }, [onClose, preview.triggerRef])

  const changeZoom = (amount: number) => setZoom((value) => Math.min(400, Math.max(50, value + amount)))
  const imageAvailable = resource.status === 'available' && Boolean(resource.url) && !imageFailed

  return <div className="preview-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div ref={dialogRef} className="interactive-preview" role="dialog" aria-modal="true" aria-labelledby="interactive-preview-title" tabIndex={-1}>
      <header className="interactive-preview-header">
        <div className="interactive-preview-heading">
          <span className="eyebrow">{preview.sourceLabel}</span>
          <h2 id="interactive-preview-title">{preview.title}</h2>
          {preview.statusLabel && <span className="interactive-preview-status">{preview.statusLabel}</span>}
        </div>
        <button ref={closeRef} type="button" className="preview-close" onClick={onClose} aria-label="关闭图片预览" title="关闭图片预览"><X size={17} /></button>
      </header>
      <div className="preview-viewport" aria-busy={resource.status === 'loading'}>
        {resource.status === 'loading' && <div className="preview-overlay-message"><LoaderCircle className="spin-icon" size={20} />正在加载预览</div>}
        {imageAvailable && <img className="interactive-preview-image" src={resource.url} alt={preview.alt} style={zoom === 100 ? undefined : { width: `${zoom}%`, maxWidth: 'none', maxHeight: 'none' }} onError={() => setImageFailed(true)} />}
        {!imageAvailable && resource.status !== 'loading' && <div className="preview-overlay-message" role="status">{imageFailed || resource.status === 'invalid' ? '预览格式无效' : resource.error?.message || '预览资源不可用或已过期'}</div>}
      </div>
      <footer className="interactive-preview-controls">
        <div className="preview-zoom-controls" aria-label="图片缩放控制">
          <button type="button" className="preview-control" onClick={() => changeZoom(-25)} disabled={!imageAvailable || zoom <= 50} aria-label="缩小图片" title="缩小图片"><Minus size={14} /></button>
          <span aria-live="polite">{zoom}%</span>
          <button type="button" className="preview-control" onClick={() => changeZoom(25)} disabled={!imageAvailable || zoom >= 400} aria-label="放大图片" title="放大图片"><Maximize2 size={14} /></button>
          <button type="button" className="preview-fit" onClick={() => setZoom(100)} disabled={!imageAvailable} aria-label="适应窗口" title="适应窗口"><Maximize2 size={13} />适应窗口</button>
        </div>
        <span className="preview-control-hint">使用 Tab 操作控件，按 Esc 关闭</span>
      </footer>
    </div>
  </div>
}

function PreviewImage({ loader, resource, fallbackUrl, alt, className, onError, onPreview, sourceLabel = '图片', title, statusLabel }: { loader: PreviewResourceLoader | null; resource?: import('./types/protocol').PreviewResource; fallbackUrl?: string; alt: string; className?: string; onError?: () => void; onPreview?: PreviewOpener; sourceLabel?: string; title?: string; statusLabel?: string }) {
  const preview = usePreviewResource(loader, resource, fallbackUrl)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [imageError, setImageError] = useState(false)
  useEffect(() => setImageError(false), [preview.url])
  if (preview.status === 'loading') return <div className="preview-placeholder loading-preview"><LoaderCircle className="spin-icon" size={18} />正在加载预览</div>
  if (preview.status === 'available' && preview.url && !imageError) {
    const image = <img className={className} src={preview.url} alt={alt} onError={() => { setImageError(true); onError?.() }} />
    if (!onPreview) return image
    return <button ref={triggerRef} type="button" className="preview-trigger" onClick={() => onPreview({ resource, fallbackUrl, alt, title: title || alt, sourceLabel, statusLabel, triggerRef })} aria-label={`查看${title || alt}大图`} title={`查看${title || alt}大图`}>{image}</button>
  }
  return <div className="preview-placeholder">{preview.status === 'invalid' || imageError ? '预览格式无效' : '预览资源不可用或已过期'}{preview.error?.retryable && <button type="button" className="preview-retry" onClick={preview.retry}>重试</button>}</div>
}

function ObservationView({ observation, loader, onPreview }: { observation: Record<string, unknown>; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const caption = String(observation.caption || '视觉观察')
  const resource = observation.previewResource as import('./types/protocol').PreviewResource | undefined
  return <div className="trace-observation"><div className="observation-label"><FileImage size={13} /><strong>视觉观察</strong></div><PreviewImage loader={loader} onPreview={onPreview} sourceLabel="视觉观察" title={caption} resource={resource} fallbackUrl={typeof observation.imageUrl === 'string' ? observation.imageUrl : undefined} alt={caption} /><small>{caption}</small></div>
}

function chartTypeLabel(value: string): string {
  return ({ bar: '柱状图', line: '折线图', pie: '饼图', scatter: '散点图' } as Record<string, string>)[value] || value || '图表'
}

function GeneratedChartView({ artifact, loader, onPreview }: { artifact: GeneratedChartReference; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const [imageFailed, setImageFailed] = useState(false)
  useEffect(() => setImageFailed(false), [artifact.imageUrl, artifact.previewResource])
  const publicationStatus = artifact.publicationStatus || ''
  const reviewStatus = artifact.reviewStatus || ''
  const candidateStatus = artifact.candidateStatus || ''
  const reviewMode = artifact.reviewMode || ''
  const status = publicationStatus === 'published' ? 'available' : publicationStatus === 'published_with_warning' ? 'warning' : publicationStatus === 'rejected' || candidateStatus === 'review_failed' || candidateStatus === 'timed_out' || candidateStatus === 'retry_exhausted' ? 'failed' : reviewStatus === 'pending' || reviewStatus === 'requires_model_decision' || candidateStatus === 'review_pending' || artifact.status === 'pending' ? 'pending' : artifact.status === 'unavailable' || (!artifact.imageUrl && !artifact.previewResource) || imageFailed ? 'unavailable' : artifact.status === 'warning' ? 'warning' : 'available'
  const statusLabel = status === 'available' ? '已发布' : status === 'warning' ? '已发布·有警告' : status === 'pending' ? (reviewMode === 'vlm' ? 'VLM 审核中' : '待审核') : status === 'failed' ? (candidateStatus === 'retry_exhausted' ? '未发布·修复次数已耗尽' : '未发布·审核未通过') : '暂不可用'
  const metadata = [
    artifact.chartType ? chartTypeLabel(artifact.chartType) : '',
    artifact.figureId ? `复合图 ${artifact.figureId}` : '',
    artifact.childChartIds?.length ? `${artifact.childChartIds.length} 个子图` : '',
    artifact.width && artifact.height ? `${artifact.width} × ${artifact.height}` : '',
    typeof artifact.byteCount === 'number' ? formatBytes(artifact.byteCount) : '',
  ].filter(Boolean).join(' · ')
  const figureDetail = artifact.figureId ? [
    artifact.source?.panel_id ? `来源面板：${artifact.source.panel_id}` : '',
    artifact.coverage?.status ? `覆盖：${artifact.coverage.status === 'complete' ? '完整' : artifact.coverage.status}` : '',
    artifact.coverage?.omitted_series?.length ? `遗漏系列：${artifact.coverage.omitted_series.join('、')}` : '',
  ].filter(Boolean).join(' · ') : ''
  const download = async () => {
    if ((!artifact.downloadUrl && !artifact.previewResource) || downloading) return
    setDownloading(true)
    setDownloadError('')
    try {
      let objectUrl = artifact.downloadUrl || ''
      let temporary = false
      if (loader && artifact.previewResource) {
        const result = await loader(artifact.previewResource)
        objectUrl = result.url
        temporary = result.temporary
      } else {
        const response = await fetch(objectUrl)
        if (!response.ok) throw new Error('download failed')
        const blob = await response.blob()
        objectUrl = URL.createObjectURL(blob)
        temporary = true
      }
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = `${artifact.title || 'figura-chart'}.png`
      document.body.appendChild(link)
      link.click()
      link.remove()
      if (temporary) releasePreview({ url: objectUrl, temporary })
    } catch {
      setDownloadError('下载失败，请稍后重试')
    } finally {
      setDownloading(false)
    }
  }
  return <article className={'generated-chart ' + status}>
    <div className="generated-chart-heading"><div className="observation-label"><BarChart3 size={13} /><strong>生成图表</strong><span>{statusLabel}</span></div>{(artifact.downloadUrl || artifact.previewResource) && (status === 'available' || status === 'warning') && <button className="chart-download" type="button" onClick={() => void download()} disabled={downloading} title="下载生成图表"><Download size={13} />{downloading ? '正在下载' : '下载 PNG'}</button>}</div>
    {(artifact.imageUrl || artifact.previewResource) && (status === 'available' || status === 'warning' || status === 'pending' || status === 'failed') ? <PreviewImage loader={loader} onPreview={onPreview} sourceLabel="生成图表" statusLabel={statusLabel} title={artifact.title || artifact.caption || '生成图表'} resource={artifact.previewResource} fallbackUrl={artifact.previewResource ? undefined : artifact.imageUrl} alt={artifact.title || artifact.caption || '生成图表'} onError={() => setImageFailed(true)} /> : <div className="observation-placeholder">{status === 'failed' ? '图表审核未通过，未产生可下载文件' : '图表文件已过期或暂不可用'}</div>}
    <div className="generated-chart-copy"><strong>{artifact.title || artifact.caption || '未命名图表'}</strong>{metadata && <small>{metadata}</small>}{figureDetail && <small>{figureDetail}</small>}{artifact.reason && <small className="generated-chart-reason">{artifact.reason}</small>}{artifact.review?.issues?.slice(0, 3).map((issue, index) => issue.message ? <small className="generated-chart-reason" key={`${issue.code || 'issue'}-${index}`}>{issue.message}</small> : null)}{downloadError && <small className="generated-chart-reason">{downloadError}</small>}</div>
  </article>
}

function eventLabel(event: AgentRunEvent): string {
  const labels: Record<string, string> = { run_started: '运行已开始', resume_started: '继续执行已开始', model_started: '模型轮次开始', model_completed: '模型轮次完成', operation_completed: '操作结果已保存', recovery_blocked: '继续执行被阻止', progress: '处理中', generated_chart: '图表状态已更新', chart_review_started: '图表审核已开始', chart_review_required: '等待图表审核', chart_review_repair_required: '正在修复并重新审核', generated_chart_published: '图表已发布', generated_chart_rejected: '图表未发布', chart_review_completed: '图表审核完成', measurement_repair_required: '需要定向重测', measurement_repair_rejected: '定向重测被拒绝', measurement_repair_exhausted: '定向重测次数已用尽', final_answer: '最终回答已生成', budget_exhausted: '达到预算上限', run_failed: '运行失败', run_interrupted: '运行已中断', history_gap: '历史记录不完整', tool_result: '工具结果（历史记录不完整）' }
  return labels[event.kind] || event.kind
}

function RunTimeline({ timeline, expanded, onToggle, previewLoader, onPreview, onInterrupt, onRetry, onResume }: { timeline: RunTimeline; expanded: boolean; onToggle: () => void; previewLoader: PreviewResourceLoader | null; onPreview?: PreviewOpener; onInterrupt?: () => void; onRetry?: () => void; onResume?: () => void }) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const rows = normalizeTimeline(timeline.events)
  const summary = timeline.summary
  const status = summary.status
  const statusText = status === 'completed' ? '已完成' : status === 'failed' ? '失败' : status === 'interrupted' ? '已中断' : summary.cancelRequested ? '正在中断' : '运行中'
  return <section className={'run-timeline ' + status + (expanded ? ' expanded' : '')}>
    <button className="run-summary" onClick={onToggle} aria-expanded={expanded} aria-controls={`trace-${summary.runId}`}><span className="run-arrow">{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</span><span className="run-summary-icon"><Terminal size={14} /></span><span className="run-summary-copy"><strong>执行过程</strong><small>{timestampLabel(summary.createdAt)} · {summary.eventCount || timeline.events.length} 个事件{summary.provider ? ` · ${providerLabel(summary.provider)}${summary.model ? ` · ${summary.model}` : ''}` : ''}{summary.retryOf ? ` · 重试自 ${summary.retryOf}` : ''}</small></span><span className={'run-status ' + status}>{statusText}</span></button>
    {(status === 'running' && onInterrupt) || ((status === 'failed' || status === 'interrupted') && (onRetry || onResume)) ? <div className="run-actions">
      {status === 'running' && onInterrupt && <button type="button" className="small-action" onClick={onInterrupt} disabled={summary.cancelRequested}>{summary.cancelRequested ? '正在中断' : '中断运行'}</button>}
      {status !== 'running' && onResume && summary.recovery?.status === 'available' && <button type="button" className="small-action" onClick={onResume}>继续执行</button>}
      {(status === 'failed' || status === 'interrupted') && onRetry && <button type="button" className="small-action" onClick={onRetry}>重试本次运行</button>}
    </div> : null}
    {expanded && <div className="run-trace" id={`trace-${summary.runId}`}>
      {summary.recovery && summary.recovery.status !== 'unavailable' && <div className={'trace-warning recovery-' + summary.recovery.status} role="status">{summary.recovery.status === 'available' ? `可继续执行：${summary.recovery.phase || '已保存'} · 下一步 ${summary.recovery.nextAction || '继续处理'}` : `暂时无法继续执行：${summary.recovery.blockedReason || '恢复状态受限'}，可使用“重试本次运行”。`}</div>}
      {summary.historyWarning && <div className="trace-warning" role="status">部分执行记录未能持久化，当前显示的过程可能不完整。</div>}
      {timeline.historyGap && <div className="trace-warning" role="status">历史记录存在缺口，未显示缺失的执行步骤。</div>}
      {rows.length === 0 && <div className="trace-empty">没有可恢复的执行事件。</div>}
      {rows.map((row) => row.kind === 'event' ? <div className={'trace-event ' + (isMeasurementRepairEventKind(row.event.kind) ? `repair ${row.event.kind === 'measurement_repair_required' ? 'pending' : 'error'}` : '') + (row.event.kind === 'run_failed' || row.event.kind === 'run_interrupted' || row.event.kind === 'history_gap' ? ' error' : '')} key={`${row.event.runId}-${row.event.sequence}`}><span className="trace-event-dot" /><span className="trace-event-copy"><strong>{eventLabel(row.event)}</strong><small>{timestampLabel(row.event.timestamp)}{isMeasurementRepairEventKind(row.event.kind) ? ` · ${row.event.kind}` : ''}</small><span>{traceEventDetail(row.event)}</span></span></div> : <div className="trace-tool" key={row.step.id}><button className="trace-tool-header" onClick={() => setExpandedSteps((current) => { const next = new Set(current); next.has(row.step.id) ? next.delete(row.step.id) : next.add(row.step.id); return next })} aria-expanded={expandedSteps.has(row.step.id)}><span className="trace-event-dot" /><span className="trace-tool-name"><strong>{row.step.toolLabel || row.step.toolName}</strong><small>{row.step.toolName} · {row.step.callId}</small></span><span className={'run-status ' + row.step.status}>{row.step.status === 'running' ? '运行中' : row.step.status === 'success' ? '完成' : '失败'}</span>{expandedSteps.has(row.step.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>{expandedSteps.has(row.step.id) && <div className="trace-tool-detail">{row.step.call && <div><label>调用参数</label><pre>{textDetail(eventPayload(row.step.call).arguments)}</pre></div>}{row.step.result && <div><label>工具结果</label>{row.step.resultTruncated && <small className="trace-warning">工具结果已截断，仅保留有限诊断内容。</small>}<pre>{textDetail(eventPayload(row.step.result).result || eventPayload(row.step.result).message)}</pre></div>}{row.step.observations.map((observation, index) => <ObservationView key={index} observation={observation} loader={previewLoader} onPreview={onPreview} />)}</div>}</div>)}
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

function evaluationStatusLabel(status: EvaluationStatus): string {
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
  if (status === 'blocked') return '已阻塞'
  return '部分完成'
}

function evaluationStatusClass(status: EvaluationStatus): string {
  return status === 'completed' ? 'completed' : status === 'running' ? 'running' : status === 'blocked' ? 'failed' : 'partial'
}

function evaluationResourceLabel(resource: EvaluationResource): string {
  if (resource.kind === 'input') return '输入图'
  if (resource.kind === 'report_image') return '报告图片'
  if (resource.kind === 'observation') return '视觉观察'
  if (resource.kind === 'candidate') return '候选图表'
  if (resource.kind === 'artifact') return '生成结果'
  return resource.label || '评测证据'
}

function evaluationDetailEntryLabel(entry: EvaluationDetailEntry): string {
  if (entry.kind === 'conversation') return entry.role === 'user' ? '用户消息' : entry.role === 'assistant' ? '模型消息' : '系统消息'
  if (entry.kind === 'tool_message') return '模型可见工具消息'
  if (entry.kind === 'tool_call') return entry.toolLabel || entry.toolName || '工具调用'
  if (entry.kind === 'tool_result') return (entry.toolLabel || entry.toolName || '工具') + ' · 工具结果'
  if (entry.kind === 'repair' || entry.kind.startsWith('measurement_repair')) return '测量修复信息'
  if (entry.kind === 'visual_observation') return '视觉观察'
  if (entry.kind === 'generated_chart') return '生成结果'
  return entry.kind || '运行记录'
}

function evaluationDetailSequenceLabel(entry: EvaluationDetailEntry): string {
  if (typeof entry.recordSequence === 'number') return 'record #' + entry.recordSequence
  if (typeof entry.eventSequence === 'number') return 'event #' + entry.eventSequence
  return '未编号'
}

function EvaluationDetailEntryView(props: { entry: EvaluationDetailEntry; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const entry = props.entry
  const hasContent = entry.content !== undefined && entry.content !== null && entry.content !== ''
  const hasArguments = entry.arguments !== undefined
  const hasResult = entry.result !== undefined
  const hasDetails = entry.details !== undefined
  return <details className={'evaluation-detail-entry ' + (entry.kind === 'tool_result' ? 'tool-result' : '')} open={entry.kind === 'conversation' || entry.kind === 'tool_call' || entry.kind === 'tool_result'}>
    <summary><span className="evaluation-detail-entry-title"><strong>{evaluationDetailEntryLabel(entry)}</strong><small>{entry.timestamp ? timestampLabel(entry.timestamp) : '未知时间'} · {evaluationDetailSequenceLabel(entry)}{entry.callId ? ' · ' + entry.callId : ''}</small></span><span className="evaluation-detail-entry-state">{entry.status || (entry.source === 'record' ? '可见记录' : '事件')}</span></summary>
    <div className="evaluation-detail-entry-body">
      {entry.toolName && <div className="evaluation-detail-meta"><span>工具</span><code>{entry.toolName}</code></div>}
      {entry.role && <div className="evaluation-detail-meta"><span>角色</span><code>{entry.role}</code></div>}
      {hasContent && <div className="evaluation-detail-block"><label>可见内容</label><pre>{textDetail(entry.content)}</pre></div>}
      {hasArguments && <div className="evaluation-detail-block"><label>调用参数</label><pre>{textDetail(entry.arguments)}</pre></div>}
      {hasResult && <div className="evaluation-detail-block"><label>工具结果</label><pre>{textDetail(entry.result)}</pre></div>}
      {hasDetails && <div className="evaluation-detail-block"><label>{entry.kind === 'repair' ? '修复详情' : '事件详情'}</label><pre>{textDetail(entry.details)}</pre></div>}
      {entry.toolCalls !== undefined && <div className="evaluation-detail-block"><label>工具调用声明</label><pre>{textDetail(entry.toolCalls)}</pre></div>}
      {entry.code && <div className="evaluation-detail-meta"><span>代码</span><code>{entry.code}</code></div>}
      {entry.reason && <div className="evaluation-detail-note">{entry.reason}</div>}
      {entry.truncated && <div className="evaluation-detail-note">该条记录已按安全上限截断，未展示完整原始内容。</div>}
      {entry.redacted && <div className="evaluation-detail-note">该条记录包含已隐藏的敏感字段或二进制内容。</div>}
      {entry.observations?.map((observation, index) => <ObservationView key={entry.entryId + '-observation-' + index} observation={observation as unknown as Record<string, unknown>} loader={props.loader} onPreview={props.onPreview} />)}
      {entry.artifacts?.map((artifact, index) => <GeneratedChartView key={entry.entryId + '-artifact-' + index} artifact={artifact} loader={props.loader} onPreview={props.onPreview} />)}
    </div>
  </details>
}

function EvaluationHistoryView(props: { history: EvaluationHistory | null; details: EvaluationHistoryDetails | null; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener; loading: boolean; detailsLoading: boolean; detailsError: string | null; onLoadDetails: () => void }) {
  if (props.loading) return <div className="evaluation-loading"><LoaderCircle className="spin-icon" size={17} />正在加载运行历史</div>
  if (!props.history) return <div className="evaluation-muted">该 case 暂无可读取的运行历史。</div>
  return <div className="evaluation-history">
    <div className="evaluation-section-heading"><div><span className="eyebrow">只读运行记录</span><h3>执行时间线</h3></div><div className="evaluation-history-heading-actions"><code>{props.history.run.runId}</code><button type="button" className="small-action" onClick={props.onLoadDetails} disabled={props.detailsLoading}>{props.detailsLoading ? '正在加载详细记录' : props.details ? '刷新详细记录' : '展开对话与工具详情'}</button></div></div>
    {props.history.historyGap && <div className="evaluation-warning"><AlertTriangle size={14} />历史记录存在缺口，以下仅展示已保留事件。</div>}
    {props.history.events.length === 0 && <div className="evaluation-muted">没有可展示的事件。</div>}
    {props.history.events.map((event) => {
      const payload = event.payload || {}
      const observations = Array.isArray(payload.observations) ? payload.observations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : []
      return <article className={'evaluation-event ' + (event.kind === 'run_failed' ? 'error' : '')} key={`${event.runId}-${event.sequence}`}>
        <span className="evaluation-event-dot" />
        <div className="evaluation-event-copy"><strong>{eventLabel(event)}</strong><small>{timestampLabel(event.timestamp)} · #{event.sequence}{typeof payload.tool_name === 'string' ? ` · ${payload.tool_name}` : ''}</small>{typeof payload.message === 'string' && <span>{payload.message}</span>}
          {event.kind === 'tool_call' && <span className="evaluation-event-note">详细参数可按需展开，当前时间线只保留安全摘要。</span>}
          {event.kind === 'tool_result' && <span className="evaluation-event-note">详细结果可按需展开，当前时间线只保留安全摘要。</span>}
          {observations.map((observation, index) => <ObservationView key={index} observation={observation} loader={props.loader} onPreview={props.onPreview} />)}
        </div>
      </article>
    })}
    {props.detailsError && <div className="evaluation-warning" role="status"><AlertTriangle size={14} />{props.detailsError}<button type="button" className="small-action" onClick={props.onLoadDetails}>重试</button></div>}
    {props.details && <section className="evaluation-detail-records"><div className="evaluation-section-heading"><div><span className="eyebrow">按需加载</span><h3>对话、工具与证据详情</h3></div><span className="detail-count">{props.details.entries.length} 条</span></div>{props.details.notice && <div className="evaluation-detail-notice">{props.details.notice}</div>}{props.details.historyGap && <div className="evaluation-warning"><AlertTriangle size={14} />详细记录存在缺口，序号较早的内容可能已被清理。</div>}{props.details.entries.length ? <div className="evaluation-detail-list">{props.details.entries.map((entry) => <EvaluationDetailEntryView key={entry.entryId} entry={entry} loader={props.loader} onPreview={props.onPreview} />)}</div> : <div className="evaluation-muted">没有可展开的详细记录。</div>}{props.details.truncated && <div className="evaluation-detail-note">本次详细记录受大小上限保护，部分内容已截断。</div>}</section>}
  </div>
}

function EvaluationPanel(props: {
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
            <section className="evaluation-section"><div className="evaluation-section-heading"><div><span className="eyebrow">阶段诊断</span><h3>链路状态</h3></div>{currentCase.timeline.historyGap && <span className="run-status interrupted">历史不完整</span>}</div><div className="evaluation-stage-list">{currentCase.timeline.stages.length ? currentCase.timeline.stages.map((stage) => <div className="evaluation-stage" key={stage.name}><span className={'evaluation-stage-dot ' + (stage.status === 'completed' ? 'success' : stage.status === 'failed' ? 'error' : '')}>{stage.status === 'completed' ? <CheckCircle2 size={13} /> : <span />}</span><div><strong>{stage.name}</strong><small>{stage.status}{stage.sequences.length ? ` · 事件 ${stage.sequences.join(', ')}` : ''}{stage.errors.length ? ` · ${stage.errors.join('；')}` : ''}</small></div></div>) : <div className="evaluation-muted">暂无阶段诊断。</div>}</div></section>
            <section className="evaluation-section"><div className="evaluation-section-heading"><div><span className="eyebrow">报告</span><h3>{currentCase.report.available ? '评测报告' : '标准诊断摘要'}</h3></div>{currentCase.report.truncated && <span className="run-status interrupted">已截断</span>}</div>{currentCase.report.text ? <SafeMarkdown source={currentCase.report.text} /> : <div className="evaluation-muted">没有自定义 Markdown 报告，当前展示上方的标准摘要与阶段证据。</div>}</section>
            <section className="evaluation-section"><div className="evaluation-section-heading"><div><span className="eyebrow">证据画廊</span><h3>图片证据</h3></div><span className="detail-count">{imageResources.length} 张</span></div>{imageResources.length ? <div className="evaluation-evidence-grid">{imageResources.map((resource) => <div className="evaluation-evidence-card" key={resource.resourceId}><PreviewImage loader={props.previewLoader} resource={resource.previewResource} alt={resource.label} title={resource.label} sourceLabel={evaluationResourceLabel(resource)} onPreview={props.onPreview} /><strong>{evaluationResourceLabel(resource)}</strong><small>{resource.label} · {formatBytes(resource.byteCount)}</small></div>)}</div> : <div className="evaluation-muted">当前 case 没有可预览的图片证据。</div>}</section>
            <EvaluationHistoryView history={props.history} details={props.historyDetails} loader={props.previewLoader} onPreview={props.onPreview} loading={props.historyLoading} detailsLoading={props.historyDetailsLoading} detailsError={props.historyDetailsError} onLoadDetails={props.onLoadHistoryDetails} />
          </>}
        </>}
        {props.error && props.detail && <div className="evaluation-warning" role="status"><AlertTriangle size={14} />{props.error}</div>}
      </div>
    </main>
    <aside className="right-panel panel evaluation-case-panel"><div className="panel-heading"><div><span className="eyebrow">评测批次</span><h2>Cases</h2></div><span className="detail-count">{props.detail?.cases.length || 0}</span></div>{props.detail?.cases.length ? <div className="evaluation-case-list">{props.detail.cases.map((item) => <button type="button" className={'evaluation-case-item ' + (item.caseId === props.selectedCaseId ? 'selected' : '')} key={item.caseId} onClick={() => props.onSelectCase(item.caseId)}><span className={'status-dot ' + evaluationStatusClass(item.status as EvaluationStatus)} /><span><strong>{item.caseId}</strong><small>{item.status}{item.firstFailure?.stage ? ` · ${item.firstFailure.stage}` : ''}</small></span><ChevronRight size={14} /></button>)}</div> : <div className="empty-attachments"><ClipboardList size={19} /><span>暂无可读 case</span><small>评测批次尚未写入完整索引。</small></div>}<div className="details-divider" /><div className="panel-heading compact"><h2>数据边界</h2></div><p className="details-note">此处只读评测 bundle，不会改变普通会话、运行或附件。</p></aside>
  </>
}

function SessionSidebar(props: { sessions: Session[]; activeId: string; onSelect: (id: string) => void; onCreate: () => void; onDelete: (id: string) => void; workspace: 'sessions' | 'evaluations'; onWorkspaceChange: (workspace: 'sessions' | 'evaluations') => void; evaluations: EvaluationSummary[]; activeEvaluationId: string; onSelectEvaluation: (id: string) => void; mode: 'mock' | 'gateway'; runtimeStatus: GatewayRuntimeStatus | null; health: GatewayHealth | null }) {
  const statusUnavailable = props.runtimeStatus?.state === 'unavailable' || props.runtimeStatus?.agentState === 'unavailable' || props.health?.agent?.status === 'unavailable'
  return <aside className="sidebar panel">
    <div className="brand"><div className="brand-mark"><BarChart3 size={19} /></div><div><strong>Figura</strong><span>图表分析工作台</span></div></div>
    <div className="workspace-switcher" role="tablist" aria-label="选择工作区"><button type="button" className={props.workspace === 'sessions' ? 'active' : ''} onClick={() => props.onWorkspaceChange('sessions')} role="tab" aria-selected={props.workspace === 'sessions'}><MessageSquare size={14} />会话</button><button type="button" className={props.workspace === 'evaluations' ? 'active' : ''} onClick={() => props.onWorkspaceChange('evaluations')} role="tab" aria-selected={props.workspace === 'evaluations'}><ClipboardList size={14} />评测</button></div>
    {props.workspace === 'sessions' ? <><div className="section-heading"><div><span className="eyebrow">工作区</span><strong>会话</strong></div><button className="icon-button" onClick={props.onCreate} title="新建会话" aria-label="新建会话"><Plus size={16} /></button></div><div className="session-list">{props.sessions.length ? props.sessions.map((session) => <div key={session.id} className={'session-item ' + (session.id === props.activeId ? 'selected' : '')}><button className="session-select" onClick={() => props.onSelect(session.id)} aria-current={session.id === props.activeId ? 'page' : undefined}><span className="session-dot" /><span className="session-copy"><strong>{session.name}</strong><small>{session.updatedAt}</small></span><span className="session-count">{session.runCount}</span></button><button className="session-more" onClick={() => props.onDelete(session.id)} title={`删除会话：${session.name}`} aria-label={`删除会话：${session.name}`}><Trash2 size={14} /></button></div>) : <div className="session-empty"><MessageSquare size={16} /><span>还没有会话</span><small>新建一个会话开始分析。</small></div>}</div></> : <><div className="section-heading"><div><span className="eyebrow">工作区</span><strong>评测记录</strong></div></div><div className="session-list">{props.evaluations.length ? props.evaluations.map((evaluation) => <button type="button" key={evaluation.evaluationId} className={'evaluation-nav-item ' + (evaluation.evaluationId === props.activeEvaluationId ? 'selected' : '')} onClick={() => props.onSelectEvaluation(evaluation.evaluationId)}><span className={'status-dot ' + evaluationStatusClass(evaluation.status)} /><span className="session-copy"><strong>{evaluation.evaluationId}</strong><small>{evaluationStatusLabel(evaluation.status)} · {evaluation.caseCount} 个 case</small></span><ChevronRight size={14} /></button>) : <div className="session-empty"><ClipboardList size={16} /><span>还没有评测记录</span><small>完成一次真实评测后可在这里查看。</small></div>}</div></>}
    <div className="sidebar-footer"><span className={'status-dot ' + (statusUnavailable ? 'status-error' : '')} />{props.mode === 'gateway' ? 'Gateway 模式' : '模拟模式'} <span className="muted">·</span> {gatewayStatusText(props.mode, props.runtimeStatus, props.health)}</div>
  </aside>
}

function Message(props: { item: ConversationItem; expanded: boolean; onToggle: (id: string) => void; previewLoader?: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const item = props.item
  const associationWarning = (item.kind === 'user' || item.kind === 'assistant') && item.associationStatus === 'legacy_unassociated' ? <span className="message-association-warning">历史关联不完整</span> : null
  if (item.kind === 'user') return <div className="message-row user-row"><div className="avatar user-avatar">我</div><div className="message-body"><div className="message-meta"><strong>你</strong>{associationWarning}<time>{item.timestamp}</time></div><div className="bubble user-bubble">{item.text}{item.attachmentIds?.length ? <div className="inline-attachment"><Paperclip size={13} /> {item.attachmentIds.length} 个附件</div> : null}</div></div></div>
  if (item.kind === 'assistant') return <div className="message-row assistant-row"><div className="avatar agent-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-meta"><strong>Figura Agent</strong>{associationWarning}<time>{item.timestamp}</time></div><div className="bubble assistant-bubble"><SafeMarkdown source={item.text} /><details className="answer-source"><summary>查看原文</summary><pre>{item.text.slice(0, 12000)}</pre></details></div></div></div>
  if (item.kind === 'visual_observation') return <div className="visual-observation"><div className="observation-label"><FileImage size={14} /> <strong>视觉观察</strong><span>{item.toolName}</span></div><PreviewImage loader={props.previewLoader || null} onPreview={props.onPreview} sourceLabel="视觉观察" title={item.caption} resource={item.previewResource} fallbackUrl={item.imageUrl} alt={item.caption} /><small>{item.caption}</small></div>
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
  previewLoader: PreviewResourceLoader | null
  onPreview?: PreviewOpener
  onInterrupt?: () => void
  onRetry?: () => void
  onResume?: () => void
}) {
  const { timeline, user, assistant } = props
  const answer = assistant?.kind === 'assistant' ? assistant.text : timeline.summary.answer || ''
  const answerTimestamp = assistant?.kind === 'assistant' ? assistant.timestamp : timestampLabel(timeline.summary.updatedAt)
  const artifacts = generatedArtifacts(timeline.events)
  return <section className={'run-block run-' + timeline.summary.status}>
    {user && <Message item={user} expanded={props.expandedMessage === user.id} onToggle={props.onToggleMessage} previewLoader={props.previewLoader} onPreview={props.onPreview} />}
    <RunTimeline timeline={timeline} expanded={props.expanded} onToggle={props.onToggleRun} previewLoader={props.previewLoader} onPreview={props.onPreview} onInterrupt={props.onInterrupt} onRetry={props.onRetry} onResume={props.onResume} />
    {(answer || artifacts.length > 0) && <section className="run-result" aria-label="最终结果">
      <div className="run-result-heading"><Sparkles size={14} /><strong>最终结果</strong><span>{answer ? answerTimestamp : '图表输出'}</span></div>
      {answer && <Message item={{ id: `${timeline.summary.runId}:assistant`, kind: 'assistant', text: answer, timestamp: answerTimestamp }} expanded={props.expandedMessage === `${timeline.summary.runId}:assistant`} onToggle={props.onToggleMessage} previewLoader={props.previewLoader} onPreview={props.onPreview} />}
      {artifacts.length > 0 && <div className="run-result-artifacts">{artifacts.map((artifact, index) => <GeneratedChartView key={`${timeline.summary.runId}-artifact-${artifact.artifactId || index}`} artifact={artifact} loader={props.previewLoader} onPreview={props.onPreview} />)}</div>}
    </section>}
  </section>
}

function ConversationPanel(props: { data: SessionData | null; timelines: RunTimeline[]; pendingUser: ConversationItem | null; runState: RunState; selectedAttachmentIds: string[]; activeSourceIds: string[]; provider: Provider; health: GatewayHealth | null; mode: 'mock' | 'gateway'; onProviderChange: (provider: Provider) => void; onSubmit: (text: string, attachmentIds: string[], retryOf?: string, resumeOf?: string) => Promise<boolean>; onInterrupt?: (runId: string) => void; onRetry?: (runId: string) => void; onResume?: (runId: string) => void; loading: boolean; loadingSession: boolean; error: string | null; onToggleRun: (runId: string, status: RunSummary['status']) => void; expandedRuns: Set<string>; previewLoader?: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const previewLoader = props.previewLoader || null
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
  return <main className="conversation panel"><header className="conversation-header"><div className="conversation-title"><span className="eyebrow">当前会话</span><h1>{props.data?.session.name ?? (props.loadingSession ? '正在加载会话' : '暂无活动会话')}</h1>{props.data && <span className="conversation-meta">{props.data.session.runCount} 次运行 · 执行记录保存在本机</span>}</div><div className="conversation-header-actions"><label className="provider-selector"><span>下一次运行</span><select aria-label="选择下一次运行的模型来源" value={props.provider} onChange={(event) => props.onProviderChange(event.target.value as Provider)} disabled={props.loadingSession}>{(['openai', 'qwen', 'deepseek'] as Provider[]).map((provider) => { const status = providerStatus(props.health, provider, props.mode); return <option key={provider} value={provider} disabled={status === 'unavailable'}>{providerLabels[provider]}{status === 'unavailable' ? '（不可用）' : ''}</option> })}</select></label><span className={'run-chip ' + props.runState}><span className="status-dot" />{runStateLabel(props.runState)} · {props.data?.session.runCount ?? 0} 次运行</span></div></header><div className="message-scroll">{props.loadingSession ? <div className="loading-state"><span className="spinner" />正在加载会话...</div> : props.error && !props.data && messages.length === 0 ? <div className="error-state"><div className="empty-icon"><MessageSquare size={22} /></div><h2>无法连接本地服务</h2><p>{props.error}</p></div> : !props.data && messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>创建第一个会话</h2><p>请从左侧新建会话，开始使用 Figura。</p></div> : messages.length === 0 && props.timelines.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><p>提出问题或添加图片，开始使用 Figura。</p></div> : <>{runBlocks.map(({ timeline, user, assistant }) => <RunBlock key={timeline.summary.runId} timeline={timeline} user={user} assistant={assistant} expanded={props.expandedRuns.has(timeline.summary.runId) || timeline.summary.status === 'running'} onToggleRun={() => props.onToggleRun(timeline.summary.runId, timeline.summary.status)} expandedMessage={expanded} onToggleMessage={toggleMessage} previewLoader={previewLoader} onPreview={props.onPreview} onInterrupt={() => props.onInterrupt?.(timeline.summary.runId)} onRetry={() => props.onRetry?.(timeline.summary.runId)} onResume={() => props.onResume?.(timeline.summary.runId)} />)}{orphanMessages.map((item) => <Message key={item.id} item={item} expanded={expanded === item.id} onToggle={toggleMessage} previewLoader={previewLoader} onPreview={props.onPreview} />)}</>}{props.loading && <div className="typing"><span /><span /><span /> Figura Agent 正在思考</div>}{props.error && <div className="error-banner" role="alert">{props.error}</div>}</div><div className="composer"><div className="composer-label"><Sparkles size={13} /><span>向 Figura Agent 提问</span></div><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder="例如：比较这张图中各系列的变化趋势..." rows={1} /><div className="composer-actions"><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" onClick={() => void send()} disabled={!text.trim() || props.loading || props.loadingSession} title="发送消息" aria-label="发送消息"><Send size={16} /> </button></div></div></main>
}

function AttachmentPreview({ attachment, loader, onPreview }: { attachment: Attachment; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const preview = usePreviewResource(loader, attachment.previewResource, attachment.previewUrl)
  const triggerRef = useRef<HTMLButtonElement>(null)
  if (preview.status === 'loading') return <div className="attachment-placeholder preview-placeholder loading-preview"><LoaderCircle className="spin-icon" size={18} /><span>正在加载预览</span></div>
  if (preview.status === 'available' && preview.url && onPreview) return <button ref={triggerRef} type="button" className="preview-trigger attachment-preview-trigger" onClick={() => onPreview({ resource: attachment.previewResource, fallbackUrl: attachment.previewResource ? undefined : attachment.previewUrl, alt: attachment.filename, title: attachment.filename, sourceLabel: '附件', statusLabel: statusLabel(attachment.status), triggerRef })} aria-label={`查看${attachment.filename}大图`} title={`查看${attachment.filename}大图`}><img src={preview.url} alt={attachment.filename} /></button>
  if (preview.status === 'available' && preview.url) return <img src={preview.url} alt={attachment.filename} />
  return <div className="attachment-placeholder preview-placeholder"><FileImage size={24} /><span>{attachment.status === 'unavailable' || preview.status === 'invalid' ? '源文件不可用' : '暂无预览'}</span>{preview.error?.retryable && <button type="button" className="preview-retry" onClick={preview.retry}>重试</button>}</div>
}

function AttachmentPanel(props: { attachments: Attachment[]; pending: PendingAttachment[]; selectedIds: string[]; activeSourceIds: string[]; error: string | null; onAdd: (files: File[]) => void; onToggle: (id: string) => void; onRemovePending: (key: string) => void; onRetryPending: (item: PendingAttachment) => void; onRemove: (attachment: Attachment) => void; previewLoader?: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const previewLoader = props.previewLoader || null
  return <aside className="right-panel panel"><div className="panel-heading"><div><span className="eyebrow">会话数据</span><h2>附件</h2></div><button className="attachment-add" onClick={() => inputRef.current?.click()} title="添加图片"><Plus size={14} />添加图片</button><input ref={inputRef} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple onChange={(event) => { props.onAdd(Array.from(event.currentTarget.files ?? [])); event.currentTarget.value = '' }} /></div>{props.error && <div className="attachment-error" role="alert">{props.error}</div>}{props.activeSourceIds.length > 0 && <div className="details-note">已固定活动源：{props.activeSourceIds.length} 个附件。未勾选新附件的后续消息会继续使用它。</div>}{props.pending.length === 0 && props.attachments.length === 0 ? <div className="empty-attachments"><Paperclip size={19} /><span>暂无附件</span><small>选择图片后会显示在这里。</small></div> : <div className="attachment-list">{props.pending.map((item) => <div className="attachment-card pending-card" key={item.key}><img src={item.previewUrl} alt={item.file.name} /><div className="attachment-info"><strong>{item.file.name}</strong><span>{mediaTypeForFile(item.file).replace('image/', '').toUpperCase()} · {formatBytes(item.file.size)}</span><div className={'attachment-status ' + (item.status === 'error' ? 'error' : '')}>{item.status === 'uploading' ? <><LoaderCircle className="spin-icon" size={12} />正在上传</> : <><X size={12} />{item.error || '上传失败'}</>}</div><div className="attachment-actions">{item.status === 'error' && <button className="small-action" onClick={() => props.onRetryPending(item)} title="重新上传"><RefreshCw size={12} />重试</button>}<button className="small-action" onClick={() => props.onRemovePending(item.key)} title="移除待处理附件"><X size={12} />移除</button></div></div></div>)}{props.attachments.map((attachment) => { const selectable = attachment.status !== 'unavailable'; const selected = props.selectedIds.includes(attachment.id); const active = props.activeSourceIds.includes(attachment.id); return <div className={'attachment-card ' + (selected ? 'selected' : '')} key={attachment.id}><AttachmentPreview attachment={attachment} loader={previewLoader} onPreview={props.onPreview} /><div className="attachment-info"><strong>{attachment.filename}</strong><span>{attachment.mediaType.replace('image/', '').toUpperCase()} · {formatBytes(attachment.byteCount)}</span><div className={'attachment-status ' + (attachment.status === 'unavailable' ? 'error' : '')}><span className="status-dot" />{statusLabel(attachment.status)}{(attachment.previewUrl || attachment.previewResource) && <em>可预览</em>}{active && <em>活动源</em>}</div>{selectable && <label className="attachment-select"><input type="checkbox" checked={selected} onChange={() => props.onToggle(attachment.id)} />附加到下一条消息{selected && <Check size={12} />}</label>}<div className="attachment-actions"><button className="small-action danger-action" onClick={() => props.onRemove(attachment)} title="删除附件"><Trash2 size={13} />删除</button></div></div></div> })}</div>}<div className="details-divider" /><div className="panel-heading compact"><h2>执行详情</h2><span className="detail-count">{props.attachments.length ? `${props.attachments.length} 个附件` : '—'}</span></div><p className="details-note">工具活动和视觉观察会在后续运行中显示。</p></aside>
}

export default function App() {
  const mode = import.meta.env.VITE_CHARTAGENT_MODE === 'gateway' ? 'gateway' : 'mock'
  const client: ChartAgentClient = useMemo(() => mode === 'gateway' ? gatewayClient : mockClient, [mode])
  const [workspace, setWorkspace] = useState<'sessions' | 'evaluations'>('sessions')
  const [runtimeStatus, setRuntimeStatus] = useState<GatewayRuntimeStatus | null>(null)
  const [gatewayHealth, setGatewayHealth] = useState<GatewayHealth | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [data, setData] = useState<SessionData | null>(null)
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [activeSourceIds, setActiveSourceIds] = useState<string[]>([])
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
  const [gatewayUrl, setGatewayUrl] = useState(() => currentGatewayBaseUrl())
  const [gatewayReady, setGatewayReady] = useState(mode !== 'gateway')
  const [provider, setProvider] = useState<Provider>('openai')
  const [activePreview, setActivePreview] = useState<PreviewDescriptor | null>(null)
  const [evaluations, setEvaluations] = useState<EvaluationSummary[]>([])
  const [activeEvaluationId, setActiveEvaluationId] = useState('')
  const [evaluationDetail, setEvaluationDetail] = useState<EvaluationDetail | null>(null)
  const [evaluationCaseId, setEvaluationCaseId] = useState('')
  const [evaluationCase, setEvaluationCase] = useState<EvaluationCaseData | null>(null)
  const [evaluationHistory, setEvaluationHistory] = useState<EvaluationHistory | null>(null)
  const [evaluationHistoryDetails, setEvaluationHistoryDetails] = useState<EvaluationHistoryDetails | null>(null)
  const [evaluationLoading, setEvaluationLoading] = useState(false)
  const [evaluationCaseLoading, setEvaluationCaseLoading] = useState(false)
  const [evaluationHistoryLoading, setEvaluationHistoryLoading] = useState(false)
  const [evaluationHistoryDetailsLoading, setEvaluationHistoryDetailsLoading] = useState(false)
  const [evaluationHistoryDetailsError, setEvaluationHistoryDetailsError] = useState<string | null>(null)
  const [evaluationError, setEvaluationError] = useState<string | null>(null)
  const [evaluationStale, setEvaluationStale] = useState(false)
  const activeIdRef = useRef(activeId)
  const localPreviews = useRef(new Map<string, string>())
  const subscriptionRef = useRef<RunSubscription | null>(null)
  const activeRunRef = useRef<{ sessionId: string; runId: string; idempotencyKey: string; lastSequence: number; text: string; attachmentIds: string[]; provider: Provider } | null>(null)
  const runRequestsRef = useRef(new Map<string, { text: string; attachmentIds: string[] }>())
  const previewLoader = useMemo(
    () => mode === 'gateway' ? createGatewayPreviewLoader(gatewayUrl) : null,
    [mode, gatewayUrl],
  )

  useEffect(() => { activeIdRef.current = activeId }, [activeId])
  useEffect(() => { setActivePreview(null) }, [activeId])
  useEffect(() => {
    if (!activeId) return
    const stored = window.localStorage.getItem(`figura.provider.${activeId}`)
    if (stored === 'openai' || stored === 'qwen' || stored === 'deepseek') setProvider(stored)
    else if (data?.session.id === activeId && data.runs.length > 0) {
      const latest = [...data.runs].reverse().find((run) => run.provider)
      if (latest?.provider) setProvider(latest.provider)
      else if (gatewayHealth?.agent?.provider === 'qwen') setProvider('qwen')
      else if (gatewayHealth?.agent?.provider === 'deepseek') setProvider('deepseek')
      else setProvider('openai')
    }
    else if (gatewayHealth?.agent?.provider === 'qwen') setProvider('qwen')
    else if (gatewayHealth?.agent?.provider === 'deepseek') setProvider('deepseek')
    else setProvider('openai')
  }, [activeId, data, gatewayHealth])
  useEffect(() => () => { subscriptionRef.current?.close(); localPreviews.current.forEach((url) => URL.revokeObjectURL(url)); localPreviews.current.clear() }, [])
  useEffect(() => {
    if (mode !== 'gateway') return
    let current = true
    void getGatewayRuntimeStatus().then((status) => {
      if (!current) return null
      const effectiveUrl = configureGatewayBaseUrl(status?.url || currentGatewayBaseUrl())
      setGatewayUrl(effectiveUrl)
      setRuntimeStatus(status)
      setGatewayReady(true)
      return gatewayClient.getHealth()
    }).then((health) => {
      if (!current) return
      if (!health) return
      setGatewayHealth(health)
      if (health.agent?.status === 'unavailable') {
        setError(toUserMessage(new GatewayClientError('agent_unavailable', 'Agent service is unavailable', 503, health.agent.reason)))
      }
    }).catch((reason) => { if (current) setError(toUserMessage(reason)) })
    return () => { current = false }
  }, [mode])

  const withLocalPreviews = (value: SessionData): SessionData => ({ ...value, attachments: value.attachments.map((attachment) => ({ ...attachment, previewUrl: attachment.previewUrl || localPreviews.current.get(attachment.id) || '' })) })

  useEffect(() => {
    if (!gatewayReady) return
    setLoadingSession(true)
    client.listSessions().then((items) => { setSessions(items); setActiveId(items[0]?.id ?? '') }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false))
  }, [client, gatewayReady])

  const loadEvaluationCatalog = async (preserve = true) => {
    try {
      const items = await client.listEvaluations()
      setEvaluations(items)
      setEvaluationStale(false)
      setEvaluationError(null)
      setActiveEvaluationId((current) => items.some((item) => item.evaluationId === current) ? current : items[0]?.evaluationId || '')
    } catch (reason) {
      setEvaluationStale(preserve)
      setEvaluationError(toUserMessage(reason))
    }
  }

  useEffect(() => {
    if (!gatewayReady) return
    void loadEvaluationCatalog()
  }, [client, gatewayReady])

  useEffect(() => {
    if (!gatewayReady || workspace !== 'evaluations' || !activeEvaluationId) {
      setEvaluationDetail(null)
      setEvaluationCase(null)
      setEvaluationHistory(null)
      setEvaluationHistoryDetails(null)
      setEvaluationHistoryDetailsError(null)
      return
    }
    let current = true
    setEvaluationLoading(true)
    setEvaluationError(null)
    void client.getEvaluation(activeEvaluationId).then((detail) => {
      if (!current) return
      setEvaluationDetail(detail)
      setEvaluationCaseId((caseId) => detail.cases.some((item) => item.caseId === caseId) ? caseId : detail.cases[0]?.caseId || '')
    }).catch((reason) => { if (current) setEvaluationError(toUserMessage(reason)) }).finally(() => { if (current) setEvaluationLoading(false) })
    return () => { current = false }
  }, [activeEvaluationId, client, gatewayReady, workspace])

  useEffect(() => {
    if (!gatewayReady || workspace !== 'evaluations' || !activeEvaluationId || !evaluationCaseId) {
      setEvaluationCase(null)
      setEvaluationHistory(null)
      setEvaluationHistoryDetails(null)
      setEvaluationHistoryDetailsError(null)
      return
    }
    let current = true
    setEvaluationCaseLoading(true)
    setEvaluationHistoryLoading(true)
    setEvaluationHistoryDetails(null)
    setEvaluationHistoryDetailsError(null)
    setEvaluationError(null)
    void client.getEvaluationCase(activeEvaluationId, evaluationCaseId).then((value) => {
      if (current) setEvaluationCase(value)
    }).catch((reason) => { if (current) setEvaluationError(toUserMessage(reason)) }).finally(() => { if (current) setEvaluationCaseLoading(false) })
    void client.getEvaluationHistory(activeEvaluationId, evaluationCaseId).then((value) => {
      if (current) setEvaluationHistory(value)
    }).catch(() => {
      if (current) setEvaluationHistory(null)
    }).finally(() => { if (current) setEvaluationHistoryLoading(false) })
    return () => { current = false }
  }, [activeEvaluationId, client, evaluationCaseId, gatewayReady, workspace])

  const loadEvaluationHistoryDetails = async () => {
    if (!activeEvaluationId || !evaluationCaseId || workspace !== 'evaluations') return
    setEvaluationHistoryDetailsLoading(true)
    setEvaluationHistoryDetailsError(null)
    try {
      const details = await client.getEvaluationHistoryDetails(activeEvaluationId, evaluationCaseId)
      setEvaluationHistoryDetails(details)
    } catch (reason) {
      setEvaluationHistoryDetailsError(toUserMessage(reason))
    } finally {
      setEvaluationHistoryDetailsLoading(false)
    }
  }

  const refreshEvaluation = async () => {
    await loadEvaluationCatalog()
    if (!activeEvaluationId || workspace !== 'evaluations') return
    try {
      const detail = await client.getEvaluation(activeEvaluationId)
      setEvaluationDetail(detail)
      const caseId = evaluationCaseId || detail.cases[0]?.caseId || ''
      if (caseId) setEvaluationCaseId(caseId)
      setEvaluationStale(false)
    } catch (reason) {
      setEvaluationStale(true)
      setEvaluationError(toUserMessage(reason))
    }
  }

  const selectedEvaluation = evaluations.find((item) => item.evaluationId === activeEvaluationId)
  useEffect(() => {
    if (workspace !== 'evaluations' || !activeEvaluationId || selectedEvaluation?.status !== 'running') return
    const timer = window.setInterval(() => {
      void refreshEvaluation()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [activeEvaluationId, selectedEvaluation?.status, workspace])
  useEffect(() => {
    if (!activeId) { setData(null); setTimelines([]); return }
    setData(null)
    setTimelines([])
    setLoadingSession(true)
    void client.getSession(activeId).then(async (value) => {
      if (activeIdRef.current !== activeId) return
      setData(withLocalPreviews(value))
      setActiveSourceIds((value.activeSourceAttachmentIds || []).filter((id) => value.attachments.some((attachment) => attachment.id === id)))
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
          const runId = current.summary.runId
          setRunState('running')
          setLoading(true)
          const cursor = Math.max(...current.events.map((event) => event.sequence), 0)
          activeRunRef.current = { sessionId: activeId, runId, idempotencyKey: '', lastSequence: cursor, text: '', attachmentIds: [], provider: current.summary.provider || 'openai' }
          let reconnectAttempts = 0
          let reconnectTimer: number | undefined
          const applyHydratedHistory = (history: Awaited<ReturnType<ChartAgentClient['getRunHistory']>>) => {
            setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, summary: history.run, events: mergeEvents(item.events, history.events), historyGap: item.historyGap || history.historyGap } : item))
            const latest = Math.max(...history.events.map((event) => event.sequence), 0)
            if (activeRunRef.current?.runId === runId) activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, latest)
          }
          const finishHydrated = async (history: Awaited<ReturnType<ChartAgentClient['getRunHistory']>>) => {
            applyHydratedHistory(history)
            if (history.run.status === 'running') return false
            setPendingUser(null)
            setRunState(history.run.status === 'interrupted' ? 'interrupted' : history.run.status === 'failed' ? 'failed' : 'completed')
            setLoading(false)
            activeRunRef.current = null
            try {
              const updated = await client.getSession(activeId)
              if (activeIdRef.current === activeId) {
                setData(withLocalPreviews(updated))
                setSessions((items) => items.map((item) => item.id === updated.session.id ? updated.session : item))
              }
            } catch { /* The durable run history remains visible if refresh fails. */ }
            return true
          }
          const scheduleHydratedReconnect = (reason: Error) => {
            if (activeIdRef.current !== activeId) return
            if (reconnectAttempts >= 5) {
              setRunState('unavailable')
              setLoading(false)
              setError(toUserMessage(reason))
              return
            }
            reconnectAttempts += 1
            setRunState('reconnecting')
            const backoff = Math.min(8000, 400 * (2 ** (reconnectAttempts - 1))) + Math.floor(Math.random() * 200)
            reconnectTimer = window.setTimeout(() => {
              const nextCursor = activeRunRef.current?.runId === runId ? activeRunRef.current.lastSequence : cursor
              connectHydrated(nextCursor)
            }, backoff)
          }
          const connectHydrated = (afterSequence: number) => {
            if (activeIdRef.current !== activeId) return
            subscriptionRef.current = client.subscribeRun(activeId, runId, {
              onEvent(event) {
                if (activeIdRef.current !== activeId) return
                if (event.kind === 'history_gap') {
                  setRunState('history-gap')
                  setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, historyGap: true } : item))
                  return
                }
                if (activeRunRef.current?.runId === runId) activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, event.sequence)
                if (event.kind === 'run_interrupted') { setRunState('interrupted'); setLoading(false) }
                else if (event.kind === 'run_failed') { setRunState('failed'); setLoading(false) }
                setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, events: mergeEvents(item.events, [event]), summary: { ...item.summary, eventCount: Math.max(item.summary.eventCount, event.sequence), updatedAt: event.timestamp } } : item))
              },
              async onError(reason) {
                if (activeIdRef.current !== activeId) return
                try {
                  const nextCursor = activeRunRef.current?.runId === runId ? activeRunRef.current.lastSequence : afterSequence
                  const history = await client.getRunHistory(activeId, runId, nextCursor)
                  if (await finishHydrated(history)) return
                } catch { /* A later reconnect will retry the durable cursor read. */ }
                scheduleHydratedReconnect(reason)
              },
              onComplete() {
                subscriptionRef.current = null
                if (activeIdRef.current !== activeId) return
                const nextCursor = activeRunRef.current?.runId === runId ? activeRunRef.current.lastSequence : afterSequence
                void client.getRunHistory(activeId, runId, nextCursor).then((history) => finishHydrated(history)).catch((reason) => scheduleHydratedReconnect(reason))
              },
            }, afterSequence)
          }
          connectHydrated(cursor)
        } else {
          activeRunRef.current = null
          setRunState('idle')
          setLoading(false)
        }
      }
    }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false))
  }, [activeId, client, gatewayReady])

  const clearPending = () => { pending.forEach((item) => URL.revokeObjectURL(item.previewUrl)); setPending([]) }
  const selectSession = (id: string) => { subscriptionRef.current?.close(); subscriptionRef.current = null; activeRunRef.current = null; runRequestsRef.current.clear(); clearPending(); setSelectedIds([]); setActiveSourceIds([]); setPendingUser(null); setTimelines([]); setExpandedRuns(new Set()); setRunState('idle'); setAttachmentError(null); setError(null); setActiveId(id) }
  const create = async () => { setNewSessionName(''); setCreatingSession(true) }
  const confirmCreate = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const name = newSessionName.trim(); if (!name) return; setError(null); try { subscriptionRef.current?.close(); subscriptionRef.current = null; clearPending(); setSelectedIds([]); setActiveSourceIds([]); setPendingUser(null); setTimelines([]); setRunState('idle'); const created = await client.createSession(name); setSessions(await client.listSessions()); setActiveId(created.session.id); setCreatingSession(false) } catch (reason) { setError(toUserMessage(reason)) } }

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
        setActiveSourceIds((ids) => ids.filter((id) => id !== action.attachment.id))
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

  const submit = async (text: string, attachmentIds: string[], retryOf?: string, resumeOf?: string): Promise<boolean> => {
    if (!activeId) return false
    const sessionId = activeId
    const effectiveAttachmentIds = attachmentIds.length > 0 ? [...attachmentIds] : [...activeSourceIds]
    subscriptionRef.current?.close()
    setLoading(true)
    setRunState('connecting')
    setError(null)
    setSelectedIds([])
    const idempotencyKey = newIdempotencyKey()
    const startOptions = { idempotencyKey, ...(retryOf ? { retryOf } : {}) }
    try {
      const selectedStatus = providerStatus(gatewayHealth, provider, mode)
      if (selectedStatus !== 'ready') {
        setError(selectedStatus === 'unavailable'
          ? `${providerLabels[provider]}当前不可用，请切换来源或检查 Gateway 配置。`
          : '正在确认 Gateway 的模型来源状态，请稍后重试。')
        setRunState('unavailable')
        setLoading(false)
        return false
      }
      let handle
      try {
        handle = resumeOf
          ? await client.resumeRun(sessionId, resumeOf, { idempotencyKey })
          : await client.startRun(sessionId, text, effectiveAttachmentIds, provider, startOptions)
      } catch (firstError) {
        // A lost acknowledgement can mean the Gateway accepted the run. One
        // keyed recovery request is safe and lets the Gateway return it.
        try {
          handle = resumeOf
            ? await client.resumeRun(sessionId, resumeOf, { idempotencyKey })
            : await client.startRun(sessionId, text, effectiveAttachmentIds, provider, startOptions)
        } catch {
          throw firstError
        }
      }
      if (attachmentIds.length > 0) setActiveSourceIds([...attachmentIds])
      window.localStorage.setItem(`figura.provider.${sessionId}`, provider)
      if (activeIdRef.current !== sessionId) return false
      activeRunRef.current = { sessionId, runId: handle.runId, idempotencyKey, lastSequence: 0, text, attachmentIds: [...effectiveAttachmentIds], provider }
      runRequestsRef.current.set(handle.runId, { text, attachmentIds: [...effectiveAttachmentIds] })
      setPendingUser({ id: `${handle.runId}:user`, kind: 'user', text, timestamp: currentTime(), attachmentIds: effectiveAttachmentIds.length ? effectiveAttachmentIds : undefined })
      setRunState(handle.status === 'running' ? 'running' : handle.status === 'interrupted' ? 'interrupted' : handle.status === 'failed' ? 'failed' : 'completed')
      const startedAt = new Date().toISOString()
      setTimelines((current) => current.some((item) => item.summary.runId === handle.runId) ? current : [...current, { summary: { runId: handle.runId, sessionId, status: handle.status, createdAt: startedAt, updatedAt: startedAt, eventCount: 0, provider: handle.provider || provider, model: handle.model, retryOf: handle.retryOf, parentRunId: handle.parentRunId, rootRunId: handle.rootRunId, continuationKind: handle.continuationKind, recovery: handle.recovery }, events: [], historyGap: false }])
      let reconnectAttempts = 0
      let reconnectTimer: number | undefined
      const applyHistory = (history: Awaited<ReturnType<ChartAgentClient['getRunHistory']>>) => {
        setTimelines((current) => current.map((item) => item.summary.runId === handle.runId ? { summary: history.run, events: mergeEvents(item.events, history.events), historyGap: item.historyGap || history.historyGap } : item))
        const latest = Math.max(...history.events.map((event) => event.sequence), 0)
        if (activeRunRef.current?.runId === handle.runId) activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, latest)
        return history
      }
      const finishFromHistory = async (history: Awaited<ReturnType<ChartAgentClient['getRunHistory']>>) => {
        applyHistory(history)
        if (history.run.status === 'interrupted') setRunState('interrupted')
        else if (history.run.status === 'failed') setRunState('failed')
        else if (history.run.status === 'completed') setRunState('completed')
        setLoading(false)
        setPendingUser(null)
        if (history.run.status !== 'running') {
          activeRunRef.current = null
          try {
            const updated = await client.getSession(sessionId)
            if (activeIdRef.current === sessionId) {
              setData(withLocalPreviews(updated))
              setSessions((items) => items.map((item) => item.id === updated.session.id ? updated.session : item))
            }
          } catch { /* The run history remains visible if the session refresh fails. */ }
        }
        return history.run.status !== 'running'
      }
      const scheduleReconnect = (reason: Error) => {
        if (activeIdRef.current !== sessionId) return
        if (reconnectAttempts >= 5) {
          setRunState('unavailable')
          setLoading(false)
          setError(toUserMessage(reason))
          return
        }
        reconnectAttempts += 1
        setRunState('reconnecting')
        const backoff = Math.min(8000, 400 * (2 ** (reconnectAttempts - 1))) + Math.floor(Math.random() * 200)
        reconnectTimer = window.setTimeout(() => {
          const cursor = activeRunRef.current?.runId === handle.runId ? activeRunRef.current.lastSequence : 0
          connect(cursor)
        }, backoff)
      }
      const connect = (afterSequence = activeRunRef.current?.lastSequence || 0) => {
        subscriptionRef.current = client.subscribeRun(sessionId, handle.runId, {
          onEvent(event) {
            if (activeIdRef.current !== sessionId) return
            if (event.kind === 'history_gap') {
              setRunState('history-gap')
              setTimelines((current) => current.map((item) => item.summary.runId === handle.runId ? { ...item, historyGap: true } : item))
              return
            }
            if (activeRunRef.current?.runId === handle.runId) activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, event.sequence)
            if (event.kind === 'run_failed') {
              setRunState('failed')
              setLoading(false)
              setError(toUserMessage(new GatewayClientError(String(event.payload.code || 'agent_failed'), String(event.payload.message || 'Agent 执行失败'), 502, typeof event.payload.reason === 'string' ? event.payload.reason : undefined)))
            } else if (event.kind === 'run_interrupted') {
              setRunState('interrupted')
              setLoading(false)
            } else if (event.kind !== 'run_started') setRunState('running')
            setTimelines((current) => current.map((item) => item.summary.runId === handle.runId ? { ...item, events: mergeEvents(item.events, [event]), summary: { ...item.summary, eventCount: Math.max(item.summary.eventCount, event.sequence), updatedAt: event.timestamp }, historyGap: item.historyGap || event.kind === 'history_gap' } : item))
          },
          async onError(reason) {
            if (activeIdRef.current !== sessionId) return
            try {
              const cursor = activeRunRef.current?.runId === handle.runId ? activeRunRef.current.lastSequence : afterSequence
              const history = await client.getRunHistory(sessionId, handle.runId, cursor)
              if (await finishFromHistory(history)) return
              scheduleReconnect(reason)
            } catch {
              scheduleReconnect(reason)
            }
          },
          onComplete() {
            subscriptionRef.current = null
            if (activeIdRef.current !== sessionId) return
            void client.getRunHistory(sessionId, handle.runId, activeRunRef.current?.lastSequence || 0).then((history) => finishFromHistory(history)).catch((reason) => { setRunState('unavailable'); setLoading(false); setError(toUserMessage(reason)) })
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

  const interruptRun = async (runId: string) => {
    const sessionId = activeIdRef.current
    if (!sessionId) return
    setRunState('cancel_requested')
    setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, summary: { ...item.summary, cancelRequested: true } } : item))
    try {
      const handle = await client.interruptRun(sessionId, runId)
      setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, summary: { ...item.summary, status: handle.status, terminalCode: handle.terminalCode, terminalMessage: handle.terminalMessage, cancelRequested: true, updatedAt: new Date().toISOString() } } : item))
      if (handle.status === 'interrupted') { setRunState('interrupted'); setLoading(false) }
    } catch (reason) {
      setRunState('running')
      setError(toUserMessage(reason))
    }
  }

  const retryRun = async (runId: string) => {
    const timeline = timelines.find((item) => item.summary.runId === runId)
    if (!timeline) return
    const request = runRequestsRef.current.get(runId)
    const storedUser = data?.messages.find((item) => item.id === `${runId}:user`)
    const activeUser = pendingUser?.id === `${runId}:user` ? pendingUser : undefined
    const user = activeUser || storedUser || (request ? { id: `${runId}:user`, kind: 'user' as const, text: request.text, timestamp: currentTime(), attachmentIds: request.attachmentIds } : undefined)
    if (!user || user.kind !== 'user') {
      setError('这条运行缺少原始请求，暂时无法自动重试。')
      return
    }
    await submit(user.text, user.attachmentIds || [], runId)
  }

  const resumeRun = async (runId: string) => {
    const timeline = timelines.find((item) => item.summary.runId === runId)
    if (!timeline || timeline.summary.recovery?.status !== 'available') return
    const request = runRequestsRef.current.get(runId)
    const storedUser = data?.messages.find((item) => item.id === `${runId}:user`)
    const user = storedUser || (request ? { id: `${runId}:user`, kind: 'user' as const, text: request.text, timestamp: currentTime(), attachmentIds: request.attachmentIds } : undefined)
    if (!user || user.kind !== 'user') {
      setError('这条运行缺少原始请求，暂时无法继续执行。')
      return
    }
    await submit(user.text, user.attachmentIds || [], undefined, runId)
  }

  const toggleRun = (runId: string, status: RunSummary['status']) => setExpandedRuns((current) => { const next = new Set(current); if (status === 'running') { next.has(runId) ? next.delete(runId) : next.add(runId) } else { next.has(runId) ? next.delete(runId) : next.add(runId) } return next })
  const changeProvider = (next: Provider) => { setProvider(next); if (activeId) window.localStorage.setItem(`figura.provider.${activeId}`, next); if (loading) setError('当前运行不会切换来源，新选择将应用于下一次运行。') }
  const selectEvaluation = (id: string) => { setWorkspace('evaluations'); setActiveEvaluationId(id); setEvaluationCaseId(''); setActivePreview(null); setEvaluationError(null) }
  const changeWorkspace = (next: 'sessions' | 'evaluations') => {
    setWorkspace(next)
    setActivePreview(null)
    if (next === 'evaluations' && !activeEvaluationId && evaluations[0]) setActiveEvaluationId(evaluations[0].evaluationId)
  }
  return <><div className="app-shell"><SessionSidebar sessions={sessions} activeId={activeId} onSelect={selectSession} onCreate={create} onDelete={requestDeleteSession} workspace={workspace} onWorkspaceChange={changeWorkspace} evaluations={evaluations} activeEvaluationId={activeEvaluationId} onSelectEvaluation={selectEvaluation} mode={mode} runtimeStatus={runtimeStatus} health={gatewayHealth} />{workspace === 'evaluations' ? <EvaluationPanel evaluations={evaluations} detail={evaluationDetail} caseData={evaluationCase} history={evaluationHistory} historyDetails={evaluationHistoryDetails} selectedEvaluationId={activeEvaluationId} selectedCaseId={evaluationCaseId} loading={evaluationLoading} caseLoading={evaluationCaseLoading} historyLoading={evaluationHistoryLoading} historyDetailsLoading={evaluationHistoryDetailsLoading} historyDetailsError={evaluationHistoryDetailsError} error={evaluationError} stale={evaluationStale} onRefresh={() => void refreshEvaluation()} onSelectCase={(id) => { setEvaluationCaseId(id); setEvaluationError(null) }} onLoadHistoryDetails={() => void loadEvaluationHistoryDetails()} previewLoader={previewLoader} onPreview={setActivePreview} /> : <><ConversationPanel data={data} timelines={timelines} pendingUser={pendingUser} runState={runState} selectedAttachmentIds={selectedIds} activeSourceIds={activeSourceIds} provider={provider} health={gatewayHealth} mode={mode} onProviderChange={changeProvider} onSubmit={submit} onInterrupt={(runId) => void interruptRun(runId)} onRetry={(runId) => void retryRun(runId)} onResume={(runId) => void resumeRun(runId)} loading={loading} loadingSession={loadingSession} error={error} onToggleRun={toggleRun} expandedRuns={expandedRuns} previewLoader={previewLoader} onPreview={setActivePreview} /><AttachmentPanel attachments={data?.attachments ?? []} pending={pending} selectedIds={selectedIds} activeSourceIds={activeSourceIds} error={attachmentError} onAdd={addFiles} onToggle={toggleAttachment} onRemovePending={removePending} onRetryPending={(item) => void uploadPending(item)} onRemove={requestDeleteAttachment} previewLoader={previewLoader} onPreview={setActivePreview} /></>}</div>{activePreview && <InteractivePreview preview={activePreview} loader={previewLoader} onClose={() => setActivePreview(null)} />}{creatingSession && <div className="dialog-backdrop"><form className="session-dialog" onSubmit={(event) => void confirmCreate(event)}><h2>新建会话</h2><label htmlFor="session-name">会话名称</label><input id="session-name" value={newSessionName} onChange={(event) => setNewSessionName(event.target.value)} placeholder="例如：季度销售分析" autoFocus /><div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={() => setCreatingSession(false)}>取消</button><button type="submit" className="dialog-primary" disabled={!newSessionName.trim()}>创建会话</button></div></form></div>}{confirmAction && <div className="dialog-backdrop"><div className="session-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title"><h2 id="delete-dialog-title">{confirmAction.kind === 'session' ? '删除会话？' : '删除附件？'}</h2><p className="dialog-message">{confirmAction.kind === 'session' ? `将永久删除“${confirmAction.session.name}”及其运行记录和附件。` : `将删除“${confirmAction.attachment.filename}”及其源文件。`}</p><div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={() => setConfirmAction(null)} disabled={deleting}>取消</button><button type="button" className="dialog-danger" onClick={() => void confirmDelete()} disabled={deleting}><Trash2 size={13} />{deleting ? '正在删除' : '确认删除'}</button></div></div></div>}</>
}

function toUserMessage(error: unknown): string {
  if (error instanceof GatewayClientError) {
    if (error.code === 'gateway_unavailable') return '无法连接到本地 Gateway，请先启动 Python 服务。'
    if (error.code === 'agent_unavailable' && error.reason === 'missing_configuration') return 'Agent 未配置，请检查项目根目录 .env 中的模型配置。'
    if (error.code === 'agent_unavailable' && error.reason === 'invalid_configuration') return 'Agent 配置无效，请检查模型地址和参数。'
    if (error.code === 'agent_unavailable') return 'Agent 当前不可用，请稍后重试。'
    if (error.code === 'invalid_provider') return '模型来源不受支持，请重新选择 OpenAI 或 Qwen。'
    if (error.code === 'idempotency_conflict') return '请求标识已对应其他内容，请重新提交。'
    if (error.code === 'run_not_terminal') return '运行尚未结束，暂时不能重试。'
    if (error.code === 'recovery_blocked') return error.reason === 'operation_outcome_uncertain' ? '运行在一个操作边界中断，结果无法安全确认，请使用“重试本次运行”。' : '该运行暂时无法继续执行，请使用“重试本次运行”。'
    if (error.code === 'recovery_unavailable' || error.code === 'checkpoint_expired' || error.code === 'unsupported_checkpoint_version') return '该运行没有可用的继续执行检查点，请使用“重试本次运行”。'
    if (error.code === 'resume_idempotency_conflict') return '恢复请求标识已对应其他恢复操作，请重新点击继续执行。'
    if (error.code === 'history_gap') return '执行历史存在缺口，当前只能查看已保留部分。'
    if (error.code === 'session_not_found') return '会话不存在，可能已被删除。'
    if (error.code === 'session_exists') return '会话名称已存在，请换一个名称。'
    if (error.code === 'session_busy') return '会话正在运行 Agent，请等待本次运行结束后再删除。'
    if (error.code === 'run_unavailable' || error.code === 'event_history_unavailable') return '这条执行记录已不可用，当前只保留可恢复的会话内容。'
    if (error.code === 'evaluation_not_found') return '评测批次不存在，可能已经被移除。'
    if (error.code === 'evaluation_case_not_found') return '评测 case 不存在或尚未写入索引。'
    if (error.code === 'evaluation_history_unavailable') return '该 case 的运行历史暂时不可读，但阶段摘要仍可查看。'
    if (error.code === 'evaluation_resource_not_found' || error.code === 'evaluation_resource_unavailable') return '评测证据不存在、已过期或暂时不可用。'
    if (error.code === 'evaluation_not_ready') return '评测批次仍在写入，请稍后刷新。'
    if (error.code === 'evaluation_schema_invalid' || error.code === 'evaluation_schema_unsupported') return '评测批次格式不受支持，已保留其它可用记录。'
    if (error.code === 'source_binding_required') return '当前会话有多个活动源，请在右侧勾选要使用的附件后重试。'
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
