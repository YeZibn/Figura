import type {
  FiguraToolTimelineStatus,
  FiguraToolTimelineStepDto,
} from '../../api/figura/types'

const toolLabels: Record<string, string> = {
  load_image: '读取图像',
  decompose_chart_image: '拆分图像',
  extract_text: '提取文字',
  measure_bars: '测量柱状图',
  measure_lines: '测量折线图',
  measure_scatter: '测量散点图',
  measure_pie: '测量饼图',
  assemble_chart_figure: '装配图表',
  render_chart_figure: '绘制图表',
}

const statusLabels: Record<FiguraToolTimelineStatus, string> = {
  pending: '等待执行',
  running: '运行中',
  needs_reconciliation: '等待结果核对',
  unknown: '状态未知',
  completed: '已完成',
  failed: '失败',
  not_started: '未执行',
}

export type FiguraToolTimelineStepViewModel = FiguraToolTimelineStepDto & {
  id: string
  label: string
  statusLabel: string
}

export function mapFiguraToolTimelineStep(
  runId: string,
  step: FiguraToolTimelineStepDto,
): FiguraToolTimelineStepViewModel {
  return {
    ...step,
    id: runId + ':' + step.callId,
    label: toolLabels[step.toolName] || step.toolName,
    statusLabel: statusLabels[step.status],
  }
}

export function figuraToolAttemptStatusLabel(
  status: 'running' | 'completed' | 'failed' | 'unknown',
): string {
  return status === 'running'
    ? '运行中'
    : status === 'completed'
      ? '已完成'
      : status === 'failed'
        ? '失败'
        : '状态未知'
}
