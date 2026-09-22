import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { GatewayClientError, configureGatewayBaseUrl, currentGatewayBaseUrl, gatewayClient } from './api/gatewayClient'
import type { ChartAgentClient } from './api/client'
import { createWorkspaceApi } from './api/workspace'
import { mockClient } from './api/mockClient'
import { validateImageFile } from './attachments'
import { getGatewayRuntimeStatus, type GatewayRuntimeStatus } from './runtime'
import { createGatewayPreviewLoader } from './previewResources'
import { currentTime, providerLabels, providerStatus } from './domain/display'
import { toUserMessage } from './domain/errors'
import { createRunController, type RunController } from './domain/run/controller'
import { mergeEvents, type RunTimeline } from './domain/run/timeline'
import type { Attachment, ConversationItem, EvaluationCaseData, EvaluationDetail, EvaluationHistory, EvaluationHistoryDetails, EvaluationSummary, GatewayHealth, Provider, RunState, RunSummary, Session, SessionData } from './types/protocol'
import { EvaluationPanel } from './components/evaluation'
import { InteractivePreview } from './components/preview'
import { ConversationPanel, AttachmentPanel, SessionSidebar } from './components/workspace'
import { ConfirmDeleteDialog, CreateSessionDialog, type ConfirmAction } from './components/dialogs'
import type { PendingAttachment, PreviewDescriptor } from './components/types'
import './styles/global.css'
import './styles/error.css'

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `figura-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export default function App() {
  const mode = import.meta.env.VITE_CHARTAGENT_MODE === 'gateway' ? 'gateway' : 'mock'
  const client: ChartAgentClient = useMemo(() => mode === 'gateway' ? gatewayClient : mockClient, [mode])
  const workspaceApi = useMemo(() => createWorkspaceApi(client), [client])
  const [workspace, setWorkspace] = useState<'sessions' | 'evaluations'>('sessions')
  const [runtimeStatus, setRuntimeStatus] = useState<GatewayRuntimeStatus | null>(null)
  const [gatewayHealth, setGatewayHealth] = useState<GatewayHealth | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [data, setData] = useState<SessionData | null>(null)
  const [pending, setPending] = useState<PendingAttachment[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [activeSourceIds, setActiveSourceIds] = useState<string[]>([])
  const [timelines, setTimelines] = useState<RunTimeline[]>([])
  const [pendingUser, setPendingUser] = useState<ConversationItem | null>(null)
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set())
  const [runState, setRunState] = useState<RunState>('idle')
  const [loading, setLoading] = useState(false)
  const [loadingSession, setLoadingSession] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)
  const [newSessionName, setNewSessionName] = useState('')
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [gatewayUrl, setGatewayUrl] = useState(() => currentGatewayBaseUrl())
  const [gatewayReady, setGatewayReady] = useState(mode !== 'gateway')
  const [provider, setProvider] = useState<Provider>('openai')
  const [activePreview, setActivePreview] = useState<PreviewDescriptor | null>(null)
  const [evaluations, setEvaluations] = useState<EvaluationSummary[]>([])
  const [activeEvaluationId, setActiveEvaluationId] = useState('')
  const [evaluationDetail, setEvaluationDetail] = useState<EvaluationDetail | null>(null)
  const [evaluationCaseId, setEvaluationCaseId] = useState('')
  const [evaluationCase, setEvaluationCase] = useState<EvaluationCaseData | null>(null)
  const [evaluationHistory, setEvaluationHistory] = useState<EvaluationHistory | null>(null)
  const [evaluationHistoryDetails, setEvaluationHistoryDetails] = useState<EvaluationHistoryDetails | null>(null)
  const [evaluationLoading, setEvaluationLoading] = useState(false)
  const [evaluationCaseLoading, setEvaluationCaseLoading] = useState(false)
  const [evaluationHistoryLoading, setEvaluationHistoryLoading] = useState(false)
  const [evaluationHistoryDetailsLoading, setEvaluationHistoryDetailsLoading] = useState(false)
  const [evaluationHistoryDetailsError, setEvaluationHistoryDetailsError] = useState<string | null>(null)
  const [evaluationError, setEvaluationError] = useState<string | null>(null)
  const [evaluationStale, setEvaluationStale] = useState(false)
  const activeIdRef = useRef(activeId)
  const localPreviews = useRef(new Map<string, string>())
  const runControllerRef = useRef<RunController | null>(null)
  const activeRunRef = useRef<{ sessionId: string; runId: string; idempotencyKey: string; lastSequence: number; text: string; attachmentIds: string[]; provider: Provider } | null>(null)
  const runRequestsRef = useRef(new Map<string, { text: string; attachmentIds: string[] }>())
  const previewLoader = useMemo(
    () => mode === 'gateway' ? createGatewayPreviewLoader(gatewayUrl) : null,
    [mode, gatewayUrl],
  )

  useEffect(() => { activeIdRef.current = activeId }, [activeId])
  useEffect(() => { setActivePreview(null) }, [activeId])
  useEffect(() => {
    if (!activeId) return
    const stored = window.localStorage.getItem(`figura.provider.${activeId}`)
    if (stored === 'openai' || stored === 'qwen' || stored === 'deepseek') setProvider(stored)
    else if (data?.session.id === activeId && data.runs.length > 0) {
      const latest = [...data.runs].reverse().find((run) => run.provider)
      if (latest?.provider) setProvider(latest.provider)
      else if (gatewayHealth?.agent?.provider === 'qwen') setProvider('qwen')
      else if (gatewayHealth?.agent?.provider === 'deepseek') setProvider('deepseek')
      else setProvider('openai')
    }
    else if (gatewayHealth?.agent?.provider === 'qwen') setProvider('qwen')
    else if (gatewayHealth?.agent?.provider === 'deepseek') setProvider('deepseek')
    else setProvider('openai')
  }, [activeId, data, gatewayHealth])
  useEffect(() => () => { runControllerRef.current?.close(); runControllerRef.current = null; localPreviews.current.forEach((url) => URL.revokeObjectURL(url)); localPreviews.current.clear() }, [])
  useEffect(() => {
    if (mode !== 'gateway') return
    let current = true
    void getGatewayRuntimeStatus().then((status) => {
      if (!current) return null
      const effectiveUrl = configureGatewayBaseUrl(status?.url || currentGatewayBaseUrl())
      setGatewayUrl(effectiveUrl)
      setRuntimeStatus(status)
      setGatewayReady(true)
      return workspaceApi.health.get()
    }).then((health) => {
      if (!current) return
      if (!health) return
      setGatewayHealth(health)
      if (health.agent?.status === 'unavailable') {
        setError(toUserMessage(new GatewayClientError('agent_unavailable', 'Agent service is unavailable', 503, health.agent.reason)))
      }
    }).catch((reason) => { if (current) setError(toUserMessage(reason)) })
    return () => { current = false }
  }, [mode, workspaceApi])

  const withLocalPreviews = (value: SessionData): SessionData => ({ ...value, attachments: value.attachments.map((attachment) => ({ ...attachment, previewUrl: attachment.previewUrl || localPreviews.current.get(attachment.id) || '' })) })

  const startRunTracking = (sessionId: string, runId: string, afterSequence = 0) => {
    runControllerRef.current?.close()
    const controller = createRunController({
      client,
      sessionId,
      runId,
      callbacks: {
        isCurrent: () => activeIdRef.current === sessionId && activeRunRef.current?.runId === runId,
        onEvent(event) {
          if (event.kind === 'history_gap') {
            setRunState('history-gap')
            setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, historyGap: true } : item))
            return
          }
          if (activeRunRef.current?.runId === runId) activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, event.sequence)
          if (event.kind === 'run_failed') {
            setRunState('failed')
            setLoading(false)
            setError(toUserMessage(new GatewayClientError(String(event.payload.code || 'agent_failed'), String(event.payload.message || 'Agent 执行失败'), 502, typeof event.payload.reason === 'string' ? event.payload.reason : undefined)))
          } else if (event.kind === 'run_interrupted') {
            setRunState('interrupted')
            setLoading(false)
          } else if (event.kind !== 'run_started') setRunState('running')
          setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, events: mergeEvents(item.events, [event]), summary: { ...item.summary, eventCount: Math.max(item.summary.eventCount, event.sequence), updatedAt: event.timestamp } } : item))
        },
        onHistory(history) {
          setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, summary: history.run, events: mergeEvents(item.events, history.events), historyGap: item.historyGap || history.historyGap } : item))
          const latest = Math.max(...history.events.map((event) => event.sequence), 0)
          if (activeRunRef.current?.runId === runId) activeRunRef.current.lastSequence = Math.max(activeRunRef.current.lastSequence, latest)
        },
        onState(state) {
          setRunState(state)
        },
        async onTerminal(history) {
          setPendingUser(null)
          setLoading(false)
          activeRunRef.current = null
          try {
            const updated = await workspaceApi.sessions.get(sessionId)
            if (activeIdRef.current === sessionId) {
              setData(withLocalPreviews(updated))
              setSessions((items) => items.map((item) => item.id === updated.session.id ? updated.session : item))
            }
          } catch { /* The durable run history remains visible if refresh fails. */ }
          if (history.run.status === 'failed') setError((current) => current || toUserMessage(new Error(history.run.terminalMessage || 'Agent 执行失败')))
        },
        onUnavailable(reason) {
          setRunState('unavailable')
          setLoading(false)
          setError(toUserMessage(reason))
        },
      },
    })
    runControllerRef.current = controller
    controller.start(afterSequence)
  }

  useEffect(() => {
    if (!gatewayReady) return
    setLoadingSession(true)
    workspaceApi.sessions.list().then((items) => { setSessions(items); setActiveId(items[0]?.id ?? '') }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false))
  }, [workspaceApi, gatewayReady])

  const loadEvaluationCatalog = async (preserve = true) => {
    try {
      const items = await workspaceApi.evaluations.list()
      setEvaluations(items)
      setEvaluationStale(false)
      setEvaluationError(null)
      setActiveEvaluationId((current) => items.some((item) => item.evaluationId === current) ? current : items[0]?.evaluationId || '')
    } catch (reason) {
      setEvaluationStale(preserve)
      setEvaluationError(toUserMessage(reason))
    }
  }

  useEffect(() => {
    if (!gatewayReady) return
    void loadEvaluationCatalog()
  }, [workspaceApi, gatewayReady])

  useEffect(() => {
    if (!gatewayReady || workspace !== 'evaluations' || !activeEvaluationId) {
      setEvaluationDetail(null)
      setEvaluationCase(null)
      setEvaluationHistory(null)
      setEvaluationHistoryDetails(null)
      setEvaluationHistoryDetailsError(null)
      return
    }
    let current = true
    setEvaluationLoading(true)
    setEvaluationError(null)
    void workspaceApi.evaluations.get(activeEvaluationId).then((detail) => {
      if (!current) return
      setEvaluationDetail(detail)
      setEvaluationCaseId((caseId) => detail.cases.some((item) => item.caseId === caseId) ? caseId : detail.cases[0]?.caseId || '')
    }).catch((reason) => { if (current) setEvaluationError(toUserMessage(reason)) }).finally(() => { if (current) setEvaluationLoading(false) })
    return () => { current = false }
  }, [activeEvaluationId, workspaceApi, gatewayReady, workspace])

  useEffect(() => {
    if (!gatewayReady || workspace !== 'evaluations' || !activeEvaluationId || !evaluationCaseId) {
      setEvaluationCase(null)
      setEvaluationHistory(null)
      setEvaluationHistoryDetails(null)
      setEvaluationHistoryDetailsError(null)
      return
    }
    let current = true
    setEvaluationCaseLoading(true)
    setEvaluationHistoryLoading(true)
    setEvaluationHistoryDetails(null)
    setEvaluationHistoryDetailsError(null)
    setEvaluationError(null)
    void workspaceApi.evaluations.getCase(activeEvaluationId, evaluationCaseId).then((value) => {
      if (current) setEvaluationCase(value)
    }).catch((reason) => { if (current) setEvaluationError(toUserMessage(reason)) }).finally(() => { if (current) setEvaluationCaseLoading(false) })
    void workspaceApi.evaluations.history(activeEvaluationId, evaluationCaseId).then((value) => {
      if (current) setEvaluationHistory(value)
    }).catch(() => {
      if (current) setEvaluationHistory(null)
    }).finally(() => { if (current) setEvaluationHistoryLoading(false) })
    return () => { current = false }
  }, [activeEvaluationId, workspaceApi, evaluationCaseId, gatewayReady, workspace])

  const loadEvaluationHistoryDetails = async () => {
    if (!activeEvaluationId || !evaluationCaseId || workspace !== 'evaluations') return
    setEvaluationHistoryDetailsLoading(true)
    setEvaluationHistoryDetailsError(null)
    try {
      const details = await workspaceApi.evaluations.historyDetails(activeEvaluationId, evaluationCaseId)
      setEvaluationHistoryDetails(details)
    } catch (reason) {
      setEvaluationHistoryDetailsError(toUserMessage(reason))
    } finally {
      setEvaluationHistoryDetailsLoading(false)
    }
  }

  const refreshEvaluation = async () => {
    await loadEvaluationCatalog()
    if (!activeEvaluationId || workspace !== 'evaluations') return
    try {
      const detail = await workspaceApi.evaluations.get(activeEvaluationId)
      setEvaluationDetail(detail)
      const caseId = evaluationCaseId || detail.cases[0]?.caseId || ''
      if (caseId) setEvaluationCaseId(caseId)
      setEvaluationStale(false)
    } catch (reason) {
      setEvaluationStale(true)
      setEvaluationError(toUserMessage(reason))
    }
  }

  const selectedEvaluation = evaluations.find((item) => item.evaluationId === activeEvaluationId)
  useEffect(() => {
    if (workspace !== 'evaluations' || !activeEvaluationId || selectedEvaluation?.status !== 'running') return
    const timer = window.setInterval(() => {
      void refreshEvaluation()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [activeEvaluationId, selectedEvaluation?.status, workspace])
  useEffect(() => {
    if (!activeId) { setData(null); setTimelines([]); return }
    setData(null)
    setTimelines([])
    setLoadingSession(true)
    void workspaceApi.sessions.get(activeId).then(async (value) => {
      if (activeIdRef.current !== activeId) return
      setData(withLocalPreviews(value))
      setActiveSourceIds((value.activeSourceAttachmentIds || []).filter((id) => value.attachments.some((attachment) => attachment.id === id)))
      const hydrated = await Promise.all(value.runs.map(async (summary) => {
        try {
          const history = await workspaceApi.runs.history(activeId, summary.runId)
          return { summary: history.run, events: history.events, historyGap: history.historyGap }
        } catch {
          return { summary, events: [], historyGap: true }
        }
      }))
      if (activeIdRef.current === activeId) {
        setTimelines(hydrated)
        const current = hydrated.find((item) => item.summary.status === 'running')
        if (current) {
          const runId = current.summary.runId
          const cursor = Math.max(...current.events.map((event) => event.sequence), 0)
          setRunState('running')
          setLoading(true)
          activeRunRef.current = { sessionId: activeId, runId, idempotencyKey: '', lastSequence: cursor, text: '', attachmentIds: [], provider: current.summary.provider || 'openai' }
          startRunTracking(activeId, runId, cursor)
        } else {
          activeRunRef.current = null
          setRunState('idle')
          setLoading(false)
        }
      }
    }).catch((reason) => setError(toUserMessage(reason))).finally(() => setLoadingSession(false))
  }, [activeId, workspaceApi, gatewayReady])

  const clearPending = () => { pending.forEach((item) => URL.revokeObjectURL(item.previewUrl)); setPending([]) }
  const selectSession = (id: string) => { runControllerRef.current?.close(); runControllerRef.current = null; activeRunRef.current = null; runRequestsRef.current.clear(); clearPending(); setSelectedIds([]); setActiveSourceIds([]); setPendingUser(null); setTimelines([]); setExpandedRuns(new Set()); setRunState('idle'); setAttachmentError(null); setError(null); setActiveId(id) }
  const create = async () => { setNewSessionName(''); setCreatingSession(true) }
  const confirmCreate = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const name = newSessionName.trim(); if (!name) return; setError(null); try { runControllerRef.current?.close(); runControllerRef.current = null; clearPending(); setSelectedIds([]); setActiveSourceIds([]); setPendingUser(null); setTimelines([]); setRunState('idle'); const created = await workspaceApi.sessions.create(name); setSessions(await workspaceApi.sessions.list()); setActiveId(created.session.id); setCreatingSession(false) } catch (reason) { setError(toUserMessage(reason)) } }

  const forgetLocalPreview = (attachmentId: string) => {
    const url = localPreviews.current.get(attachmentId)
    if (url?.startsWith('blob:')) URL.revokeObjectURL(url)
    localPreviews.current.delete(attachmentId)
  }

  const requestDeleteSession = (id: string) => {
    const session = sessions.find((item) => item.id === id)
    if (session) setConfirmAction({ kind: 'session', session })
  }

  const requestDeleteAttachment = (attachment: Attachment) => setConfirmAction({ kind: 'attachment', attachment })

  const confirmDelete = async () => {
    const action = confirmAction
    if (!action || deleting) return
    setDeleting(true)
    setError(null)
    setAttachmentError(null)
    try {
      if (action.kind === 'session') {
        const deletedIndex = sessions.findIndex((item) => item.id === action.session.id)
        await workspaceApi.sessions.remove(action.session.id)
        const remaining = sessions.filter((item) => item.id !== action.session.id)
        setSessions(remaining)
        if (activeIdRef.current === action.session.id) {
          runControllerRef.current?.close()
          runControllerRef.current = null
          data?.attachments.forEach((attachment) => forgetLocalPreview(attachment.id))
          clearPending()
          setSelectedIds([])
          setPendingUser(null)
          setTimelines([])
          setExpandedRuns(new Set())
          setRunState('idle')
          setLoading(false)
          setData(null)
          const next = remaining[deletedIndex] || remaining[deletedIndex - 1]
          setActiveId(next?.id ?? '')
        }
      } else {
        const sessionId = activeIdRef.current
        await workspaceApi.attachments.remove(sessionId, action.attachment.id)
        forgetLocalPreview(action.attachment.id)
        setSelectedIds((ids) => ids.filter((id) => id !== action.attachment.id))
        setActiveSourceIds((ids) => ids.filter((id) => id !== action.attachment.id))
        setData((current) => current ? { ...current, attachments: current.attachments.filter((item) => item.id !== action.attachment.id) } : current)
      }
      setConfirmAction(null)
    } catch (reason) {
      const message = toUserMessage(reason)
      if (action.kind === 'attachment') setAttachmentError(message)
      else setError(message)
    } finally {
      setDeleting(false)
    }
  }

  const uploadPending = async (target: PendingAttachment) => {
    const sessionId = activeIdRef.current
    setPending((items) => items.map((item) => item.key === target.key ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const uploaded = await workspaceApi.attachments.upload(sessionId, target.file)
      if (activeIdRef.current !== sessionId) { URL.revokeObjectURL(target.previewUrl); return }
      const previewUrl = mode === 'mock' ? target.previewUrl : uploaded.previewUrl || ''
      if (mode === 'mock') localPreviews.current.set(uploaded.id, target.previewUrl)
      else URL.revokeObjectURL(target.previewUrl)
      setData((current) => current ? { ...current, attachments: [...current.attachments.filter((item) => item.id !== uploaded.id), { ...uploaded, previewUrl, previewAvailable: Boolean(previewUrl) }] } : current)
      setSelectedIds((ids) => ids.includes(uploaded.id) ? ids : [...ids, uploaded.id])
      setPending((items) => items.filter((item) => item.key !== target.key))
      setAttachmentError(null)
    } catch (reason) {
      const message = toUserMessage(reason)
      setPending((items) => items.map((item) => item.key === target.key ? { ...item, status: 'error', error: message } : item))
      setAttachmentError(message)
    }
  }

  const addFiles = (files: File[]) => {
    if (!activeIdRef.current) return
    const accepted: PendingAttachment[] = []
    for (const file of files) {
      const validationError = validateImageFile(file)
      if (validationError) { setAttachmentError(validationError); continue }
      const pendingItem: PendingAttachment = { key: `${Date.now()}-${accepted.length}-${file.name}`, file, previewUrl: URL.createObjectURL(file), status: 'uploading' }
      accepted.push(pendingItem)
    }
    if (accepted.length) { setPending((items) => [...items, ...accepted]); accepted.forEach((item) => void uploadPending(item)) }
  }

  const removePending = (key: string) => { const item = pending.find((candidate) => candidate.key === key); if (item) URL.revokeObjectURL(item.previewUrl); setPending((items) => items.filter((candidate) => candidate.key !== key)) }
  const toggleAttachment = (id: string) => setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id])

  const submit = async (text: string, attachmentIds: string[], retryOf?: string, resumeOf?: string): Promise<boolean> => {
    if (!activeId) return false
    const sessionId = activeId
    const effectiveAttachmentIds = attachmentIds.length > 0 ? [...attachmentIds] : [...activeSourceIds]
    runControllerRef.current?.close()
    runControllerRef.current = null
    setLoading(true)
    setRunState('connecting')
    setError(null)
    setSelectedIds([])
    const idempotencyKey = newIdempotencyKey()
    const startOptions = { idempotencyKey, ...(retryOf ? { retryOf } : {}) }
    try {
      const selectedStatus = providerStatus(gatewayHealth, provider, mode)
      if (selectedStatus !== 'ready') {
        setError(selectedStatus === 'unavailable'
          ? `${providerLabels[provider]}当前不可用，请切换来源或检查 Gateway 配置。`
          : '正在确认 Gateway 的模型来源状态，请稍后重试。')
        setRunState('unavailable')
        setLoading(false)
        return false
      }
      let handle
      try {
        handle = resumeOf
          ? await workspaceApi.runs.resume(sessionId, resumeOf, { idempotencyKey })
          : await workspaceApi.runs.start(sessionId, text, effectiveAttachmentIds, provider, startOptions)
      } catch (firstError) {
        // A lost acknowledgement can mean the Gateway accepted the run. One
        // keyed recovery request is safe and lets the Gateway return it.
        try {
          handle = resumeOf
            ? await workspaceApi.runs.resume(sessionId, resumeOf, { idempotencyKey })
            : await workspaceApi.runs.start(sessionId, text, effectiveAttachmentIds, provider, startOptions)
        } catch {
          throw firstError
        }
      }
      if (attachmentIds.length > 0) setActiveSourceIds([...attachmentIds])
      window.localStorage.setItem(`figura.provider.${sessionId}`, provider)
      if (activeIdRef.current !== sessionId) return false
      activeRunRef.current = { sessionId, runId: handle.runId, idempotencyKey, lastSequence: 0, text, attachmentIds: [...effectiveAttachmentIds], provider }
      runRequestsRef.current.set(handle.runId, { text, attachmentIds: [...effectiveAttachmentIds] })
      setPendingUser({ id: `${handle.runId}:user`, kind: 'user', text, timestamp: currentTime(), attachmentIds: effectiveAttachmentIds.length ? effectiveAttachmentIds : undefined })
      setRunState(handle.status === 'running' ? 'running' : handle.status === 'interrupted' ? 'interrupted' : handle.status === 'failed' ? 'failed' : 'completed')
      const startedAt = new Date().toISOString()
      setTimelines((current) => current.some((item) => item.summary.runId === handle.runId) ? current : [...current, { summary: { runId: handle.runId, sessionId, status: handle.status, createdAt: startedAt, updatedAt: startedAt, eventCount: 0, provider: handle.provider || provider, model: handle.model, retryOf: handle.retryOf, parentRunId: handle.parentRunId, rootRunId: handle.rootRunId, continuationKind: handle.continuationKind, recovery: handle.recovery }, events: [], historyGap: false }])
      startRunTracking(sessionId, handle.runId)
      return true
    } catch (reason) {
      setRunState('unavailable')
      setError(toUserMessage(reason))
      setLoading(false)
      return false
    }
  }

  const interruptRun = async (runId: string) => {
    const sessionId = activeIdRef.current
    if (!sessionId) return
    setRunState('cancel_requested')
    setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, summary: { ...item.summary, cancelRequested: true } } : item))
    try {
      const handle = await workspaceApi.runs.interrupt(sessionId, runId)
      setTimelines((items) => items.map((item) => item.summary.runId === runId ? { ...item, summary: { ...item.summary, status: handle.status, terminalCode: handle.terminalCode, terminalMessage: handle.terminalMessage, cancelRequested: true, updatedAt: new Date().toISOString() } } : item))
      if (handle.status === 'interrupted') { setRunState('interrupted'); setLoading(false) }
    } catch (reason) {
      setRunState('running')
      setError(toUserMessage(reason))
    }
  }

  const retryRun = async (runId: string) => {
    const timeline = timelines.find((item) => item.summary.runId === runId)
    if (!timeline) return
    const request = runRequestsRef.current.get(runId)
    const storedUser = data?.messages.find((item) => item.id === `${runId}:user`)
    const activeUser = pendingUser?.id === `${runId}:user` ? pendingUser : undefined
    const user = activeUser || storedUser || (request ? { id: `${runId}:user`, kind: 'user' as const, text: request.text, timestamp: currentTime(), attachmentIds: request.attachmentIds } : undefined)
    if (!user || user.kind !== 'user') {
      setError('这条运行缺少原始请求，暂时无法自动重试。')
      return
    }
    await submit(user.text, user.attachmentIds || [], runId)
  }

  const resumeRun = async (runId: string) => {
    const timeline = timelines.find((item) => item.summary.runId === runId)
    if (!timeline || timeline.summary.recovery?.status !== 'available') return
    const request = runRequestsRef.current.get(runId)
    const storedUser = data?.messages.find((item) => item.id === `${runId}:user`)
    const user = storedUser || (request ? { id: `${runId}:user`, kind: 'user' as const, text: request.text, timestamp: currentTime(), attachmentIds: request.attachmentIds } : undefined)
    if (!user || user.kind !== 'user') {
      setError('这条运行缺少原始请求，暂时无法继续执行。')
      return
    }
    await submit(user.text, user.attachmentIds || [], undefined, runId)
  }

  const toggleRun = (runId: string, status: RunSummary['status']) => setExpandedRuns((current) => { const next = new Set(current); if (status === 'running') { next.has(runId) ? next.delete(runId) : next.add(runId) } else { next.has(runId) ? next.delete(runId) : next.add(runId) } return next })
  const changeProvider = (next: Provider) => { setProvider(next); if (activeId) window.localStorage.setItem(`figura.provider.${activeId}`, next); if (loading) setError('当前运行不会切换来源，新选择将应用于下一次运行。') }
  const selectEvaluation = (id: string) => { setWorkspace('evaluations'); setActiveEvaluationId(id); setEvaluationCaseId(''); setActivePreview(null); setEvaluationError(null) }
  const changeWorkspace = (next: 'sessions' | 'evaluations') => {
    setWorkspace(next)
    setActivePreview(null)
    if (next === 'evaluations' && !activeEvaluationId && evaluations[0]) setActiveEvaluationId(evaluations[0].evaluationId)
  }
  return <>
    <div className="app-shell">
      <SessionSidebar sessions={sessions} activeId={activeId} onSelect={selectSession} onCreate={create} onDelete={requestDeleteSession} workspace={workspace} onWorkspaceChange={changeWorkspace} evaluations={evaluations} activeEvaluationId={activeEvaluationId} onSelectEvaluation={selectEvaluation} mode={mode} runtimeStatus={runtimeStatus} health={gatewayHealth} />
      {workspace === 'evaluations' ? <EvaluationPanel evaluations={evaluations} detail={evaluationDetail} caseData={evaluationCase} history={evaluationHistory} historyDetails={evaluationHistoryDetails} selectedEvaluationId={activeEvaluationId} selectedCaseId={evaluationCaseId} loading={evaluationLoading} caseLoading={evaluationCaseLoading} historyLoading={evaluationHistoryLoading} historyDetailsLoading={evaluationHistoryDetailsLoading} historyDetailsError={evaluationHistoryDetailsError} error={evaluationError} stale={evaluationStale} onRefresh={() => void refreshEvaluation()} onSelectCase={(id) => { setEvaluationCaseId(id); setEvaluationError(null) }} onLoadHistoryDetails={() => void loadEvaluationHistoryDetails()} previewLoader={previewLoader} onPreview={setActivePreview} /> : <>
        <ConversationPanel data={data} timelines={timelines} pendingUser={pendingUser} runState={runState} selectedAttachmentIds={selectedIds} activeSourceIds={activeSourceIds} provider={provider} health={gatewayHealth} mode={mode} onProviderChange={changeProvider} onSubmit={submit} onInterrupt={(runId) => void interruptRun(runId)} onRetry={(runId) => void retryRun(runId)} onResume={(runId) => void resumeRun(runId)} loading={loading} loadingSession={loadingSession} error={error} onToggleRun={toggleRun} expandedRuns={expandedRuns} previewLoader={previewLoader} onPreview={setActivePreview} />
        <AttachmentPanel attachments={data?.attachments ?? []} pending={pending} selectedIds={selectedIds} activeSourceIds={activeSourceIds} error={attachmentError} onAdd={addFiles} onToggle={toggleAttachment} onRemovePending={removePending} onRetryPending={(item) => void uploadPending(item)} onRemove={requestDeleteAttachment} previewLoader={previewLoader} onPreview={setActivePreview} />
      </>}
    </div>
    {activePreview && <InteractivePreview preview={activePreview} loader={previewLoader} onClose={() => setActivePreview(null)} />}
    {creatingSession && <CreateSessionDialog name={newSessionName} onNameChange={setNewSessionName} onCancel={() => setCreatingSession(false)} onSubmit={(event) => void confirmCreate(event)} />}
    {confirmAction && <ConfirmDeleteDialog action={confirmAction} deleting={deleting} onCancel={() => setConfirmAction(null)} onConfirm={() => void confirmDelete()} />}
  </>
}
