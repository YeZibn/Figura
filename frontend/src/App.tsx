import { useEffect, useRef, useState, type FormEvent } from 'react'
import { BarChart3, Check, ChevronDown, ChevronRight, FileImage, LoaderCircle, MessageSquare, Paperclip, Plus, RefreshCw, Send, Sparkles, Terminal, X } from 'lucide-react'
import { GatewayClientError, gatewayClient } from './api/gatewayClient'
import type { ChartAgentClient } from './api/client'
import { mockClient } from './api/mockClient'
import { formatBytes, mediaTypeForFile, validateImageFile } from './attachments'
import type { Attachment, AttachmentStatus, ConversationItem, Session, SessionData } from './types/protocol'
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

function SessionSidebar(props: { sessions: Session[]; activeId: string; onSelect: (id: string) => void; onCreate: () => void; mode: 'mock' | 'gateway' }) {
  return <aside className="sidebar panel">
    <div className="brand"><div className="brand-mark"><BarChart3 size={19} /></div><div><strong>ChartAgent</strong><span>桌面工作台</span></div></div>
    <div className="section-heading"><span>会话</span><button className="icon-button" onClick={props.onCreate} title="新建会话"><Plus size={16} /></button></div>
    <div className="session-list">{props.sessions.map((session) => <button key={session.id} className={'session-item ' + (session.id === props.activeId ? 'selected' : '')} onClick={() => props.onSelect(session.id)}><span className="session-dot" /><span className="session-copy"><strong>{session.name}</strong><small>{session.updatedAt}</small></span><span className="session-count">{session.runCount}</span></button>)}</div>
    <div className="sidebar-footer"><span className="status-dot" />{props.mode === 'gateway' ? 'Gateway 模式' : '模拟模式'} <span className="muted">·</span> {props.mode === 'gateway' ? '本地服务' : '可离线使用'}</div>
  </aside>
}

function Message(props: { item: ConversationItem; expanded: boolean; onToggle: (id: string) => void }) {
  const item = props.item
  if (item.kind === 'user') return <div className="message-row user-row"><div className="avatar user-avatar">我</div><div className="message-body"><div className="message-meta"><strong>你</strong><time>{item.timestamp}</time></div><div className="bubble user-bubble">{item.text}{item.attachmentIds?.length ? <div className="inline-attachment"><Paperclip size={13} /> {item.attachmentIds.length} 个附件</div> : null}</div></div></div>
  if (item.kind === 'assistant') return <div className="message-row"><div className="avatar agent-avatar"><Sparkles size={15} /></div><div className="message-body"><div className="message-meta"><strong>ChartAgent</strong><time>{item.timestamp}</time></div><div className="bubble assistant-bubble">{item.text}</div></div></div>
  if (item.kind === 'visual_observation') return <div className="visual-observation"><div className="observation-label"><FileImage size={14} /> 视觉观察 <span>{item.toolName}</span></div><img src={item.imageUrl} alt={item.caption} /><small>{item.caption}</small></div>
  if (item.kind === 'error') return <div className="error-banner">{item.text}</div>
  const label = item.kind === 'tool_call' ? '工具调用' : '工具结果'
  return <div className={'execution-item ' + (props.expanded ? 'expanded' : '')}><button className="execution-header" onClick={() => props.onToggle(item.id)} aria-expanded={props.expanded}><span className="execution-icon"><Terminal size={14} /></span><span><strong>{label}</strong><b>{item.toolName}</b></span><span className={'execution-status ' + item.status}>{toolStatusLabel(item.status)}</span>{props.expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>{props.expanded && <div className="execution-detail">{item.detail}</div>}</div>
}

function ConversationPanel(props: { data: SessionData | null; selectedAttachmentIds: string[]; onSubmit: (text: string, attachmentIds: string[]) => Promise<boolean>; loading: boolean; loadingSession: boolean; error: string | null }) {
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const send = async () => {
    const value = text.trim()
    if (!value || props.loading) return
    const submitted = await props.onSubmit(value, props.selectedAttachmentIds)
    if (submitted) setText('')
  }
  return <main className="conversation panel"><header className="conversation-header"><div><span className="eyebrow">当前会话</span><h1>{props.data?.session.name ?? (props.loadingSession ? '正在加载会话' : '暂无活动会话')}</h1></div><span className="run-chip"><span className="status-dot" />{props.data?.session.runCount ?? 0} 次运行</span></header><div className="message-scroll">{props.loadingSession ? <div className="loading-state"><span className="spinner" />正在加载会话...</div> : props.error && !props.data ? <div className="error-state"><div className="empty-icon"><MessageSquare size={22} /></div><h2>无法连接本地服务</h2><p>{props.error}</p></div> : !props.data ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>创建第一个会话</h2><p>请从左侧新建会话，开始使用 ChartAgent。</p></div> : props.data.messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>开始新的分析</h2><p>提出问题或添加图片，开始使用 ChartAgent。</p></div> : props.data.messages.map((item) => <Message key={item.id} item={item} expanded={expanded === item.id} onToggle={(id) => setExpanded(expanded === id ? null : id)} />)}{props.loading && <div className="typing"><span /><span /><span /> Agent 正在思考</div>}{props.error && props.data && <div className="error-banner" role="alert">{props.error}</div>}</div><div className="composer"><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder="询问 ChartAgent 关于图表的问题..." rows={1} /><div className="composer-actions"><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" onClick={() => void send()} disabled={!text.trim() || props.loading || props.loadingSession} title="发送消息"><Send size={16} /></button></div></div></main>
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
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [data, setData] = useState<SessionData | null>(null)
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingSession, setLoadingSession] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)
  const [newSessionName, setNewSessionName] = useState('')
  const activeIdRef = useRef(activeId)
  const localPreviews = useRef(new Map<string, string>())

  useEffect(() => { activeIdRef.current = activeId }, [activeId])
  useEffect(() => () => { localPreviews.current.forEach((url) => URL.revokeObjectURL(url)); localPreviews.current.clear() }, [])

  const withLocalPreviews = (value: SessionData): SessionData => ({ ...value, attachments: value.attachments.map((attachment) => ({ ...attachment, previewUrl: attachment.previewUrl || localPreviews.current.get(attachment.id) || '' })) })

  useEffect(() => { setLoadingSession(true); client.listSessions().then((items) => { setSessions(items); setActiveId(items[0]?.id ?? '') }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false)) }, [client])
  useEffect(() => { if (!activeId) { setData(null); return }; setData(null); setLoadingSession(true); client.getSession(activeId).then((value) => setData(withLocalPreviews(value))).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false)) }, [activeId, client])

  const clearPending = () => { pending.forEach((item) => URL.revokeObjectURL(item.previewUrl)); setPending([]) }
  const selectSession = (id: string) => { clearPending(); setSelectedIds([]); setAttachmentError(null); setError(null); setActiveId(id) }
  const create = async () => { setNewSessionName(''); setCreatingSession(true) }
  const confirmCreate = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const name = newSessionName.trim(); if (!name) return; setError(null); try { const created = await client.createSession(name); setSessions(await client.listSessions()); setActiveId(created.session.id); setCreatingSession(false) } catch (reason) { setError(toUserMessage(reason)) } }

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

  const submit = async (text: string, attachmentIds: string[]): Promise<boolean> => { if (!activeId) return false; setLoading(true); setError(null); try { const updated = await client.submitMessage(activeId, text, attachmentIds); setData(withLocalPreviews(updated)); setSessions(await client.listSessions()); setSelectedIds([]); return true } catch (reason) { setError(toUserMessage(reason)); return false } finally { setLoading(false) } }

  return <><div className="app-shell"><SessionSidebar sessions={sessions} activeId={activeId} onSelect={selectSession} onCreate={create} mode={mode} /><ConversationPanel data={data} selectedAttachmentIds={selectedIds} onSubmit={submit} loading={loading} loadingSession={loadingSession} error={error} /><AttachmentPanel attachments={data?.attachments ?? []} pending={pending} selectedIds={selectedIds} error={attachmentError} onAdd={addFiles} onToggle={toggleAttachment} onRemovePending={removePending} onRetryPending={(item) => void uploadPending(item)} /></div>{creatingSession && <div className="dialog-backdrop"><form className="session-dialog" onSubmit={(event) => void confirmCreate(event)}><h2>新建会话</h2><label htmlFor="session-name">会话名称</label><input id="session-name" value={newSessionName} onChange={(event) => setNewSessionName(event.target.value)} placeholder="例如：季度销售分析" autoFocus /><div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={() => setCreatingSession(false)}>取消</button><button type="submit" className="dialog-primary" disabled={!newSessionName.trim()}>创建会话</button></div></form></div>}</>
}

function toUserMessage(error: unknown): string {
  if (error instanceof GatewayClientError) {
    if (error.code === 'gateway_unavailable') return '无法连接到本地 Gateway，请先启动 Python 服务。'
    if (error.code === 'agent_unavailable') return 'Agent 当前不可用，请检查模型配置。'
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
