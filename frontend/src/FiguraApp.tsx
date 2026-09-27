import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { createFiguraClient } from './api/figura/client'
import { createFiguraWorkspaceApi } from './api/figura/workspace'
import type { FiguraHealth, FiguraProviderId } from './api/figura/types'
import { validateImageFile } from './attachments'
import { toUserMessage } from './domain/errors'
import { createRunController, type RunController } from './domain/run/controller'
import { mergeEvents, type RunTimeline } from './domain/run/timeline'
import type { Attachment, ConversationItem, Provider, RunState, Session, SessionData } from './types/protocol'
import { AttachmentPanel, ConversationPanel, SessionSidebar } from './components/workspace'
import { CreateSessionDialog } from './components/dialogs'
import type { PendingAttachment } from './components/types'

const providers: FiguraProviderId[] = ['qwen', 'deepseek', 'mimo']
const providerLabels: Record<FiguraProviderId, string> = {
  qwen: 'Qwen（qwen3.8-flash）',
  deepseek: 'DeepSeek（deepseek-flash）',
  mimo: '小米 MiMo（mimo-v2.6-flash）',
}

function idempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `figura-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function FiguraApp() {
  const client = useMemo(() => createFiguraClient(), [])
  const api = useMemo(() => createFiguraWorkspaceApi(client), [client])
  const [health, setHealth] = useState<FiguraHealth | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [data, setData] = useState<SessionData | null>(null)
  const [timelines, setTimelines] = useState<RunTimeline[]>([])
  const [pendingUser, setPendingUser] = useState<ConversationItem | null>(null)
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [provider, setProvider] = useState<FiguraProviderId>('qwen')
  const [runState, setRunState] = useState<RunState>('idle')
  const [activeRunId, setActiveRunId] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingSession, setLoadingSession] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)
  const [newSessionName, setNewSessionName] = useState('')
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set())
  const activeIdRef = useRef(activeId)
  const activeRunRef = useRef<{ sessionId: string; runId: string; lastSequence: number } | null>(null)
  const controllerRef = useRef<RunController | null>(null)

  useEffect(() => { activeIdRef.current = activeId }, [activeId])

  useEffect(() => {
    let current = true
    void Promise.all([api.health.get(), api.sessions.list()]).then(([nextHealth, nextSessions]) => {
      if (!current) return
      setHealth(nextHealth)
      setSessions(nextSessions)
      setActiveId(nextSessions[0]?.id ?? '')
      if (nextSessions.length === 0) setLoadingSession(false)
    }).catch((reason) => {
      if (current) {
        setError(toUserMessage(reason))
        setLoadingSession(false)
      }
    })
    return () => { current = false }
  }, [api])

  useEffect(() => () => {
    controllerRef.current?.close()
    controllerRef.current = null
  }, [])

  const clearPending = () => {
    pending.forEach((item) => URL.revokeObjectURL(item.previewUrl))
    setPending([])
  }

  const trackRun = (sessionId: string, runId: string, afterSequence: number) => {
    controllerRef.current?.close()
    const controller = createRunController({
      client: {
        getRunHistory: (id, targetRunId, after) => api.runs.history(id, targetRunId, after),
        subscribeRun: (id, targetRunId, callbacks, after) => api.runs.subscribe(id, targetRunId, callbacks, after),
      },
      sessionId,
      runId,
      callbacks: {
        isCurrent: () => activeIdRef.current === sessionId && activeRunRef.current?.runId === runId,
        onEvent(event) {
          if (activeRunRef.current?.runId === runId) {
            activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, event.sequence)
          }
          setTimelines((items) => items.map((item) => item.summary.runId === runId ? {
            ...item,
            events: mergeEvents(item.events, [event]),
            summary: { ...item.summary, eventCount: Math.max(item.summary.eventCount, event.sequence), updatedAt: event.timestamp },
          } : item))
        },
        onHistory(history) {
          setTimelines((items) => items.map((item) => item.summary.runId === runId ? {
            ...item,
            summary: history.run,
            events: mergeEvents(item.events, history.events),
            historyGap: item.historyGap || history.historyGap,
          } : item))
          const cursor = Math.max(...history.events.map((event) => event.sequence), 0)
          if (activeRunRef.current?.runId === runId) {
            activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, cursor)
          }
        },
        onState(state) { setRunState(state) },
        async onTerminal(history) {
          setPendingUser(null)
          setLoading(false)
          setActiveRunId('')
          activeRunRef.current = null
          try {
            const [updated, nextSessions] = await Promise.all([
              api.sessions.get(sessionId),
              api.sessions.list(),
            ])
            if (activeIdRef.current === sessionId) {
              setData(updated)
              setSessions(nextSessions)
            }
          } catch {
            // The durable history already contains the terminal outcome.
          }
          if (history.run.status === 'failed') {
            setError((current) => current || history.run.terminalMessage || 'Figura Run 执行失败。')
          }
        },
        onUnavailable(reason) {
          setRunState('unavailable')
          setLoading(false)
          setError(toUserMessage(reason))
        },
      },
    })
    controllerRef.current = controller
    controller.start(afterSequence)
  }

  useEffect(() => {
    if (!activeId) {
      setData(null)
      setTimelines([])
      setLoadingSession(false)
      return
    }
    let current = true
    setData(null)
    setTimelines([])
    setLoadingSession(true)
    void api.sessions.get(activeId).then(async (value) => {
      if (!current || activeIdRef.current !== activeId) return
      setData(value)
      setSelectedIds([])
      const histories = await Promise.all(value.runs.map(async (summary) => {
        try {
          const history = await api.runs.history(activeId, summary.runId)
          return { summary: history.run, events: history.events, historyGap: history.historyGap }
        } catch {
          return { summary, events: [], historyGap: true }
        }
      }))
      if (!current || activeIdRef.current !== activeId) return
      setTimelines(histories)
      const running = histories.find((item) => item.summary.status === 'running')
      if (!running) {
        activeRunRef.current = null
        setActiveRunId('')
        setRunState('idle')
        setLoading(false)
        return
      }
      const runId = running.summary.runId
      const cursor = Math.max(...running.events.map((event) => event.sequence), 0)
      activeRunRef.current = { sessionId: activeId, runId, lastSequence: cursor }
      setActiveRunId(runId)
      setRunState('running')
      if (running.summary.executionState === 'needs_reconciliation') {
        setLoading(false)
        controllerRef.current?.close()
        controllerRef.current = null
      } else {
        setLoading(true)
        trackRun(activeId, runId, cursor)
      }
    }).catch((reason) => {
      if (current) setError(toUserMessage(reason))
    }).finally(() => {
      if (current) setLoadingSession(false)
    })
    return () => { current = false }
  }, [activeId, api])

  useEffect(() => {
    if (!activeId) return
    const saved = window.localStorage.getItem(`figura.provider.${activeId}`)
    if (saved && providers.includes(saved as FiguraProviderId)) {
      setProvider(saved as FiguraProviderId)
      return
    }
    const latest = [...(data?.runs ?? [])].reverse().find((run) => run.provider)
    if (latest?.provider && providers.includes(latest.provider as FiguraProviderId)) {
      setProvider(latest.provider as FiguraProviderId)
    } else {
      const available = health?.providers.find((item) => item.available)?.providerId
      if (available) setProvider(available)
    }
  }, [activeId, data, health])

  const selectSession = (sessionId: string) => {
    controllerRef.current?.close()
    controllerRef.current = null
    activeRunRef.current = null
    activeIdRef.current = sessionId
    setActiveRunId('')
    clearPending()
    setSelectedIds([])
    setPendingUser(null)
    setTimelines([])
    setExpandedRuns(new Set())
    setRunState('idle')
    setLoading(false)
    setError(null)
    setAttachmentError(null)
    setActiveId(sessionId)
  }

  const openCreateSession = () => {
    setNewSessionName('')
    setError(null)
    setCreatingSession(true)
  }

  const confirmCreateSession = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const name = newSessionName.trim()
    if (!name) return
    setError(null)
    try {
      const created = await api.sessions.create(name)
      const nextSessions = await api.sessions.list()
      setSessions(nextSessions)
      setCreatingSession(false)
      selectSession(created.id)
    } catch (reason) {
      setError(toUserMessage(reason))
    }
  }

  const uploadPending = async (target: PendingAttachment) => {
    const sessionId = activeIdRef.current
    if (!sessionId) return
    setPending((items) => items.map((item) => item.key === target.key ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const uploaded = await api.attachments.upload(sessionId, target.file)
      if (activeIdRef.current !== sessionId) {
        URL.revokeObjectURL(target.previewUrl)
        return
      }
      URL.revokeObjectURL(target.previewUrl)
      setData((current) => current ? {
        ...current,
        attachments: [...current.attachments.filter((item) => item.id !== uploaded.id), uploaded],
      } : current)
      setSelectedIds((ids) => ids.includes(uploaded.id) ? ids : [...ids, uploaded.id])
      setPending((items) => items.filter((item) => item.key !== target.key))
      setAttachmentError(null)
    } catch (reason) {
      setPending((items) => items.map((item) => item.key === target.key ? { ...item, status: 'error', error: toUserMessage(reason) } : item))
      setAttachmentError(toUserMessage(reason))
    }
  }

  const addFiles = (files: File[]) => {
    if (!activeIdRef.current || activeRunId) return
    const accepted: PendingAttachment[] = []
    for (const file of files) {
      const validationError = validateImageFile(file)
      if (validationError) {
        setAttachmentError(validationError)
        continue
      }
      accepted.push({ key: randomId(), file, previewUrl: URL.createObjectURL(file), status: 'uploading' })
    }
    if (accepted.length) {
      setPending((items) => [...items, ...accepted])
      accepted.forEach((item) => void uploadPending(item))
    }
  }

  const removePending = (key: string) => {
    const item = pending.find((candidate) => candidate.key === key)
    if (item) URL.revokeObjectURL(item.previewUrl)
    setPending((items) => items.filter((candidate) => candidate.key !== key))
  }

  const toggleAttachment = (attachmentId: string) => {
    setSelectedIds((ids) => ids.includes(attachmentId) ? ids.filter((id) => id !== attachmentId) : [...ids, attachmentId])
  }

  const referencedAttachmentIds = new Set(
    (data?.messages ?? []).flatMap((message) => message.kind === 'user' ? message.attachmentIds ?? [] : []),
  )

  const removeAttachment = async (attachment: Attachment) => {
    if (!activeId || referencedAttachmentIds.has(attachment.id)) return
    try {
      await api.attachments.remove(activeId, attachment.id)
      setData((current) => current ? { ...current, attachments: current.attachments.filter((item) => item.id !== attachment.id) } : current)
      setSelectedIds((ids) => ids.filter((id) => id !== attachment.id))
      setAttachmentError(null)
    } catch (reason) {
      setAttachmentError(toUserMessage(reason))
    }
  }

  const submit = async (text: string, attachmentIds: string[]): Promise<boolean> => {
    if (!activeId || activeRunId || !text.trim()) return false
    const selectedProvider = health?.providers.find((item) => item.providerId === provider)
    if (!selectedProvider?.available) {
      setError(`${providerLabels[provider]}当前不可用，请检查本地 Provider 配置。`)
      return false
    }
    const sessionId = activeId
    const key = idempotencyKey()
    setLoading(true)
    setRunState('connecting')
    setError(null)
    try {
      let handle
      try {
        handle = await api.runs.start(sessionId, text, [...attachmentIds], provider, key)
      } catch (firstError) {
        try {
          handle = await api.runs.start(sessionId, text, [...attachmentIds], provider, key)
        } catch {
          throw firstError
        }
      }
      if (activeIdRef.current !== sessionId) return true
      const summary = {
        runId: handle.runId,
        sessionId,
        status: handle.status,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        eventCount: 0,
        provider: handle.provider,
        model: handle.model,
        terminalCode: handle.terminalCode,
        terminalMessage: handle.terminalMessage,
        executionState: 'active' as const,
      }
      activeRunRef.current = { sessionId, runId: handle.runId, lastSequence: 0 }
      setActiveRunId(handle.runId)
      setSelectedIds([])
      setPendingUser({
        id: `${handle.runId}:user`,
        kind: 'user',
        text,
        timestamp: new Date().toISOString(),
        ...(attachmentIds.length ? { attachmentIds: [...attachmentIds] } : {}),
      })
      setTimelines((items) => items.some((item) => item.summary.runId === handle.runId) ? items : [
        ...items,
        { summary, events: [], historyGap: false },
      ])
      setRunState('running')
      setLoading(true)
      window.localStorage.setItem(`figura.provider.${sessionId}`, provider)
      trackRun(sessionId, handle.runId, 0)
      return true
    } catch (reason) {
      setRunState('unavailable')
      setLoading(false)
      setError(toUserMessage(reason))
      return false
    }
  }

  const changeProvider = (value: string) => {
    if (!providers.includes(value as FiguraProviderId)) return
    const next = value as FiguraProviderId
    setProvider(next)
    if (activeId) window.localStorage.setItem(`figura.provider.${activeId}`, next)
  }

  const providerOptions = providers.map((providerId) => {
    const availability = health?.providers.find((item) => item.providerId === providerId)
    return {
      id: providerId,
      label: providerLabels[providerId],
      status: !availability ? 'unknown' as const : availability.available ? 'ready' as const : 'unavailable' as const,
    }
  })

  const chooseRun = (runId: string) => setExpandedRuns((current) => {
    const next = new Set(current)
    if (next.has(runId)) next.delete(runId)
    else next.add(runId)
    return next
  })

  return <>
    <div className="app-shell">
      <SessionSidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={selectSession}
        onCreate={openCreateSession}
        mode="figura"
        runtimeStatus={null}
        health={null}
        showEvaluations={false}
        showSessionDeletion={false}
      />
      <ConversationPanel
        data={data}
        timelines={timelines}
        pendingUser={pendingUser}
        runState={runState}
        selectedAttachmentIds={selectedIds}
        activeSourceIds={[]}
        provider="qwen"
        providerValue={provider}
        providerOptions={providerOptions}
        health={null}
        mode="figura"
        onProviderChange={() => undefined}
        onProviderValueChange={changeProvider}
        onSubmit={submit}
        hideRunActions
        submissionBlocked={Boolean(activeRunId)}
        loading={loading}
        loadingSession={loadingSession}
        error={error}
        onToggleRun={chooseRun}
        expandedRuns={expandedRuns}
      />
      <AttachmentPanel
        attachments={data?.attachments ?? []}
        pending={pending}
        selectedIds={selectedIds}
        activeSourceIds={[]}
        error={attachmentError}
        onAdd={addFiles}
        onToggle={toggleAttachment}
        onRemovePending={removePending}
        onRetryPending={(item) => void uploadPending(item)}
        onRemove={(attachment) => void removeAttachment(attachment)}
        canRemove={(attachment) => !referencedAttachmentIds.has(attachment.id)}
      />
    </div>
    {creatingSession && <CreateSessionDialog
      name={newSessionName}
      onNameChange={setNewSessionName}
      onCancel={() => setCreatingSession(false)}
      onSubmit={(event) => void confirmCreateSession(event)}
    />}
  </>
}
