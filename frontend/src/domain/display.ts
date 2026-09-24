import type { GatewayHealth, Provider, RunState, AttachmentStatus, EvaluationDetailEntry, EvaluationResource, EvaluationStatus, AgentRunEvent } from '../types/protocol'
import type { GatewayRuntimeStatus } from '../runtime'

export function statusLabel(status: AttachmentStatus): string {
  if (status === 'uploading') return '正在上传'
  if (status === 'registered') return '已登记'
  if (status === 'unavailable') return '源文件不可用'
  if (status === 'loaded') return '已加载到模型'
  if (status === 'observation') return '已有视觉观察'
  if (status === 'error') return '上传失败'
  return '待处理'
}

export function toolStatusLabel(status: 'success' | 'running' | 'error'): string {
  if (status === 'success') return '已完成'
  if (status === 'running') return '运行中'
  return '失败'
}

const timelineEventStatusLabels: Record<string, Record<string, string>> = {
  tool_call: { running: '运行中' },
  tool_result: { success: '已完成', error: '失败' },
  tool_skipped: { not_started: '未执行' },
  visual_observation: { observed: '已观察' },
  chart_staged: { staged: '已暂存', unavailable: '暂不可用' },
  chart_verification_result: { pass: '验证通过', pass_with_warning: '验证通过·有警告', fail: '验证未通过', unavailable: '验证不可用' },
  chart_promotion_result: { published: '已发布', published_with_warning: '已发布·有警告' },
  assembly_validation_failure: { failed: '组装校验失败' },
}

export function timelineEventStatusLabel(kind: string, value: unknown): string | undefined {
  const labels = timelineEventStatusLabels[kind]
  if (!labels) return undefined
  const status = typeof value === 'string' ? value.trim().toLowerCase() : ''
  return labels[status] || '状态未知'
}

export function runStateLabel(state: RunState): string {
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

export const providerLabels: Record<Provider, string> = {
  openai: 'OpenAI（中转站）',
  qwen: 'Qwen（DashScope）',
  deepseek: 'DeepSeek（V4.1 Flash）',
}

export function providerLabel(provider?: Provider | null): string {
  return provider ? providerLabels[provider] : ''
}

export function providerStatus(health: GatewayHealth | null, provider: Provider, mode: 'mock' | 'gateway'): 'ready' | 'unavailable' | 'unknown' {
  const status = health?.agent?.providers?.[provider]?.status
  if (status) return status
  if (health?.agent?.provider === provider) return health.agent.status
  return health || mode === 'gateway' ? 'unknown' : 'ready'
}

export function currentTime(): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

export function timestampLabel(timestamp: string): string {
  if (!timestamp) return currentTime()
  const parsed = new Date(timestamp)
  return Number.isNaN(parsed.valueOf()) ? timestamp : parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export function chartTypeLabel(value: string): string {
  return ({ bar: '柱状图', line: '折线图', pie: '饼图', scatter: '散点图' } as Record<string, string>)[value] || value || '图表'
}

export function eventLabel(event: AgentRunEvent): string {
  const labels: Record<string, string> = {
    run_started: '运行已开始',
    resume_started: '继续执行已开始',
    model_started: '模型轮次开始',
    model_completed: '模型轮次完成',
    recovery_blocked: '继续执行被阻止',
    progress: '处理中',
    chart_staged: '图表已暂存',
    chart_verification_result: '图表验证结果',
    chart_promotion_result: '图表已发布',
    assembly_validation_failure: 'ChartSpec 组装校验失败',
    tool_skipped: '工具未执行',
    final_answer: '最终回答已生成',
    budget_exhausted: '达到预算上限',
    run_failed: '运行失败',
    run_interrupted: '运行已中断',
    history_gap: '历史记录不完整',
    tool_result: '工具结果',
  }
  return labels[event.kind] || '技术事件'
}

export function failureCategoryLabel(value?: string): string {
  return ({
    provider_balance: 'Provider 余额不足',
    provider_authorization: 'Provider 鉴权失败',
    provider_rate_limit: 'Provider 请求受限',
    provider_rate_limited: 'Provider 请求受限',
    provider_request: 'Provider 请求被拒绝',
    provider_request_rejected: 'Provider 请求被拒绝',
    provider_transient: 'Provider 临时故障',
    provider_failure: 'Provider 请求失败',
    transport_uncertain: '远端结果未知',
    source_scope: '源图范围错误',
    measurement_evidence: '测量证据错误',
    assembly_validation: '图表组装校验失败',
    tool_rejected: '工具拒绝执行',
  } as Record<string, string>)[value || ''] || value || '执行失败'
}

export function gatewayStatusText(mode: 'mock' | 'gateway', runtimeStatus: GatewayRuntimeStatus | null, health: GatewayHealth | null): string {
  if (mode === 'mock') return '可离线使用'
  if (runtimeStatus?.state === 'unavailable') return '本地服务不可用'
  const agentState = runtimeStatus?.agentState || health?.agent?.status
  if (agentState === 'unavailable') return 'Agent 配置不可用'
  if (agentState === 'ready') return 'Agent 已就绪'
  if (agentState === 'starting') return 'Agent 正在启动'
  if (runtimeStatus?.state === 'ready') return '本地服务已就绪'
  return '本地服务连接中'
}

export function evaluationStatusLabel(status: EvaluationStatus): string {
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
  if (status === 'blocked') return '已阻塞'
  return '部分完成'
}

export function evaluationStatusClass(status: EvaluationStatus): string {
  return status === 'completed' ? 'completed' : status === 'running' ? 'running' : status === 'blocked' ? 'failed' : 'partial'
}

export function evaluationResourceLabel(resource: EvaluationResource): string {
  if (resource.kind === 'input') return '输入图'
  if (resource.kind === 'report_image') return '报告图片'
  if (resource.kind === 'observation') return '视觉观察'
  if (resource.kind === 'artifact') return '生成结果'
  return resource.label || '评测证据'
}

export function evaluationDetailEntryLabel(entry: EvaluationDetailEntry): string {
  if (entry.kind === 'conversation') return entry.role === 'user' ? '用户消息' : entry.role === 'assistant' ? '模型消息' : '系统消息'
  if (entry.kind === 'tool_message') return '模型可见工具消息'
  if (entry.kind === 'tool_call') return entry.toolLabel || entry.toolName || '工具调用'
  if (entry.kind === 'tool_result') return (entry.toolLabel || entry.toolName || '工具') + ' · 工具结果'
  if (entry.kind === 'verification_result') return '图表验证结果'
  if (entry.kind === 'visual_observation') return '视觉观察'
  if (entry.kind === 'generated_chart') return '生成结果'
  return '运行记录'
}

export function evaluationDetailSequenceLabel(entry: EvaluationDetailEntry): string {
  if (typeof entry.recordSequence === 'number') return 'record #' + entry.recordSequence
  if (typeof entry.eventSequence === 'number') return 'event #' + entry.eventSequence
  return '未编号'
}

export function toolResultIntegrityDetail(payload: Record<string, unknown>): string {
  if (payload.detailUnavailable) return '工具结果在持久化阶段已截断，当前 bundle 没有可恢复的完整资源。'
  if (payload.detailResource) return '工具结果超过普通事件容量，可按需加载完整安全结果。'
  return '工具结果已按安全上限截断。'
}
