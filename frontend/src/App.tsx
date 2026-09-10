import { useEffect, useState } from 'react'
import { BarChart3, ChevronDown, ChevronRight, FileImage, MessageSquare, Paperclip, Plus, Send, Sparkles, Terminal } from 'lucide-react'
import { GatewayClientError, gatewayClient } from './api/gatewayClient'
import type { ChartAgentClient } from './api/client'
import { mockClient } from './api/mockClient'
import type { Attachment, ConversationItem, Session, SessionData } from './types/protocol'
import './styles/global.css'
import './styles/error.css'

const formatBytes = (bytes: number) => (bytes / 1024).toFixed(1) + ' KB'

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
  return <div className={'execution-item ' + (props.expanded ? 'expanded' : '')}><button className="execution-header" onClick={() => props.onToggle(item.id)} aria-expanded={props.expanded}><span className="execution-icon"><Terminal size={14} /></span><span><strong>{label}</strong><b>{item.toolName}</b></span><span className={'execution-status ' + item.status}>{item.status}</span>{props.expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>{props.expanded && <div className="execution-detail">{item.detail}</div>}</div>
}

function ConversationPanel(props: { data: SessionData | null; onSubmit: (text: string) => void; loading: boolean; loadingSession: boolean; error: string | null }) {
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const send = () => { if (text.trim() && !props.loading) { props.onSubmit(text.trim()); setText('') } }
  return <main className="conversation panel"><header className="conversation-header"><div><span className="eyebrow">当前会话</span><h1>{props.data?.session.name ?? (props.loadingSession ? '正在加载会话' : '暂无活动会话')}</h1></div><span className="run-chip"><span className="status-dot" />{props.data?.session.runCount ?? 0} 次运行</span></header><div className="message-scroll">{props.loadingSession ? <div className="loading-state"><span className="spinner" />正在加载会话...</div> : props.error && !props.data ? <div className="error-state"><div className="empty-icon"><MessageSquare size={22} /></div><h2>无法连接本地服务</h2><p>{props.error}</p></div> : !props.data ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>创建第一个会话</h2><p>请从左侧新建会话，开始使用 ChartAgent。</p></div> : props.data.messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>开始新的分析</h2><p>提出问题或添加图片，开始使用 ChartAgent。</p></div> : props.data.messages.map((item) => <Message key={item.id} item={item} expanded={expanded === item.id} onToggle={(id) => setExpanded(expanded === id ? null : id)} />)}{props.loading && <div className="typing"><span /><span /><span /> Agent 正在思考</div>}{props.error && props.data && <div className="error-banner" role="alert">{props.error}</div>}</div><div className="composer"><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send() } }} placeholder="询问 ChartAgent 关于图表的问题..." rows={1} /><div className="composer-actions"><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" onClick={send} disabled={!text.trim() || props.loading || props.loadingSession} title="发送消息"><Send size={16} /></button></div></div></main>
}

function AttachmentPanel({ attachments }: { attachments: Attachment[] }) {
  return <aside className="right-panel panel"><div className="panel-heading"><div><span className="eyebrow">会话数据</span><h2>附件</h2></div><button className="icon-button" title="添加附件"><Plus size={16} /></button></div>{attachments.length === 0 ? <div className="empty-attachments"><Paperclip size={19} /><span>暂无附件</span><small>上传的图片会显示在这里。</small></div> : <div className="attachment-list">{attachments.map((attachment) => <div className="attachment-card" key={attachment.id}><img src={attachment.previewUrl} alt={attachment.filename} /><div className="attachment-info"><strong>{attachment.filename}</strong><span>{attachment.mediaType.replace('image/', '').toUpperCase()} · {formatBytes(attachment.byteCount)}</span><div className="attachment-status"><span className="status-dot" />已有视觉观察</div></div></div>)}</div>}<div className="details-divider" /><div className="panel-heading compact"><h2>执行详情</h2><span className="detail-count">{attachments.length ? '2 个工具' : '—'}</span></div><p className="details-note">运行期间的工具活动和视觉观察会显示在这里。</p></aside>
}

export default function App() {
  const mode = import.meta.env.VITE_CHARTAGENT_MODE === 'gateway' ? 'gateway' : 'mock'
  const client: ChartAgentClient = mode === 'gateway' ? gatewayClient : mockClient
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [data, setData] = useState<SessionData | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingSession, setLoadingSession] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { setLoadingSession(true); client.listSessions().then((items) => { setSessions(items); setActiveId(items[0]?.id ?? '') }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false)) }, [client])
  useEffect(() => { if (!activeId) { setData(null); return }; setData(null); setLoadingSession(true); client.getSession(activeId).then(setData).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false)) }, [activeId, client])
  const create = async () => { const name = window.prompt('请输入会话名称'); if (!name?.trim()) return; setError(null); try { const created = await client.createSession(name.trim()); setSessions(await client.listSessions()); setActiveId(created.session.id) } catch (reason) { setError(toUserMessage(reason)) } }
  const submit = async (text: string) => { if (!activeId) return; setLoading(true); setError(null); try { const updated = await client.submitMessage(activeId, text); setData(updated); setSessions(await client.listSessions()) } catch (reason) { setError(toUserMessage(reason)) } finally { setLoading(false) } }
  return <div className="app-shell"><SessionSidebar sessions={sessions} activeId={activeId} onSelect={(id) => { setError(null); setActiveId(id) }} onCreate={create} mode={mode} /><ConversationPanel data={data} onSubmit={submit} loading={loading} loadingSession={loadingSession} error={error} /><AttachmentPanel attachments={data?.attachments ?? []} /></div>
}

function toUserMessage(error: unknown): string {
  if (error instanceof GatewayClientError) {
    if (error.code === 'gateway_unavailable') return '无法连接到本地 Gateway，请先启动 Python 服务。'
    if (error.code === 'agent_unavailable') return 'Agent 当前不可用，请检查模型配置。'
    if (error.code === 'session_not_found') return '会话不存在，可能已被删除。'
    if (error.code === 'session_exists') return '会话名称已存在，请换一个名称。'
    if (error.code === 'invalid_request') return '请求内容无效，请检查后重试。'
    return '本地服务处理失败，请稍后重试。'
  }
  return '操作失败，请稍后重试。'
}
