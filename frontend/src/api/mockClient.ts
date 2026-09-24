import type { ChartAgentClient, RunEventCallbacks, RunResumeOptions, RunStartOptions, RunSubscription } from './client'
import type { AgentRunEvent, Attachment, Provider, RunHistory, Session } from '../types/protocol'
import { createMockData, createMockHistories, mockImage } from './mock/fixtures'

const data = createMockData()

const pendingRuns = new Map<string, { text: string; attachmentIds: string[] }>()
const idempotentRuns = new Map<string, string>()
const idempotentRequests = new Map<string, string>()
const histories = createMockHistories()
type MockSubscription = { interrupt(): void }
const subscriptions = new Map<string, Set<MockSubscription>>()
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T,>(value: T): T => structuredClone(value)

export const mockClient: ChartAgentClient = {
  async getHealth() {
    return { version: 'v1', status: 'ok', service: 'Figura Gateway（模拟）', agent: { status: 'ready' as const, provider: 'openai', model: 'gpt-4o-mini', providers: { openai: { status: 'ready' as const, provider: 'openai', model: 'gpt-4o-mini' }, qwen: { status: 'ready' as const, provider: 'qwen', model: 'qwen3.8-flash' }, deepseek: { status: 'ready' as const, provider: 'deepseek', model: 'deepseek-flash' } } } }
  },

  async listSessions() { await wait(120); return Object.values(data).map((entry) => clone(entry.session)) },
  async listEvaluations() { await wait(80); return [] },
  async getEvaluation(_id) { await wait(80); throw new Error('模拟模式没有评测记录') },
  async getEvaluationCase(_evaluationId, _caseId) { await wait(80); throw new Error('模拟模式没有评测记录') },
  async getEvaluationHistory(_evaluationId, _caseId, _afterSequence = 0) { await wait(80); throw new Error('模拟模式没有评测记录') },
  async getEvaluationHistoryDetails(_evaluationId, _caseId, _afterRecordSequence = 0) { await wait(80); throw new Error('模拟模式没有评测记录') },
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
    return mockImage
  },
  async startRun(sessionId, text, attachmentIds = [], provider: Provider = 'openai', options: RunStartOptions = {}) {
    await wait(90)
    if (options.idempotencyKey) {
      const request = JSON.stringify({ sessionId, text, attachmentIds, provider, retryOf: options.retryOf || null })
      const previousRequest = idempotentRequests.get(options.idempotencyKey)
      if (previousRequest && previousRequest !== request) {
        const error = new Error('请求标识已对应其他内容') as Error & { code: string; status: number }
        error.code = 'idempotency_conflict'
        error.status = 409
        throw error
      }
      const existingId = idempotentRuns.get(options.idempotencyKey)
      const existing = existingId ? data[sessionId]?.runs.find((item) => item.runId === existingId) : undefined
      if (existing) return { runId: existing.runId, sessionId, status: existing.status, provider: existing.provider, model: existing.model, retryOf: existing.retryOf }
      idempotentRequests.set(options.idempotencyKey, request)
    }
    const runId = `run_mock_${Date.now()}`
    pendingRuns.set(runId, { text, attachmentIds })
    const target = data[sessionId]
    const model = provider === 'qwen' ? 'qwen3.8-flash' : provider === 'deepseek' ? 'deepseek-flash' : 'gpt-4o-mini'
    if (target) target.runs.push({ runId, sessionId, status: 'running', provider, model, retryOf: options.retryOf, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), eventCount: 0, parentRunId: options.retryOf, rootRunId: options.retryOf || runId, continuationKind: options.retryOf ? 'retry' : null, recovery: { status: 'available', cursorId: `cur_mock_${runId}`, nextAction: 'model' } })
    if (options.idempotencyKey) idempotentRuns.set(options.idempotencyKey, runId)
    return { runId, sessionId, status: 'running', provider, model, retryOf: options.retryOf, parentRunId: options.retryOf, rootRunId: options.retryOf || runId, continuationKind: options.retryOf ? 'retry' : null, recovery: { status: 'available', cursorId: `cur_mock_${runId}`, nextAction: 'model' } }
  },
  async interruptRun(sessionId, runId) {
    const target = data[sessionId]
    const summary = target?.runs.find((item) => item.runId === runId)
    if (!target || !summary) throw new Error('运行记录不存在')
    if (summary.status === 'running') {
      summary.status = 'interrupted'
      summary.cancelRequested = true
      summary.terminalCode = 'user_cancelled'
      summary.terminalMessage = '运行已按用户请求中断'
      summary.updatedAt = new Date().toISOString()
      const sequence = Math.max(...(histories.get(runId) || []).map((event) => event.sequence), 0) + 1
      const payload = { status: 'interrupted', code: 'user_cancelled', reason: 'user_cancelled', message: '运行已按用户请求中断' }
      const history = histories.get(runId) || []
      if (!history.some((event) => event.sequence === sequence)) history.push({ runId, sequence, kind: 'run_interrupted', timestamp: '刚刚', payload })
      histories.set(runId, history)
      subscriptions.get(runId)?.forEach((subscription) => subscription.interrupt())
    }
    return { runId, sessionId, status: summary.status, provider: summary.provider, model: summary.model, terminalCode: summary.terminalCode, terminalMessage: summary.terminalMessage, retryOf: summary.retryOf, parentRunId: summary.parentRunId, rootRunId: summary.rootRunId, continuationKind: summary.continuationKind, recovery: summary.recovery }
  },
  async resumeRun(sessionId, runId, options: RunResumeOptions) {
    await wait(90)
    const target = data[sessionId]
    const parent = target?.runs.find((item) => item.runId === runId)
    if (!target || !parent) throw new Error('运行记录不存在')
    if (parent.status === 'running') throw new Error('运行尚未结束')
    if (parent.recovery?.status !== 'available') {
      const error = new Error('该运行暂时无法继续执行') as Error & { code: string; status: number }
      error.code = parent.recovery?.status === 'blocked' ? 'recovery_blocked' : 'recovery_unavailable'
      error.status = 409
      throw error
    }
    const request = JSON.stringify({ sessionId, runId, cursorId: options.cursorId || parent.recovery.cursorId || null })
    const previousRequest = idempotentRequests.get(options.idempotencyKey)
    if (previousRequest && previousRequest !== request) {
      const error = new Error('恢复请求标识已用于其他请求') as Error & { code: string; status: number }
      error.code = 'resume_idempotency_conflict'
      error.status = 409
      throw error
    }
    const existingId = idempotentRuns.get(options.idempotencyKey)
    const existing = existingId ? target.runs.find((item) => item.runId === existingId) : undefined
    if (existing) return { runId: existing.runId, sessionId, status: existing.status, provider: existing.provider, model: existing.model, parentRunId: existing.parentRunId, rootRunId: existing.rootRunId, continuationKind: existing.continuationKind, recovery: existing.recovery }
    idempotentRequests.set(options.idempotencyKey, request)
    const childId = `run_mock_${Date.now()}`
    const model = parent.model || 'gpt-4o-mini'
    pendingRuns.set(childId, { text: '继续执行已提交的图表分析', attachmentIds: [] })
    target.runs.push({ runId: childId, sessionId, status: 'running', provider: parent.provider, model, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), eventCount: 0, parentRunId: runId, rootRunId: parent.rootRunId || runId, continuationKind: 'resume', recovery: { status: 'available', cursorId: `cur_mock_${childId}`, nextAction: 'model' } })
    idempotentRuns.set(options.idempotencyKey, childId)
    return { runId: childId, sessionId, status: 'running', provider: parent.provider, model, parentRunId: runId, rootRunId: parent.rootRunId || runId, continuationKind: 'resume', recovery: { status: 'available', cursorId: `cur_mock_${childId}`, nextAction: 'model' } }
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
    const runSummary = target?.runs.find((item) => item.runId === runId)
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
    const model = target?.runs.find((item) => item.runId === runId)?.model || (provider === 'qwen' ? 'qwen3.8-flash' : provider === 'deepseek' ? 'deepseek-flash' : 'gpt-4o-mini')
    schedule(20, () => emit('run_started', 1, { status: 'running', provider, model }))
    schedule(130, () => emit('model_started', 2, { turn: 1, provider, model }))
    const measurementUnit = { correlation_version: 2, unit_id: 'measurement:mock-attempt-1', unit_type: 'measurement', phase: 'observe', actor: 'tool', role: 'observation', transition_id: 'measurement:mock-attempt-1:observed' }
    schedule(260, () => emit('tool_call', 3, { ...measurementUnit, phase: 'action', state: 'running', transition_id: 'measurement:mock-attempt-1:started', tool_name: 'measure_bars', call_id: 'mock-call-1', arguments: { attachment_id: 'selected' } }))
    schedule(430, () => emit('tool_result', 4, { ...measurementUnit, tool_name: 'measure_bars', call_id: 'mock-call-1', status: 'success', result: { bars: 3, evidence: { coordinate_system: 'cartesian_2d', frame: null, confidence: { overall: 0.5 }, warnings: [] } } }))
    schedule(560, () => emit('visual_observation', 5, {
      ...measurementUnit,
      state: 'observed',
      phase: 'observe',
      role: 'observation',
      transition_id: 'measurement:mock-attempt-1:observed',
      tool_name: 'measure_bars',
      call_id: 'mock-call-1',
      observations: [{ observationId: 'mock-observation', mediaType: 'image/svg+xml', caption: '模拟柱状图测量结果', byteCount: mockImage.length, imageUrl: mockImage }],
    }))
    schedule(650, () => emit('chart_staged', 6, {
      correlation_version: 2,
      unit_id: 'generation:stg_mock_chart_1',
      unit_type: 'generation',
      phase: 'render',
      actor: 'tool',
      role: 'action',
      transition_id: 'generation:stg_mock_chart_1:staged',
      staged_ref: 'stg_mock_chart_1',
      state: 'staged',
      chart_type: 'bar',
      title: '分析结果重绘',
      media_type: 'image/png',
      caption: '生成图表：分析结果重绘',
      chart_spec_digest: 'mock-chart-spec-digest',
      manifest_digest: 'mock-chart-manifest-digest',
      width: 640,
      height: 360,
      call_id: 'mock-render-1',
      imageUrl: mockImage,
    }))
    schedule(700, () => emit('chart_verification_result', 7, {
      correlation_version: 2,
      unit_id: 'verification:ver_mock_chart_1',
      unit_type: 'verification',
      parent_unit_id: 'generation:stg_mock_chart_1',
      phase: 'verify',
      actor: 'system',
      role: 'verification',
      transition_id: 'verification:ver_mock_chart_1:completed',
      staged_ref: 'stg_mock_chart_1',
      verification_ref: 'ver_mock_chart_1',
      state: 'pass_with_warning',
      verification: {
        verificationRef: 'ver_mock_chart_1',
        stagedRef: 'stg_mock_chart_1',
        manifestDigest: 'mock-chart-manifest-digest',
        policyVersion: 1,
        status: 'pass_with_warning',
        checks: { structure: 'pass', encoded_artifact: 'pass' },
        issues: [{ code: 'mock_label_review', location: 'labels', message: '部分标签较小', severity: 'warning' }],
        decision: 'pass_with_warning',
        confidence: 0.9,
        attempt: 1,
      },
    }))
    schedule(730, () => emit('chart_promotion_result', 8, {
      correlation_version: 2,
      unit_id: `artifact:artifact_${runId}`,
      unit_type: 'artifact',
      parent_unit_id: 'generation:stg_mock_chart_1',
      phase: 'publish',
      actor: 'system',
      role: 'artifact',
      transition_id: `artifact:artifact_${runId}:published`,
      staged_ref: 'stg_mock_chart_1',
      verification_ref: 'ver_mock_chart_1',
      artifact_id: `artifact_${runId}`,
      state: 'published_with_warning',
      warning: true,
      imageUrl: mockImage,
      downloadUrl: mockImage,
    }))
    const subscription: MockSubscription = {
      interrupt() {
        if (closed) return
        emit('run_interrupted', Math.max(...(histories.get(runId) || []).map((event) => event.sequence), 0), {
          status: 'interrupted',
          code: 'user_cancelled',
          reason: 'user_cancelled',
          message: '运行已按用户请求中断',
        })
        closed = true
        timers.forEach((timer) => clearTimeout(timer))
        callbacks.onComplete()
        subscriptions.get(runId)?.delete(subscription)
      },
    }
    const registered = subscriptions.get(runId) || new Set<MockSubscription>()
    registered.add(subscription)
    subscriptions.set(runId, registered)
    schedule(760, () => {
      if (closed) return
      const pending = pendingRuns.get(runId)
      if (runSummary?.status !== 'running') return
      emit('final_answer', 9, { answer: '模拟回复：已完成本次图表分析。' })
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
        subscriptions.get(runId)?.delete(subscription)
      },
    }
  },
  async submitMessage(sessionId, text, attachmentIds = [], _provider?: Provider) { await wait(700); const target = data[sessionId]; target.messages.push({ id: 'user-' + Date.now(), kind: 'user', text, timestamp: '10:42', attachmentIds: attachmentIds.length ? attachmentIds : undefined }); target.messages.push({ id: 'assistant-' + Date.now(), kind: 'assistant', text: '模拟回复：已收到你的请求。', timestamp: '10:42' }); target.session = { ...target.session, updatedAt: '刚刚', runCount: target.session.runCount + 1 }; return clone(target) },
}
