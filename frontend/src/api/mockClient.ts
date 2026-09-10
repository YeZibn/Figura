import type { ChartAgentClient, RunEventCallbacks, RunSubscription } from './client'
import type { AgentRunEvent, Attachment, ConversationItem, RunHandle, Session, SessionData } from '../types/protocol'

const image = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"%3E%3Crect width="640" height="360" fill="%23f7f9fb"/%3E%3Cpath d="M74 292h492M110 260V104m130 156V68m130 192V126m130 134V92" stroke="%232e8c82" stroke-width="54" stroke-linecap="round"/%3E%3Cpath d="M60 48h520" stroke="%23dbe3e8"/%3E%3C/svg%3E'
const attachments: Attachment[] = [{ id: 'att_demo_chart', filename: '季度销售.png', mediaType: 'image/png', byteCount: 16299, previewUrl: image, status: 'observation' }]
const baseMessages: ConversationItem[] = [
  { id: 'm1', kind: 'user', text: '请分析这张图表，并告诉我每个类别的数值。', timestamp: '10:39', attachmentIds: ['att_demo_chart'] },
  { id: 'm2', kind: 'tool_call', toolName: 'load_image', status: 'success', detail: 'attachment_id=att_demo_chart', timestamp: '10:39' },
  { id: 'm3', kind: 'tool_result', toolName: 'load_image', status: 'success', detail: '已加载季度销售.png · 1 个视觉观察', timestamp: '10:39' },
  { id: 'm4', kind: 'visual_observation', toolName: 'load_image', caption: '已加载附件：季度销售.png', imageUrl: image, timestamp: '10:39' },
  { id: 'm5', kind: 'tool_call', toolName: 'measure_bars', status: 'success', detail: 'attachment_id=att_demo_chart', timestamp: '10:40' },
  { id: 'm6', kind: 'tool_result', toolName: 'measure_bars', status: 'success', detail: '检测到 3 个柱子 · baseline_y=425', timestamp: '10:40' },
  { id: 'm7', kind: 'visual_observation', toolName: 'measure_bars', caption: '已检测柱子、稳定标识和基线', imageUrl: image, timestamp: '10:40' },
  { id: 'm8', kind: 'assistant', text: '这张图表包含三个类别：Alpha 为 8，Beta 为 16，Gamma 为 24。测量得到的柱高约为 1:2:3，与图中打印的数值一致。', timestamp: '10:40' },
]

const data: Record<string, SessionData> = {
  'chart-analysis': { session: { id: 'chart-analysis', name: '图表分析', updatedAt: '今天 10:40', runCount: 12 }, messages: baseMessages, attachments },
  'sales-review': { session: { id: 'sales-review', name: '销售复盘', updatedAt: '昨天 16:18', runCount: 7 }, messages: [{ id: 's1', kind: 'assistant', text: '可以开始比较这个会话中的销售图表。', timestamp: '16:18' }], attachments: [] },
  untitled: { session: { id: 'untitled', name: '未命名会话', updatedAt: '周一 09:12', runCount: 0 }, messages: [], attachments: [] },
}

const pendingRuns = new Map<string, { text: string; attachmentIds: string[] }>()
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T,>(value: T): T => structuredClone(value)

export const mockClient: ChartAgentClient = {
  async listSessions() { await wait(120); return Object.values(data).map((entry) => clone(entry.session)) },
  async getSession(id) { await wait(160); return clone(data[id]) },
  async createSession(name) { await wait(160); const id = 'session-' + Date.now(); const session: Session = { id, name, updatedAt: '刚刚', runCount: 0 }; data[id] = { session, messages: [], attachments: [] }; return clone(data[id]) },
  async listAttachments(sessionId) { await wait(80); return clone(data[sessionId]?.attachments ?? []) },
  async uploadAttachment(sessionId, file) {
    await wait(240)
    const target = data[sessionId]
    const attachment: Attachment = { id: 'att_mock_' + Date.now(), filename: file.name, mediaType: file.type || 'image/png', byteCount: file.size, previewUrl: URL.createObjectURL(file), status: 'registered', previewAvailable: true }
    target.attachments.push(attachment)
    return clone(attachment)
  },
  async startRun(sessionId, text, attachmentIds = []) {
    await wait(90)
    const runId = `run_mock_${Date.now()}`
    pendingRuns.set(runId, { text, attachmentIds })
    return { runId, sessionId, status: 'running' }
  },
  subscribeRun(sessionId, runId, callbacks: RunEventCallbacks): RunSubscription {
    let closed = false
    const timers: ReturnType<typeof setTimeout>[] = []
    const target = data[sessionId]
    const timestamp = '刚刚'
    const emit = (kind: string, sequence: number, payload: Record<string, unknown> = {}) => {
      if (closed) return
      callbacks.onEvent({ runId, sequence, kind, timestamp, payload } as AgentRunEvent)
    }
    const schedule = (delay: number, action: () => void) => timers.push(setTimeout(action, delay))
    schedule(20, () => emit('run_started', 1, { status: 'running' }))
    schedule(130, () => emit('model_started', 2, { turn: 1 }))
    schedule(260, () => emit('tool_call', 3, { tool_name: 'measure_bars', call_id: 'mock-call-1', arguments: { attachment_id: 'selected' } }))
    schedule(430, () => emit('tool_result', 4, { tool_name: 'measure_bars', call_id: 'mock-call-1', status: 'success', result: { bars: 3 } }))
    schedule(560, () => emit('visual_observation', 5, {
      tool_name: 'measure_bars',
      call_id: 'mock-call-1',
      observations: [{ observationId: 'mock-observation', mediaType: 'image/svg+xml', caption: '模拟柱状图测量结果', byteCount: image.length, imageUrl: image }],
    }))
    schedule(760, () => {
      if (closed) return
      const pending = pendingRuns.get(runId)
      emit('final_answer', 6, { answer: '模拟回复：已完成本次图表分析。' })
      if (target) {
        target.messages.push({ id: `user-${Date.now()}`, kind: 'user', text: pending?.text || '已提交的分析请求', timestamp, attachmentIds: pending?.attachmentIds.length ? pending.attachmentIds : undefined })
        target.messages.push({ id: `assistant-${Date.now()}`, kind: 'assistant', text: '模拟回复：已完成本次图表分析。', timestamp })
        target.session = { ...target.session, updatedAt: '刚刚', runCount: target.session.runCount + 1 }
      }
      pendingRuns.delete(runId)
      callbacks.onComplete()
    })
    return {
      close() {
        closed = true
        timers.forEach((timer) => clearTimeout(timer))
      },
    }
  },
  async submitMessage(sessionId, text, attachmentIds = []) { await wait(700); const target = data[sessionId]; target.messages.push({ id: 'user-' + Date.now(), kind: 'user', text, timestamp: '10:42', attachmentIds: attachmentIds.length ? attachmentIds : undefined }); target.messages.push({ id: 'assistant-' + Date.now(), kind: 'assistant', text: '模拟回复：已收到你的请求。下一阶段将由 Python Agent gateway 替换当前 mock adapter。', timestamp: '10:42' }); target.session = { ...target.session, updatedAt: '刚刚', runCount: target.session.runCount + 1 }; return clone(target) },
}
