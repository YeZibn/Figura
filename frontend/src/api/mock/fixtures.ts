import type { AgentRunEvent, Attachment, ConversationItem, RunSummary, Session, SessionData } from '../../types/protocol'

export const mockImage = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"%3E%3Crect width="640" height="360" fill="%23f7f9fb"/%3E%3Cpath d="M74 292h492M110 260V104m130 156V68m130 192V126m130 134V92" stroke="%232e8c82" stroke-width="54" stroke-linecap="round"/%3E%3Cpath d="M60 48h520" stroke="%23dbe3e8"/%3E%3C/svg%3E'

export const mockAttachments: Attachment[] = [{ id: 'att_demo_chart', filename: '季度销售.png', mediaType: 'image/png', byteCount: 16299, previewUrl: mockImage, status: 'observation' }]

export const mockBaseMessages: ConversationItem[] = [
  { id: 'run_mock_demo:user', kind: 'user', text: '请分析这张图表，并告诉我每个类别的数值。', timestamp: '10:39', attachmentIds: ['att_demo_chart'] },
  { id: 'run_mock_demo:assistant', kind: 'assistant', text: '这张图表包含三个类别：Alpha 为 8，Beta 为 16，Gamma 为 24。测量得到的柱高约为 1:2:3，与图中打印的数值一致。', timestamp: '10:40' },
]

export const mockDemoRun: RunSummary = { runId: 'run_mock_demo', sessionId: 'chart-analysis', status: 'completed', createdAt: '2026-09-13T10:39:00+08:00', updatedAt: '2026-09-13T10:40:00+08:00', eventCount: 10, provider: 'openai', model: 'gpt-4o-mini', answer: '这张图表包含三个类别：Alpha 为 8，Beta 为 16，Gamma 为 24。测量得到的柱高约为 1:2:3，与图中打印的数值一致。' }
export const mockRepairDemoRun: RunSummary = { runId: 'run_mock_repair', sessionId: 'sales-review', status: 'failed', createdAt: '2026-09-14T16:10:00+08:00', updatedAt: '2026-09-14T16:12:00+08:00', eventCount: 8, provider: 'qwen', model: 'qwen3.8-flash', terminalCode: 'measurement_repair_exhausted', terminalMessage: '定向重测次数已用尽' }

export const mockDemoEvents: AgentRunEvent[] = [
  { runId: mockDemoRun.runId, sequence: 1, kind: 'run_started', timestamp: '2026-09-13T10:39:00+08:00', payload: { status: 'running', provider: 'openai', model: 'gpt-4o-mini' } },
  { runId: mockDemoRun.runId, sequence: 2, kind: 'tool_call', timestamp: '2026-09-13T10:39:20+08:00', payload: { tool_name: 'load_image', call_id: 'demo-load', arguments: { attachment_id: 'att_demo_chart' } } },
  { runId: mockDemoRun.runId, sequence: 3, kind: 'tool_result', timestamp: '2026-09-13T10:39:30+08:00', payload: { tool_name: 'load_image', call_id: 'demo-load', status: 'success', result: { observations: 1 } } },
  { runId: mockDemoRun.runId, sequence: 4, kind: 'visual_observation', timestamp: '2026-09-13T10:39:31+08:00', payload: { tool_name: 'load_image', call_id: 'demo-load', observations: [{ observationId: 'demo-load-image', mediaType: 'image/svg+xml', caption: '已加载附件：季度销售.png', byteCount: mockImage.length, imageUrl: mockImage }] } },
  { runId: mockDemoRun.runId, sequence: 5, kind: 'tool_call', timestamp: '2026-09-13T10:40:00+08:00', payload: { tool_name: 'measure_bars', call_id: 'demo-measure', arguments: { attachment_id: 'att_demo_chart' } } },
  { runId: mockDemoRun.runId, sequence: 6, kind: 'tool_result', timestamp: '2026-09-13T10:40:10+08:00', payload: { tool_name: 'measure_bars', call_id: 'demo-measure', status: 'success', result: { bars: 3, orientation: 'vertical', bar_mode: 'single', baseline: { points_px: [[74, 292], [566, 292]], residual_px: 0, confidence: 0.96 }, evidence: { image_size: [640, 360], coordinate_system: 'cartesian_2d', frame: { coordinate_system: 'cartesian_2d', bbox_px: [74, 50, 492, 242], orientation: 'upright', confidence: 0.96 }, legend: [], series: [], confidence: { overall: 0.96 }, warnings: [] } } } },
  { runId: mockDemoRun.runId, sequence: 7, kind: 'visual_observation', timestamp: '2026-09-13T10:40:11+08:00', payload: { tool_name: 'measure_bars', call_id: 'demo-measure', observations: [{ observationId: 'demo-bars-image', mediaType: 'image/svg+xml', caption: '已检测柱子、稳定标识和基线', byteCount: mockImage.length, imageUrl: mockImage }] } },
  { runId: mockDemoRun.runId, sequence: 8, kind: 'generated_chart', timestamp: '2026-09-13T10:40:20+08:00', payload: { tool_name: 'render_chart', call_id: 'demo-render', artifacts: [{ artifactKind: 'generated_chart', artifactId: 'artifact_mock_chart', mediaType: 'image/png', caption: '生成图表：季度销售重绘', byteCount: mockImage.length, chartType: 'bar', title: '季度销售重绘', width: 640, height: 360, status: 'available', imageUrl: mockImage, downloadUrl: mockImage }] } },
  { runId: mockDemoRun.runId, sequence: 9, kind: 'generated_chart', timestamp: '2026-09-13T10:40:22+08:00', payload: { tool_name: 'render_chart', call_id: 'demo-expired-render', artifacts: [{ artifactKind: 'generated_chart', mediaType: 'image/png', caption: '历史生成图表', chartType: 'line', title: '历史生成图表', width: 640, height: 360, status: 'unavailable', reason: 'artifact_expired' }] } },
  { runId: mockDemoRun.runId, sequence: 10, kind: 'final_answer', timestamp: '2026-09-13T10:40:25+08:00', payload: { answer: mockDemoRun.answer } },
]

export const mockRepairDemoEvents: AgentRunEvent[] = [
  { runId: mockRepairDemoRun.runId, sequence: 1, kind: 'run_started', timestamp: '2026-09-14T16:10:00+08:00', payload: { status: 'running', provider: 'qwen', model: 'qwen3.8-flash' } },
  { runId: mockRepairDemoRun.runId, sequence: 2, kind: 'tool_result', timestamp: '2026-09-14T16:10:40+08:00', payload: { tool_name: 'measure_bars', call_id: 'repair-measure-1', status: 'success', result: { measurement: 'quality_gate_required' } } },
  { runId: mockRepairDemoRun.runId, sequence: 3, kind: 'measurement_repair_required', timestamp: '2026-09-14T16:10:41+08:00', payload: { tool_name: 'measure_bars', call_id: 'repair-measure-1', repair: { attachment_id: 'att_demo_chart', panel_id: 'panel_left_bars', parent_attempt_id: 'matt_1', target: { region_kind: 'baseline', fields: ['baseline', 'bars.measure'] }, status: 'available', next_action: '在同一 panel 内重新测量' } } },
  { runId: mockRepairDemoRun.runId, sequence: 4, kind: 'measurement_repair_rejected', timestamp: '2026-09-14T16:11:05+08:00', payload: { panel_id: 'panel_left_bars', parent_attempt_id: 'matt_1', status: 'rejected', code: 'measurement_target_invalid', reason: '目标区域不再属于当前面板', next_action: '重新读取当前 panel 的 repair_action' } },
  { runId: mockRepairDemoRun.runId, sequence: 5, kind: 'measurement_repair_required', timestamp: '2026-09-14T16:11:20+08:00', payload: { repair: { panel_id: 'panel_left_bars', attempt_id: 'matt_2', parent_attempt_id: 'matt_1', target: { region_kind: 'bar_group' }, status: 'available', budget_remaining: 1, next_action: '在同一面板内重新测量柱体和基准线' } } },
  { runId: mockRepairDemoRun.runId, sequence: 6, kind: 'measurement_repair_exhausted', timestamp: '2026-09-14T16:11:50+08:00', payload: { panel_id: 'panel_left_bars', attempt_id: 'matt_2', parent_attempt_id: 'matt_1', status: 'exhausted', budget_remaining: 0, reason: '定向重测未收敛', next_action: '保留失败证据并停止定向重测' } },
  { runId: mockRepairDemoRun.runId, sequence: 7, kind: 'measurement_repair_future_state', timestamp: '2026-09-14T16:11:51+08:00', payload: { status: 'pending' } },
  { runId: mockRepairDemoRun.runId, sequence: 8, kind: 'run_failed', timestamp: '2026-09-14T16:12:00+08:00', payload: { code: mockRepairDemoRun.terminalCode, message: mockRepairDemoRun.terminalMessage } },
]

export function createMockData(): Record<string, SessionData> {
  return {
    'chart-analysis': { session: { id: 'chart-analysis', name: '图表分析', updatedAt: '今天 10:40', runCount: 12 }, messages: mockBaseMessages, attachments: mockAttachments, runs: [mockDemoRun] },
    'sales-review': { session: { id: 'sales-review', name: '销售复盘', updatedAt: '昨天 16:18', runCount: 8 }, messages: [{ id: 's1', kind: 'assistant', text: '可以开始比较这个会话中的销售图表。', timestamp: '16:18' }], attachments: [], runs: [mockRepairDemoRun] },
    untitled: { session: { id: 'untitled', name: '未命名会话', updatedAt: '周一 09:12', runCount: 0 }, messages: [], attachments: [], runs: [] },
  }
}

export function createMockHistories(): Map<string, AgentRunEvent[]> {
  return new Map([[mockDemoRun.runId, mockDemoEvents], [mockRepairDemoRun.runId, mockRepairDemoEvents]])
}

