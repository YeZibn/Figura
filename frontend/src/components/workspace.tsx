import { useRef, useState } from 'react'
import { BarChart3, Check, ChevronDown, ChevronRight, ClipboardList, FileImage, LoaderCircle, MessageSquare, Paperclip, Plus, RefreshCw, Send, Sparkles, Terminal, Trash2, X } from 'lucide-react'
import { formatBytes, mediaTypeForFile } from '../attachments'
import { evaluationStatusClass, evaluationStatusLabel, gatewayStatusText, providerLabels, providerStatus, runStateLabel, statusLabel, timestampLabel, toolStatusLabel } from '../domain/display'
import { generatedArtifacts, type RunTimeline as RunTimelineModel } from '../domain/run/timeline'
import { usePreviewResource } from '../previewResources'
import type { GatewayRuntimeStatus } from '../runtime'
import type { PreviewResourceLoader } from '../previewResources'
import type { Attachment, ConversationItem, EvaluationSummary, GatewayHealth, Provider, RunState, RunSummary, Session, SessionData } from '../types/protocol'
import type { PreviewOpener, PendingAttachment } from './types'
import { PreviewImage, GeneratedChartView } from './preview'
import { SafeMarkdown } from './common'
import { RunTimeline } from './run'

export function SessionSidebar(props: { sessions: Session[]; activeId: string; onSelect: (id: string) => void; onCreate: () => void; onDelete: (id: string) => void; workspace: 'sessions' | 'evaluations'; onWorkspaceChange: (workspace: 'sessions' | 'evaluations') => void; evaluations: EvaluationSummary[]; activeEvaluationId: string; onSelectEvaluation: (id: string) => void; mode: 'mock' | 'gateway'; runtimeStatus: GatewayRuntimeStatus | null; health: GatewayHealth | null }) {
  const statusUnavailable = props.runtimeStatus?.state === 'unavailable' || props.runtimeStatus?.agentState === 'unavailable' || props.health?.agent?.status === 'unavailable'
  return <aside className="sidebar panel">
    <div className="brand"><div className="brand-mark"><BarChart3 size={19} /></div><div><strong>Figura</strong><span>图表分析工作台</span></div></div>
    <div className="workspace-switcher" role="tablist" aria-label="选择工作区"><button type="button" className={props.workspace === 'sessions' ? 'active' : ''} onClick={() => props.onWorkspaceChange('sessions')} role="tab" aria-selected={props.workspace === 'sessions'}><MessageSquare size={14} />会话</button><button type="button" className={props.workspace === 'evaluations' ? 'active' : ''} onClick={() => props.onWorkspaceChange('evaluations')} role="tab" aria-selected={props.workspace === 'evaluations'}><ClipboardList size={14} />评测</button></div>
    {props.workspace === 'sessions' ? <><div className="section-heading"><div><span className="eyebrow">工作区</span><strong>会话</strong></div><button className="icon-button" onClick={props.onCreate} title="新建会话" aria-label="新建会话"><Plus size={16} /></button></div><div className="session-list">{props.sessions.length ? props.sessions.map((session) => <div key={session.id} className={'session-item ' + (session.id === props.activeId ? 'selected' : '')}><button className="session-select" onClick={() => props.onSelect(session.id)} aria-current={session.id === props.activeId ? 'page' : undefined}><span className="session-dot" /><span className="session-copy"><strong>{session.name}</strong><small>{session.updatedAt}</small></span><span className="session-count">{session.runCount}</span></button><button className="session-more" onClick={() => props.onDelete(session.id)} title={`删除会话：${session.name}`} aria-label={`删除会话：${session.name}`}><Trash2 size={14} /></button></div>) : <div className="session-empty"><MessageSquare size={16} /><span>还没有会话</span><small>新建一个会话开始分析。</small></div>}</div></> : <><div className="section-heading"><div><span className="eyebrow">工作区</span><strong>评测记录</strong></div></div><div className="session-list">{props.evaluations.length ? props.evaluations.map((evaluation) => <button type="button" key={evaluation.evaluationId} className={'evaluation-nav-item ' + (evaluation.evaluationId === props.activeEvaluationId ? 'selected' : '')} onClick={() => props.onSelectEvaluation(evaluation.evaluationId)}><span className={'status-dot ' + evaluationStatusClass(evaluation.status)} /><span className="session-copy"><strong>{evaluation.evaluationId}</strong><small>{evaluationStatusLabel(evaluation.status)} · {evaluation.caseCount} 个 case</small></span><ChevronRight size={14} /></button>) : <div className="session-empty"><ClipboardList size={16} /><span>还没有评测记录</span><small>完成一次真实评测后可在这里查看。</small></div>}</div></>}
    <div className="sidebar-footer"><span className={'status-dot ' + (statusUnavailable ? 'status-error' : '')} />{props.mode === 'gateway' ? 'Gateway 模式' : '模拟模式'} <span className="muted">·</span> {gatewayStatusText(props.mode, props.runtimeStatus, props.health)}</div>
  </aside>
}

export function Message(props: { item: ConversationItem; expanded: boolean; onToggle: (id: string) => void; previewLoader?: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const item = props.item
  const associationWarning = (item.kind === 'user' || item.kind === 'assistant') && item.associationStatus === 'legacy_unassociated' ? <span className="message-association-warning">历史关联不完整</span> : null
  if (item.kind === 'user') return <div className="message-row user-row"><div className="avatar user-avatar">我</div><div className="message-body"><div className="message-meta"><strong>你</strong>{associationWarning}<time>{item.timestamp}</time></div><div className="bubble user-bubble">{item.text}{item.attachmentIds?.length ? <div className="inline-attachment"><Paperclip size={13} /> {item.attachmentIds.length} 个附件</div> : null}</div></div></div>
  if (item.kind === 'assistant') return <div className="message-row assistant-row"><div className="avatar agent-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-meta"><strong>Figura Agent</strong>{associationWarning}<time>{item.timestamp}</time></div><div className="bubble assistant-bubble"><SafeMarkdown source={item.text} /><details className="answer-source"><summary>查看原文</summary><pre>{item.text.slice(0, 12000)}</pre></details></div></div></div>
  if (item.kind === 'visual_observation') return <div className="visual-observation"><div className="observation-label"><FileImage size={14} /> <strong>视觉观察</strong><span>{item.toolName}</span></div><PreviewImage loader={props.previewLoader || null} onPreview={props.onPreview} sourceLabel="视觉观察" title={item.caption} resource={item.previewResource} fallbackUrl={item.imageUrl} alt={item.caption} /><small>{item.caption}</small></div>
  if (item.kind === 'error') return <div className="error-banner" role="alert">{item.text}</div>
  const label = item.kind === 'tool_call' ? '工具调用' : '工具结果'
  return <div className={'execution-item ' + (props.expanded ? 'expanded' : '')}><button className="execution-header" onClick={() => props.onToggle(item.id)} aria-expanded={props.expanded}><span className="execution-icon"><Terminal size={14} /></span><span><strong>{label}</strong><b>{item.toolName}</b></span><span className={'execution-status ' + item.status}>{toolStatusLabel(item.status)}</span>{props.expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>{props.expanded && <div className="execution-detail">{item.detail}</div>}</div>
}

export function RunBlock(props: {
  timeline: RunTimelineModel
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

export function ConversationPanel(props: { data: SessionData | null; timelines: RunTimelineModel[]; pendingUser: ConversationItem | null; runState: RunState; selectedAttachmentIds: string[]; activeSourceIds: string[]; provider: Provider; health: GatewayHealth | null; mode: 'mock' | 'gateway'; onProviderChange: (provider: Provider) => void; onSubmit: (text: string, attachmentIds: string[], retryOf?: string, resumeOf?: string) => Promise<boolean>; onInterrupt?: (runId: string) => void; onRetry?: (runId: string) => void; onResume?: (runId: string) => void; loading: boolean; loadingSession: boolean; error: string | null; onToggleRun: (runId: string, status: RunSummary['status']) => void; expandedRuns: Set<string>; previewLoader?: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
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

export function AttachmentPanel(props: { attachments: Attachment[]; pending: PendingAttachment[]; selectedIds: string[]; activeSourceIds: string[]; error: string | null; onAdd: (files: File[]) => void; onToggle: (id: string) => void; onRemovePending: (key: string) => void; onRetryPending: (item: PendingAttachment) => void; onRemove: (attachment: Attachment) => void; previewLoader?: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const previewLoader = props.previewLoader || null
  return <aside className="right-panel panel"><div className="panel-heading"><div><span className="eyebrow">会话数据</span><h2>附件</h2></div><button className="attachment-add" onClick={() => inputRef.current?.click()} title="添加图片"><Plus size={14} />添加图片</button><input ref={inputRef} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple onChange={(event) => { props.onAdd(Array.from(event.currentTarget.files ?? [])); event.currentTarget.value = '' }} /></div>{props.error && <div className="attachment-error" role="alert">{props.error}</div>}{props.activeSourceIds.length > 0 && <div className="details-note">已固定活动源：{props.activeSourceIds.length} 个附件。未勾选新附件的后续消息会继续使用它。</div>}{props.pending.length === 0 && props.attachments.length === 0 ? <div className="empty-attachments"><Paperclip size={19} /><span>暂无附件</span><small>选择图片后会显示在这里。</small></div> : <div className="attachment-list">{props.pending.map((item) => <div className="attachment-card pending-card" key={item.key}><img src={item.previewUrl} alt={item.file.name} /><div className="attachment-info"><strong>{item.file.name}</strong><span>{mediaTypeForFile(item.file).replace('image/', '').toUpperCase()} · {formatBytes(item.file.size)}</span><div className={'attachment-status ' + (item.status === 'error' ? 'error' : '')}>{item.status === 'uploading' ? <><LoaderCircle className="spin-icon" size={12} />正在上传</> : <><X size={12} />{item.error || '上传失败'}</>}</div><div className="attachment-actions">{item.status === 'error' && <button className="small-action" onClick={() => props.onRetryPending(item)} title="重新上传"><RefreshCw size={12} />重试</button>}<button className="small-action" onClick={() => props.onRemovePending(item.key)} title="移除待处理附件"><X size={12} />移除</button></div></div></div>)}{props.attachments.map((attachment) => { const selectable = attachment.status !== 'unavailable'; const selected = props.selectedIds.includes(attachment.id); const active = props.activeSourceIds.includes(attachment.id); return <div className={'attachment-card ' + (selected ? 'selected' : '')} key={attachment.id}><AttachmentPreview attachment={attachment} loader={previewLoader} onPreview={props.onPreview} /><div className="attachment-info"><strong>{attachment.filename}</strong><span>{attachment.mediaType.replace('image/', '').toUpperCase()} · {formatBytes(attachment.byteCount)}</span><div className={'attachment-status ' + (attachment.status === 'unavailable' ? 'error' : '')}><span className="status-dot" />{statusLabel(attachment.status)}{(attachment.previewUrl || attachment.previewResource) && <em>可预览</em>}{active && <em>活动源</em>}</div>{selectable && <label className="attachment-select"><input type="checkbox" checked={selected} onChange={() => props.onToggle(attachment.id)} />附加到下一条消息{selected && <Check size={12} />}</label>}<div className="attachment-actions"><button className="small-action danger-action" onClick={() => props.onRemove(attachment)} title="删除附件"><Trash2 size={13} />删除</button></div></div></div> })}</div>}<div className="details-divider" /><div className="panel-heading compact"><h2>执行详情</h2><span className="detail-count">{props.attachments.length ? `${props.attachments.length} 个附件` : '—'}</span></div><p className="details-note">工具活动和视觉观察会在后续运行中显示。</p></aside>
}
