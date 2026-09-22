import type { RunEventCallbacks, RunSubscription } from '../client'
import { measurementRepairEventKinds } from '../../types/protocol'
import { mapRunEvent } from './mappers'
import { GatewayClientError } from './transport'
import type { GatewayRunEvent } from './types'

const terminalEventKinds = new Set(['final_answer', 'run_failed', 'run_interrupted'])
const streamEventKinds = [
  'run_started', 'resume_started', 'model_started', 'model_completed', 'tool_call', 'tool_result', 'visual_observation', 'generated_chart',
  'chart_review_started', 'chart_review_completed', 'generated_chart_rejected', 'chart_review_required', 'generated_chart_published',
  ...measurementRepairEventKinds, 'reasoning', 'budget_exhausted', 'final_answer', 'run_failed', 'run_interrupted', 'recovery_blocked',
  'operation_completed', 'history_gap',
]

export function subscribeRun(baseUrl: string, sessionId: string, runId: string, callbacks: RunEventCallbacks, afterSequence = 0): RunSubscription {
  const source = new EventSource(`${baseUrl}/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/events?after=${Math.max(0, afterSequence)}`)
  let closed = false
  let connectionErrors = 0
  const receive = (raw: Event) => {
    if (closed) return
    try {
      const event = mapRunEvent(JSON.parse((raw as MessageEvent<string>).data) as GatewayRunEvent, sessionId)
      connectionErrors = 0
      callbacks.onEvent(event)
      if (terminalEventKinds.has(event.kind)) {
        closed = true
        source.close()
        callbacks.onComplete()
      }
    } catch {
      closed = true
      source.close()
      callbacks.onError(new GatewayClientError('invalid_gateway_event', 'Gateway 返回了无效执行事件', 502))
    }
  }
  streamEventKinds.forEach((kind) => source.addEventListener(kind, receive))
  source.onerror = () => {
    if (closed) return
    connectionErrors += 1
    if (source.readyState === EventSource.CLOSED || connectionErrors >= 3) {
      closed = true
      source.close()
      callbacks.onError(new GatewayClientError('gateway_stream_unavailable', '执行事件流已断开', 0))
    }
  }
  return { close() { closed = true; source.close() } }
}
