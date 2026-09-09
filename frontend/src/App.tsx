import { useEffect, useState } from 'react'
import { BarChart3, ChevronDown, ChevronRight, FileImage, MessageSquare, Paperclip, Plus, Send, Sparkles, Terminal } from 'lucide-react'
import { mockClient } from './api/mockClient'
import type { Attachment, ConversationItem, Session, SessionData } from './types/protocol'
import './styles/global.css'

const formatBytes = (bytes: number) => (bytes / 1024).toFixed(1) + ' KB'

function SessionSidebar(props: { sessions: Session[]; activeId: string; onSelect: (id: string) => void; onCreate: () => void }) {
  return <aside className="sidebar panel">
    <div className="brand"><div className="brand-mark"><BarChart3 size={19} /></div><div><strong>ChartAgent</strong><span>桌面工作台</span></div></div>
    <div className="section-heading"><span>会话</span><button className="icon-button" onClick={props.onCreate} title="新建会话"><Plus size={16} /></button></div>
    <div className="session-list">{props.sessions.map((session) => <button key={session.id} className={'session-item ' + (session.id === props.activeId ? 'selected' : '')} onClick={() => props.onSelect(session.id)}><span className="session-dot" /><span className="session-copy"><strong>{session.name}</strong><small>{session.updatedAt}</small></span><span className="session-count">{session.runCount}</span></button>)}</div>
    <div className="sidebar-footer"><span className="status-dot" />模拟模式 <span className="muted">·</span> 可离线使用</div>
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

function ConversationPanel(props: { data: SessionData | null; onSubmit: (text: string) => void; loading: boolean }) {
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const send = () => { if (text.trim() && !props.loading) { props.onSubmit(text.trim()); setText('') } }
  return <main className="conversation panel"><header className="conversation-header"><div><span className="eyebrow">当前会话</span><h1>{props.data?.session.name ?? '正在加载会话'}</h1></div><span className="run-chip"><span className="status-dot" />{props.data?.session.runCount ?? 0} 次运行</span></header><div className="message-scroll">{!props.data ? <div className="loading-state"><span className="spinner" />正在加载会话...</div> : props.data.messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquare size={22} /></div><h2>开始新的分析</h2><p>提出问题或添加图片，开始使用 ChartAgent。</p></div> : props.data.messages.map((item) => <Message key={item.id} item={item} expanded={expanded === item.id} onToggle={(id) => setExpanded(expanded === id ? null : id)} />)}{props.loading && <div className="typing"><span /><span /><span /> Agent 正在思考</div>}</div><div className="composer"><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send() } }} placeholder="询问 ChartAgent 关于图表的问题..." rows={1} /><div className="composer-actions"><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><button className="send-button" onClick={send} disabled={!text.trim() || props.loading} title="发送消息"><Send size={16} /></button></div></div></main>
}

function AttachmentPanel({ attachments }: { attachments: Attachment[] }) {
  return <aside className="right-panel panel"><div className="panel-heading"><div><span className="eyebrow">会话数据</span><h2>附件</h2></div><button className="icon-button" title="添加附件"><Plus size={16} /></button></div>{attachments.length === 0 ? <div className="empty-attachments"><Paperclip size={19} /><span>暂无附件</span><small>上传的图片会显示在这里。</small></div> : <div className="attachment-list">{attachments.map((attachment) => <div className="attachment-card" key={attachment.id}><img src={attachment.previewUrl} alt={attachment.filename} /><div className="attachment-info"><strong>{attachment.filename}</strong><span>{attachment.mediaType.replace('image/', '').toUpperCase()} · {formatBytes(attachment.byteCount)}</span><div className="attachment-status"><span className="status-dot" />已有视觉观察</div></div></div>)}</div>}<div className="details-divider" /><div className="panel-heading compact"><h2>执行详情</h2><span className="detail-count">{attachments.length ? '2 个工具' : '—'}</span></div><p className="details-note">运行期间的工具活动和视觉观察会显示在这里。</p></aside>
}

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [data, setData] = useState<SessionData | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => { mockClient.listSessions().then((items) => { setSessions(items); setActiveId(items[0]?.id ?? '') }) }, [])
  useEffect(() => { if (activeId) { setData(null); mockClient.getSession(activeId).then(setData) } }, [activeId])
  const create = async () => { const name = window.prompt('请输入会话名称'); if (!name?.trim()) return; const created = await mockClient.createSession(name.trim()); setSessions(await mockClient.listSessions()); setActiveId(created.session.id) }
  const submit = async (text: string) => { if (!activeId) return; setLoading(true); try { const updated = await mockClient.submitMessage(activeId, text); setData(updated); setSessions(await mockClient.listSessions()) } finally { setLoading(false) } }
  return <div className="app-shell"><SessionSidebar sessions={sessions} activeId={activeId} onSelect={setActiveId} onCreate={create} /><ConversationPanel data={data} onSubmit={submit} loading={loading} /><AttachmentPanel attachments={data?.attachments ?? []} /></div>
}
