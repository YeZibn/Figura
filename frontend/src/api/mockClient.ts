import type { ChartAgentClient, RunEventCallbacks, RunSubscription } from './client'
import type { AgentRunEvent, Attachment, ConversationItem, Provider, RunHandle, RunHistory, RunSummary, Session, SessionData } from '../types/protocol'

const image = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"%3E%3Crect width="640" height="360" fill="%23f7f9fb"/%3E%3Cpath d="M74 292h492M110 260V104m130 156V68m130 192V126m130 134V92" stroke="%232e8c82" stroke-width="54" stroke-linecap="round"/%3E%3Cpath d="M60 48h520" stroke="%23dbe3e8"/%3E%3C/svg%3E'
const attachments: Attachment[] = [{ id: 'att_demo_chart', filename: '季度销售.png', mediaType: 'image/png', byteCount: 16299, previewUrl: image, status: 'observation' }]
const baseMessages: ConversationItem[] = [
  { id: 'run_mock_demo:user', kind: 'user', text: '请分析这张图表，并告诉我每个类别的数值。', timestamp: '10:39', attachmentIds: ['att_demo_chart'] },
  { id: 'run_mock_demo:assistant', kind: 'assistant', text: '这张图表包含三个类别：Alpha 为 8，Beta 为 16，Gamma 为 24。测量得到的柱高约为 1:2:3，与图中打印的数值一致。', timestamp: '10:40' },
]

const demoRun: RunSummary = { runId: 'run_mock_demo', sessionId: 'chart-analysis', status: 'completed', createdAt: '2026-09-13T10:39:00+08:00', updatedAt: '2026-09-13T10:40:00+08:00', eventCount: 10, provider: 'openai', model: 'gpt-4o-mini', answer: '这张图表包含三个类别：Alpha 为 8，Beta 为 16，Gamma 为 24。测量得到的柱高约为 1:2:3，与图中打印的数值一致。' }
const demoEvents: AgentRunEvent[] = [
  { runId: demoRun.runId, sequence: 1, kind: 'run_started', timestamp: '2026-09-13T10:39:00+08:00', payload: { status: 'running', provider: 'openai', model: 'gpt-4o-mini' } },
  { runId: demoRun.runId, sequence: 2, kind: 'tool_call', timestamp: '2026-09-13T10:39:20+08:00', payload: { tool_name: 'load_image', call_id: 'demo-load', arguments: { attachment_id: 'att_demo_chart' } } },
  { runId: demoRun.runId, sequence: 3, kind: 'tool_result', timestamp: '2026-09-13T10:39:30+08:00', payload: { tool_name: 'load_image', call_id: 'demo-load', status: 'success', result: { observations: 1 } } },
  { runId: demoRun.runId, sequence: 4, kind: 'visual_observation', timestamp: '2026-09-13T10:39:31+08:00', payload: { tool_name: 'load_image', call_id: 'demo-load', observations: [{ observationId: 'demo-load-image', mediaType: 'image/svg+xml', caption: '已加载附件：季度销售.png', byteCount: image.length, imageUrl: image }] } },
  { runId: demoRun.runId, sequence: 5, kind: 'tool_call', timestamp: '2026-09-13T10:40:00+08:00', payload: { tool_name: 'measure_bars', call_id: 'demo-measure', arguments: { attachment_id: 'att_demo_chart' } } },
  { runId: demoRun.runId, sequence: 6, kind: 'tool_result', timestamp: '2026-09-13T10:40:10+08:00', payload: { tool_name: 'measure_bars', call_id: 'demo-measure', status: 'success', result: { bars: 3, orientation: 'vertical', bar_mode: 'single', baseline: { points_px: [[74, 292], [566, 292]], residual_px: 0, confidence: 0.96 }, evidence: { image_size: [640, 360], coordinate_system: 'cartesian_2d', frame: { coordinate_system: 'cartesian_2d', bbox_px: [74, 50, 492, 242], orientation: 'upright', confidence: 0.96 }, legend: [], series: [], confidence: { overall: 0.96 }, warnings: [] } } } },
  { runId: demoRun.runId, sequence: 7, kind: 'visual_observation', timestamp: '2026-09-13T10:40:11+08:00', payload: { tool_name: 'measure_bars', call_id: 'demo-measure', observations: [{ observationId: 'demo-bars-image', mediaType: 'image/svg+xml', caption: '已检测柱子、稳定标识和基线', byteCount: image.length, imageUrl: image }] } },
  { runId: demoRun.runId, sequence: 8, kind: 'generated_chart', timestamp: '2026-09-13T10:40:20+08:00', payload: { tool_name: 'render_chart', call_id: 'demo-render', artifacts: [{ artifactKind: 'generated_chart', artifactId: 'artifact_mock_chart', mediaType: 'image/png', caption: '生成图表：季度销售重绘', byteCount: image.length, chartType: 'bar', title: '季度销售重绘', width: 640, height: 360, status: 'available', imageUrl: image, downloadUrl: image }] } },
  { runId: demoRun.runId, sequence: 9, kind: 'generated_chart', timestamp: '2026-09-13T10:40:22+08:00', payload: { tool_name: 'render_chart', call_id: 'demo-expired-render', artifacts: [{ artifactKind: 'generated_chart', mediaType: 'image/png', caption: '历史生成图表', chartType: 'line', title: '历史生成图表', width: 640, height: 360, status: 'unavailable', reason: 'artifact_expired' }] } },
  { runId: demoRun.runId, sequence: 10, kind: 'final_answer', timestamp: '2026-09-13T10:40:25+08:00', payload: { answer: demoRun.answer } },
]

const data: Record<string, SessionData> = {
  'chart-analysis': { session: { id: 'chart-analysis', name: '图表分析', updatedAt: '今天 10:40', runCount: 12 }, messages: baseMessages, attachments, runs: [demoRun] },
  'sales-review': { session: { id: 'sales-review', name: '销售复盘', updatedAt: '昨天 16:18', runCount: 7 }, messages: [{ id: 's1', kind: 'assistant', text: '可以开始比较这个会话中的销售图表。', timestamp: '16:18' }], attachments: [], runs: [] },
  untitled: { session: { id: 'untitled', name: '未命名会话', updatedAt: '周一 09:12', runCount: 0 }, messages: [], attachments: [], runs: [] },
}

const pendingRuns = new Map<string, { text: string; attachmentIds: string[] }>()
const histories = new Map<string, AgentRunEvent[]>([[demoRun.runId, demoEvents]])
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T,>(value: T): T => structuredClone(value)

export const mockClient: ChartAgentClient = {
  async getHealth() {
    return { version: 'v1', status: 'ok', service: 'Figura Gateway（模拟）', agent: { status: 'ready' as const, provider: 'openai', model: 'gpt-4o-mini', providers: { openai: { status: 'ready' as const, provider: 'openai', model: 'gpt-4o-mini' }, qwen: { status: 'ready' as const, provider: 'qwen', model: 'qwen3.8-flash' } } } }
  },

  async listSessions() { await wait(120); return Object.values(data).map((entry) => clone(entry.session)) },
  async getSession(id) { await wait(160); return clone(data[id]) },
  async createSession(name) { await wait(160); const id = 'session-' + Date.now(); const session: Session = { id, name, updatedAt: '刚刚', runCount: 0 }; data[id] = { session, messages: [], attachments: [], runs: [] }; return clone(data[id]) },
  async deleteSession(id) { await wait(140); if (!data[id]) throw new Error('会话不存在'); delete data[id] },
  async listAttachments(sessionId) { await wait(80); return clone(data[sessionId]?.attachments ?? []) },
  async uploadAttachment(sessionId, file) {
    await wait(240)
    const target = data[sessionId]
    const attachment: Attachment = { id: 'att_mock_' + Date.now(), filename: file.name, mediaType: file.type || 'image/png', byteCount: file.size, previewUrl: URL.createObjectURL(file), status: 'registered', previewAvailable: true }
    target.attachments.push(attachment)
    return clone(attachment)
  },
  async deleteAttachment(sessionId, attachmentId) {
    await wait(120)
    const target = data[sessionId]
    const index = target?.attachments.findIndex((item) => item.id === attachmentId) ?? -1
    if (!target || index < 0) throw new Error('附件不存在')
    const [removed] = target.attachments.splice(index, 1)
    if (removed.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(removed.previewUrl)
  },
  attachmentContentUrl(sessionId, attachmentId) {
    return data[sessionId]?.attachments.find((item) => item.id === attachmentId)?.previewUrl || ''
  },
  generatedArtifactUrl(_sessionId, _runId, _artifactId) {
    return image
  },
  async startRun(sessionId, text, attachmentIds = [], provider: Provider = 'openai') {
    await wait(90)
    const runId = `run_mock_${Date.now()}`
    pendingRuns.set(runId, { text, attachmentIds })
    const target = data[sessionId]
    if (target) target.runs.push({ runId, sessionId, status: 'running', provider, model: provider === 'qwen' ? 'qwen3.8-flash' : 'gpt-4o-mini', createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), eventCount: 0 })
    return { runId, sessionId, status: 'running', provider, model: provider === 'qwen' ? 'qwen3.8-flash' : 'gpt-4o-mini' }
  },
  async getRunHistory(sessionId, runId, afterSequence = 0): Promise<RunHistory> {
    await wait(40)
    const target = data[sessionId]
    const run = target?.runs.find((item) => item.runId === runId)
    if (!target || !run) throw new Error('运行记录不存在')
    return { run: clone(run), events: clone((histories.get(runId) || []).filter((event) => event.sequence > afterSequence)), historyGap: false }
  },
  subscribeRun(sessionId, runId, callbacks: RunEventCallbacks, afterSequence = 0): RunSubscription {
    let closed = false
    const timers: ReturnType<typeof setTimeout>[] = []
    const target = data[sessionId]
    const timestamp = '刚刚'
    const emit = (kind: string, sequence: number, payload: Record<string, unknown> = {}) => {
      if (closed) return
      const event = { runId, sequence, kind, timestamp, payload } as AgentRunEvent
      const history = histories.get(runId) || []
      if (!history.some((item) => item.sequence === sequence)) history.push(event)
      histories.set(runId, history)
      const summary = target?.runs.find((item) => item.runId === runId)
      if (summary) { summary.eventCount = history.length; summary.updatedAt = new Date().toISOString() }
      if (sequence > afterSequence) callbacks.onEvent(event)
    }
    const schedule = (delay: number, action: () => void) => timers.push(setTimeout(action, delay))
    const provider = target?.runs.find((item) => item.runId === runId)?.provider || 'openai'
    const model = target?.runs.find((item) => item.runId === runId)?.model || (provider === 'qwen' ? 'qwen3.8-flash' : 'gpt-4o-mini')
    schedule(20, () => emit('run_started', 1, { status: 'running', provider, model }))
    schedule(130, () => emit('model_started', 2, { turn: 1, provider, model }))
    schedule(260, () => emit('tool_call', 3, { tool_name: 'measure_bars', call_id: 'mock-call-1', arguments: { attachment_id: 'selected' } }))
    schedule(430, () => emit('tool_result', 4, { tool_name: 'measure_bars', call_id: 'mock-call-1', status: 'success', result: { bars: 3, evidence: { coordinate_system: 'cartesian_2d', frame: null, confidence: { overall: 0.5 }, warnings: [] } } }))
    schedule(560, () => emit('visual_observation', 5, {
      tool_name: 'measure_bars',
      call_id: 'mock-call-1',
      observations: [{ observationId: 'mock-observation', mediaType: 'image/svg+xml', caption: '模拟柱状图测量结果', byteCount: image.length, imageUrl: image }],
    }))
    schedule(650, () => emit('generated_chart', 6, {
      tool_name: 'render_chart',
      call_id: 'mock-render-1',
      artifacts: [{ artifactKind: 'generated_chart', artifactId: `artifact_${runId}`, mediaType: 'image/png', caption: '生成图表：分析结果重绘', byteCount: image.length, chartType: 'bar', title: '分析结果重绘', width: 640, height: 360, status: 'available', imageUrl: image, downloadUrl: image }],
    }))
    schedule(760, () => {
      if (closed) return
      const pending = pendingRuns.get(runId)
      emit('final_answer', 7, { answer: '模拟回复：已完成本次图表分析。' })
      if (target) {
        target.messages.push({ id: `${runId}:user`, kind: 'user', text: pending?.text || '已提交的分析请求', timestamp, attachmentIds: pending?.attachmentIds.length ? pending.attachmentIds : undefined })
        target.messages.push({ id: `${runId}:assistant`, kind: 'assistant', text: '模拟回复：已完成本次图表分析。', timestamp })
        target.session = { ...target.session, updatedAt: '刚刚', runCount: target.session.runCount + 1 }
      }
      pendingRuns.delete(runId)
      const summary = target?.runs.find((item) => item.runId === runId)
      if (summary) { summary.status = 'completed'; summary.answer = '模拟回复：已完成本次图表分析。'; summary.updatedAt = new Date().toISOString() }
      callbacks.onComplete()
    })
    return {
      close() {
        closed = true
        timers.forEach((timer) => clearTimeout(timer))
      },
    }
  },
  async submitMessage(sessionId, text, attachmentIds = [], _provider?: Provider) { await wait(700); const target = data[sessionId]; target.messages.push({ id: 'user-' + Date.now(), kind: 'user', text, timestamp: '10:42', attachmentIds: attachmentIds.length ? attachmentIds : undefined }); target.messages.push({ id: 'assistant-' + Date.now(), kind: 'assistant', text: '模拟回复：已收到你的请求。', timestamp: '10:42' }); target.session = { ...target.session, updatedAt: '刚刚', runCount: target.session.runCount + 1 }; return clone(target) },
}
