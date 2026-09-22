import type { ChartAgentClient, RunSubscription } from '../../api/client'
import type { AgentRunEvent, RunHistory, RunState } from '../../types/protocol'

export type RunControllerCallbacks = {
  isCurrent: () => boolean
  onEvent: (event: AgentRunEvent) => void
  onHistory: (history: RunHistory) => void
  onState: (state: RunState) => void
  onTerminal: (history: RunHistory) => void | Promise<void>
  onUnavailable: (error: Error) => void
}

export type RunControllerOptions = {
  client: ChartAgentClient
  sessionId: string
  runId: string
  callbacks: RunControllerCallbacks
  maxReconnectAttempts?: number
}

export type RunController = {
  start(afterSequence?: number): void
  reconcile(afterSequence?: number): Promise<boolean>
  close(): void
}

const defaultMaxReconnectAttempts = 5

function terminalStatus(status: RunHistory['run']['status']): RunState | null {
  if (status === 'interrupted') return 'interrupted'
  if (status === 'failed') return 'failed'
  if (status === 'completed') return 'completed'
  return null
}

export function createRunController(options: RunControllerOptions): RunController {
  const maxReconnectAttempts = options.maxReconnectAttempts ?? defaultMaxReconnectAttempts
  let closed = false
  let cursor = 0
  let reconnectAttempts = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let subscription: RunSubscription | null = null
  let connectionGeneration = 0

  const isCurrent = () => !closed && options.callbacks.isCurrent()

  const clearTimer = () => {
    if (reconnectTimer !== undefined) clearTimeout(reconnectTimer)
    reconnectTimer = undefined
  }

  const closeSubscription = () => {
    subscription?.close()
    subscription = null
  }

  const close = () => {
    if (closed) return
    closed = true
    connectionGeneration += 1
    clearTimer()
    closeSubscription()
  }

  const applyHistory = (history: RunHistory) => {
    if (!isCurrent()) return
    const latest = Math.max(...history.events.map((event) => event.sequence), 0)
    cursor = Math.max(cursor, latest)
    options.callbacks.onHistory(history)
  }

  const finishHistory = (history: RunHistory): boolean => {
    applyHistory(history)
    const state = terminalStatus(history.run.status)
    if (!state || !isCurrent()) return false
    options.callbacks.onState(state)
    void options.callbacks.onTerminal(history)
    close()
    return true
  }

  const scheduleReconnect = (reason: Error) => {
    if (!isCurrent()) return
    if (reconnectAttempts >= maxReconnectAttempts) {
      options.callbacks.onUnavailable(reason)
      close()
      return
    }
    reconnectAttempts += 1
    options.callbacks.onState('reconnecting')
    const backoff = Math.min(8000, 400 * (2 ** (reconnectAttempts - 1))) + Math.floor(Math.random() * 200)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined
      connect(cursor)
    }, backoff)
  }

  const reconcile = async (afterSequence = cursor): Promise<boolean> => {
    if (!isCurrent()) return false
    try {
      const history = await options.client.getRunHistory(options.sessionId, options.runId, afterSequence)
      return finishHistory(history)
    } catch {
      return false
    }
  }

  const handleDisconnect = async (reason: Error, generation: number, afterSequence: number) => {
    if (!isCurrent() || generation !== connectionGeneration) return
    subscription = null
    const finished = await reconcile(Math.max(cursor, afterSequence))
    if (finished || !isCurrent() || generation !== connectionGeneration) return
    scheduleReconnect(reason)
  }

  const connect = (afterSequence = cursor) => {
    if (!isCurrent()) return
    clearTimer()
    closeSubscription()
    cursor = Math.max(cursor, afterSequence)
    const generation = ++connectionGeneration
    subscription = options.client.subscribeRun(options.sessionId, options.runId, {
      onEvent(event) {
        if (!isCurrent() || generation !== connectionGeneration) return
        cursor = Math.max(cursor, event.sequence)
        options.callbacks.onEvent(event)
      },
      onError(reason) {
        void handleDisconnect(reason, generation, afterSequence)
      },
      onComplete() {
        if (!isCurrent() || generation !== connectionGeneration) return
        subscription = null
        void options.client.getRunHistory(options.sessionId, options.runId, cursor).then((history) => {
          if (!isCurrent() || generation !== connectionGeneration) return
          if (!finishHistory(history)) scheduleReconnect(new Error('执行事件流已结束，但运行仍未进入终态'))
        }).catch((reason) => {
          scheduleReconnect(reason instanceof Error ? reason : new Error('执行历史暂时不可用'))
        })
      },
    }, afterSequence)
  }

  return {
    start(afterSequence = 0) {
      if (closed) return
      cursor = Math.max(0, afterSequence)
      reconnectAttempts = 0
      connect(cursor)
    },
    reconcile,
    close,
  }
}

