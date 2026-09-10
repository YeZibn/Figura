import { useEffect, useRef, useState, type FormEvent } from 'react'
import { BarChart3, Check, ChevronDown, ChevronRight, FileImage, LoaderCircle, MessageSquare, Paperclip, Plus, RefreshCw, Send, Sparkles, Terminal, X } from 'lucide-react'
import { GatewayClientError, gatewayClient } from './api/gatewayClient'
import type { ChartAgentClient, RunSubscription } from './api/client'
import { mockClient } from './api/mockClient'
import { formatBytes, mediaTypeForFile, validateImageFile } from './attachments'
import { getGatewayRuntimeStatus, type GatewayRuntimeStatus } from './runtime'
import type { AgentRunEvent, Attachment, AttachmentStatus, ConversationItem, GatewayHealth, RunState, Session, SessionData } from './types/protocol'
import './styles/global.css'
import './styles/error.css'

type PendingAttachment = {
  key: string
  file: File
  previewUrl: string
  status: 'uploading' | 'error'
  error?: string
}

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
  if (state === 'unavailable') return '服务不可用'
  return '准备就绪'
}

function currentTime(): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function eventPayload(event: AgentRunEvent): Record<string, unknown> {
  return event.payload || {}
}

function textDetail(value: unknown): string {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return '事件内容不可显示' }
}

function conversationItemsForEvent(event: AgentRunEvent): ConversationItem[] {
  const payload = eventPayload(event)
  const timestamp = event.timestamp ? new Date(event.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : currentTime()
  if (event.kind === 'tool_call') {
    return [{ id: `${event.runId}-${event.sequence}`, kind: 'tool_call', toolName: String(payload.tool_name || '未知工具'), status: 'running', detail: textDetail(payload.arguments), timestamp }]
  }
  if (event.kind === 'tool_result') {
    return [{ id: `${event.runId}-${event.sequence}`, kind: 'tool_result', toolName: String(payload.tool_name || '未知工具'), status: payload.status === 'error' ? 'error' : 'success', detail: textDetail(payload.result), timestamp }]
  }
  if (event.kind === 'visual_observation') {
    const observations = Array.isArray(payload.observations) ? payload.observations : []
    return observations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')).map((item, index) => ({
      id: `${event.runId}-${event.sequence}-${index}`,
      kind: 'visual_observation',
      toolName: String(payload.tool_name || '视觉工具'),
      caption: String(item.caption || '视觉观察'),
      imageUrl: typeof item.imageUrl === 'string' ? item.imageUrl : undefined,
      timestamp,
    }))
  }
  return []
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

function SessionSidebar(props: { sessions: Session[]; activeId: string; onSelect: (id: string) => void; onCreate: () => void; mode: 'mock' | 'gateway'; runtimeStatus: GatewayRuntimeStatus | null; health: GatewayHealth | null }) {
  const statusUnavailable = props.runtimeStatus?.state === 'unavailable' || props.runtimeStatus?.agentState === 'unavailable' || props.health?.agent?.status === 'unavailable'
  return <aside className="sidebar panel">
    <div className="brand"><div className="brand-mark"><BarChart3 size={19} /></div><div><strong>ChartAgent</strong><span>桌面工作台</span></div></div>
    <div className="section-heading"><span>会话</span><button className="icon-button" onClick={props.onCreate} title="新建会话"><Plus size={16} /></button></div>
    <div className="session-list">{props.sessions.map((session) => <button key={session.id} className={'session-item ' + (session.id === props.activeId ? 'selected' : '')} onClick={() => props.onSelect(session.id)}><span className="session-dot" /><span className="session-copy"><strong>{session.name}</strong><small>{session.updatedAt}</small></span><span className="session-count">{session.runCount}</span></button>)}</div>
    <div className="sidebar-footer"><span className={'status-dot ' + (statusUnavailable ? 'status-error' : '')} />{props.mode === 'gateway' ? 'Gateway 模式' : '模拟模式'} <span className="muted">·</span> {gatewayStatusText(props.mode, props.runtimeStatus, props.health)}</div>
  </aside>
}

function Message(props: { item: ConversationItem; expanded: boolean; onToggle: (id: string) => void }) {
  const item = props.item
  if (item.kind === 'user') return <div className="message-row user-row"><div className="avatar user-avatar">我</div><div className="message-body"><div className="message-meta"><strong>你</strong><time>{item.timestamp}</time></div><div className="bubble user-bubble">{item.text}{item.attachmentIds?.length ? <div className="inline-attachment"><Paperclip size={13} /> {item.attachmentIds.length} 个附件</div> : null}</div></div></div>
  if (item.kind === 'assistant') return <div className="message-row"><div className="avatar agent-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-meta"><strong>ChartAgent</strong><time>{item.timestamp}</time></div><div className="bubble assistant-bubble">{item.text}</div></div></div>
  if (item.kind === 'visual_observation') return <div className="visual-observation"><div className="observation-label"><FileImage size={14} /> 视觉观察 <span>{item.toolName}</span></div>{item.imageUrl ? <img src={item.imageUrl} alt={item.caption} /> : <div className="observation-placeholder">临时视觉证据不可用</div>}<small>{item.caption}</small></div>
  if (item.kind === 'error') return <div className="error-banner">{item.text}</div>
  const label = item.kind === 'tool_call' ? '工具调用' : '工具结果'
  return <div className={'execution-item ' + (props.expanded ? 'expanded' : '')}><button className="execution-header" onClick={() => props.onToggle(item.id)} aria-expanded={props.expanded}><span className="execution-icon"><Terminal size={14} /></span><span><strong>{label}</strong><b>{item.toolName}</b></span><span className={'execution-status ' + item.status}>{toolStatusLabel(item.status)}</span>{props.expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>{props.expanded && <div className="execution-detail">{item.detail}</div>}</div>
}

function ConversationPanel(props: { data: SessionData | null; liveItems: ConversationItem[]; runState: RunState; selectedAttachmentIds: string[]; onSubmit: (text: string, attachmentIds: string[]) => Promise<boolean>; loading: boolean; loadingSession: boolean; error: string | null }) {
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const items = [...(props.data?.messages ?? []), ...props.liveItems]
  const send = async () => {
    const value = text.trim()
    if (!value || props.loading) return
    const submitted = await props.onSubmit(value, props.selectedAttachmentIds)
    if (submitted) setText('')
  }
  return <main className="conversation panel"><header className="conversation-header"><div><span className="eyebrow">当前会话</span><h1>{props.data?.session.name ?? (props.loadingSession ? '正在加载会话' : '暂无活动会话')}</h1></div><span className={'run-chip ' + props.runState}><span className="status-dot" />{runStateLabel(props.runState)} · {props.data?.session.runCount ?? 0} 次运行</span></header><div className="message-scroll">{props.loadingSession ? <div className="loading-state"><span className="spinner" />正在加载会话...</div> : props.error && !props.data && items.length === 0 ? <div className="error-state"><div className="empty-icon"><MessageSquare size={22} /></div><h2>无法连接本地服务</h2><p>{props.error}</p></div> : !props.data && items.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>创建第一个会话</h2><p>请从左侧新建会话，开始使用 ChartAgent。</p></div> : items.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>开始新的分析</h2><p>提出问题或添加图片，开始使用 ChartAgent。</p></div> : items.map((item) => <Message key={item.id} item={item} expanded={expanded === item.id} onToggle={(id) => setExpanded(expanded === id ? null : id)} />)}{props.loading && <div className="typing"><span /><span /><span /> Agent 正在思考</div>}{props.error && <div className="error-banner" role="alert">{props.error}</div>}</div><div className="composer"><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder="询问 ChartAgent 关于图表的问题..." rows={1} /><div className="composer-actions"><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" onClick={() => void send()} disabled={!text.trim() || props.loading || props.loadingSession} title="发送消息"><Send size={16} /></button></div></div></main>
}

function AttachmentPreview({ attachment }: { attachment: Attachment }) {
  return attachment.previewUrl ? <img src={attachment.previewUrl} alt={attachment.filename} /> : <div className="attachment-placeholder"><FileImage size={24} /><span>暂无本地预览</span></div>
}

function AttachmentPanel(props: { attachments: Attachment[]; pending: PendingAttachment[]; selectedIds: string[]; error: string | null; onAdd: (files: File[]) => void; onToggle: (id: string) => void; onRemovePending: (key: string) => void; onRetryPending: (item: PendingAttachment) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  return <aside className="right-panel panel"><div className="panel-heading"><div><span className="eyebrow">会话数据</span><h2>附件</h2></div><button className="attachment-add" onClick={() => inputRef.current?.click()} title="添加图片"><Plus size={14} />添加图片</button><input ref={inputRef} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple onChange={(event) => { props.onAdd(Array.from(event.currentTarget.files ?? [])); event.currentTarget.value = '' }} /></div>{props.error && <div className="attachment-error" role="alert">{props.error}</div>}{props.pending.length === 0 && props.attachments.length === 0 ? <div className="empty-attachments"><Paperclip size={19} /><span>暂无附件</span><small>选择图片后会显示在这里。</small></div> : <div className="attachment-list">{props.pending.map((item) => <div className="attachment-card pending-card" key={item.key}><img src={item.previewUrl} alt={item.file.name} /><div className="attachment-info"><strong>{item.file.name}</strong><span>{mediaTypeForFile(item.file).replace('image/', '').toUpperCase()} · {formatBytes(item.file.size)}</span><div className={'attachment-status ' + (item.status === 'error' ? 'error' : '')}>{item.status === 'uploading' ? <><LoaderCircle className="spin-icon" size={12} />正在上传</> : <><X size={12} />{item.error || '上传失败'}</>}</div><div className="attachment-actions">{item.status === 'error' && <button className="small-action" onClick={() => props.onRetryPending(item)} title="重新上传"><RefreshCw size={12} />重试</button>}<button className="small-action" onClick={() => props.onRemovePending(item.key)} title="移除待处理附件"><X size={12} />移除</button></div></div></div>)}{props.attachments.map((attachment) => { const selectable = attachment.status !== 'unavailable'; const selected = props.selectedIds.includes(attachment.id); return <div className={'attachment-card ' + (selected ? 'selected' : '')} key={attachment.id}><AttachmentPreview attachment={attachment} /><div className="attachment-info"><strong>{attachment.filename}</strong><span>{attachment.mediaType.replace('image/', '').toUpperCase()} · {formatBytes(attachment.byteCount)}</span><div className={'attachment-status ' + (attachment.status === 'unavailable' ? 'error' : '')}><span className="status-dot" />{statusLabel(attachment.status)}{attachment.previewUrl && <em>本地预览</em>}</div>{selectable && <label className="attachment-select"><input type="checkbox" checked={selected} onChange={() => props.onToggle(attachment.id)} />附加到下一条消息{selected && <Check size={12} />}</label>}</div></div> })}</div>}<div className="details-divider" /><div className="panel-heading compact"><h2>执行详情</h2><span className="detail-count">{props.attachments.length ? `${props.attachments.length} 个附件` : '—'}</span></div><p className="details-note">工具活动和视觉观察会在后续运行中显示。</p></aside>
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
  const [liveItems, setLiveItems] = useState<ConversationItem[]>([])
  const [runState, setRunState] = useState<RunState>('idle')
  const [loading, setLoading] = useState(false)
  const [loadingSession, setLoadingSession] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)
  const [newSessionName, setNewSessionName] = useState('')
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
  useEffect(() => { if (!activeId) { setData(null); return }; setData(null); setLoadingSession(true); client.getSession(activeId).then((value) => setData(withLocalPreviews(value))).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false)) }, [activeId, client])

  const clearPending = () => { pending.forEach((item) => URL.revokeObjectURL(item.previewUrl)); setPending([]) }
  const selectSession = (id: string) => { subscriptionRef.current?.close(); subscriptionRef.current = null; clearPending(); setSelectedIds([]); setLiveItems([]); setRunState('idle'); setAttachmentError(null); setError(null); setActiveId(id) }
  const create = async () => { setNewSessionName(''); setCreatingSession(true) }
  const confirmCreate = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const name = newSessionName.trim(); if (!name) return; setError(null); try { subscriptionRef.current?.close(); subscriptionRef.current = null; clearPending(); setSelectedIds([]); setLiveItems([]); setRunState('idle'); const created = await client.createSession(name); setSessions(await client.listSessions()); setActiveId(created.session.id); setCreatingSession(false) } catch (reason) { setError(toUserMessage(reason)) } }

  const uploadPending = async (target: PendingAttachment) => {
    const sessionId = activeIdRef.current
    setPending((items) => items.map((item) => item.key === target.key ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const uploaded = await client.uploadAttachment(sessionId, target.file)
      if (activeIdRef.current !== sessionId) { URL.revokeObjectURL(target.previewUrl); return }
      localPreviews.current.set(uploaded.id, target.previewUrl)
      setData((current) => current ? { ...current, attachments: [...current.attachments.filter((item) => item.id !== uploaded.id), { ...uploaded, previewUrl: target.previewUrl, previewAvailable: true }] } : current)
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
    setLiveItems([{ id: `pending-${Date.now()}`, kind: 'user', text, timestamp: currentTime(), attachmentIds: attachmentIds.length ? attachmentIds : undefined }])
    try {
      const handle = await client.startRun(sessionId, text, attachmentIds)
      if (activeIdRef.current !== sessionId) return false
      setRunState('running')
      let terminalFailure = false
      subscriptionRef.current = client.subscribeRun(sessionId, handle.runId, {
        onEvent(event) {
          if (activeIdRef.current !== sessionId) return
          if (event.kind === 'run_failed') {
            terminalFailure = true
            setRunState('failed')
            setLoading(false)
            setError(toUserMessage(new GatewayClientError(String(event.payload.code || 'agent_failed'), String(event.payload.message || 'Agent 执行失败'), 502, typeof event.payload.reason === 'string' ? event.payload.reason : undefined)))
          } else if (event.kind !== 'run_started') {
            setRunState('running')
          }
          const items = conversationItemsForEvent(event)
          if (items.length) setLiveItems((current) => [...current, ...items])
        },
        onError(reason) {
          if (activeIdRef.current !== sessionId) return
          setRunState('unavailable')
          setLoading(false)
          setError(toUserMessage(reason))
        },
        onComplete() {
          subscriptionRef.current = null
          if (activeIdRef.current !== sessionId) return
          if (terminalFailure) return
          void client.getSession(sessionId).then((updated) => {
            if (activeIdRef.current !== sessionId) return
            setData(withLocalPreviews(updated))
            setSessions((current) => current.map((item) => item.id === updated.session.id ? updated.session : item))
            setLiveItems((current) => current.filter((item) => item.kind !== 'user' && item.kind !== 'assistant'))
            setRunState('completed')
            setLoading(false)
          }).catch((reason) => {
            setRunState('failed')
            setLoading(false)
            setError(toUserMessage(reason))
          })
        },
      })
      return true
    } catch (reason) {
      setRunState('unavailable')
      setError(toUserMessage(reason))
      setLoading(false)
      return false
    }
  }

  return <><div className="app-shell"><SessionSidebar sessions={sessions} activeId={activeId} onSelect={selectSession} onCreate={create} mode={mode} runtimeStatus={runtimeStatus} health={gatewayHealth} /><ConversationPanel data={data} liveItems={liveItems} runState={runState} selectedAttachmentIds={selectedIds} onSubmit={submit} loading={loading} loadingSession={loadingSession} error={error} /><AttachmentPanel attachments={data?.attachments ?? []} pending={pending} selectedIds={selectedIds} error={attachmentError} onAdd={addFiles} onToggle={toggleAttachment} onRemovePending={removePending} onRetryPending={(item) => void uploadPending(item)} /></div>{creatingSession && <div className="dialog-backdrop"><form className="session-dialog" onSubmit={(event) => void confirmCreate(event)}><h2>新建会话</h2><label htmlFor="session-name">会话名称</label><input id="session-name" value={newSessionName} onChange={(event) => setNewSessionName(event.target.value)} placeholder="例如：季度销售分析" autoFocus /><div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={() => setCreatingSession(false)}>取消</button><button type="submit" className="dialog-primary" disabled={!newSessionName.trim()}>创建会话</button></div></form></div>}</>
}

function toUserMessage(error: unknown): string {
  if (error instanceof GatewayClientError) {
    if (error.code === 'gateway_unavailable') return '无法连接到本地 Gateway，请先启动 Python 服务。'
    if (error.code === 'agent_unavailable' && error.reason === 'missing_configuration') return 'Agent 未配置，请检查项目根目录 .env 中的模型配置。'
    if (error.code === 'agent_unavailable' && error.reason === 'invalid_configuration') return 'Agent 配置无效，请检查模型地址和参数。'
    if (error.code === 'agent_unavailable') return 'Agent 当前不可用，请稍后重试。'
    if (error.code === 'session_not_found') return '会话不存在，可能已被删除。'
    if (error.code === 'session_exists') return '会话名称已存在，请换一个名称。'
    if (error.code === 'attachment_not_found') return '附件不存在或不属于当前会话。'
    if (error.code === 'attachment_unavailable') return '附件源文件不可用，请重新上传。'
    if (error.code === 'unsupported_media_type' || error.code === 'invalid_image') return '图片格式无法识别，请选择 PNG、JPEG、GIF 或 WebP。'
    if (error.code === 'attachment_too_large' || error.code === 'attachment_storage_limit') return '图片或当前会话的附件总量超过限制。'
    if (error.code === 'invalid_filename') return '图片文件名无效，请重命名后重试。'
    if (error.code === 'invalid_request') return '请求内容无效，请检查后重试。'
    return '本地服务处理失败，请稍后重试。'
  }
  return '操作失败，请稍后重试。'
}
