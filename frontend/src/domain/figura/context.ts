import type { RunSummary } from '../../types/run'

export function selectContextRun(runs: RunSummary[], activeRunId: string): RunSummary | undefined {
  if (activeRunId) return runs.find((run) => run.runId === activeRunId)
  return runs.reduce<RunSummary | undefined>((latest, run) => !latest || (run.ordinal ?? 0) > (latest.ordinal ?? 0) ? run : latest, undefined)
}

export function contextDisplay(run?: RunSummary): { label: string; detail: string; fill: number | null } {
  const usage = run?.contextUsage
  if (!usage) return { label: '上下文待估算', detail: '尚未获得最近一次模型请求的估算。', fill: null }
  const count = usage.inputTokens.toLocaleString('en-US')
  const capacity = usage.contextWindowTokens
  const percentage = capacity ? usage.inputTokens / capacity * 100 : null
  const percentText = percentage !== null && percentage > 0 && percentage < 1 ? '<1' : String(Math.round(percentage ?? 0))
  return {
    label: percentage === null ? `上下文 ≈ ${count} tokens` : `上下文 ≈ ${percentText}%`,
    detail: `约 ${count}${capacity ? ` / ${capacity.toLocaleString('en-US')}` : ''} tokens · ${run?.model ?? run?.provider ?? '原请求模型'}。根据最近一次模型请求估算，包含指令、工具和历史消息。`,
    fill: percentage === null ? null : Math.min(100, Math.max(0, percentage)),
  }
}
