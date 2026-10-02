import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { resolve } from 'node:path'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'

const root = resolve(import.meta.dirname, '..')
async function load(path, define = {}) {
  const bundle = await build({ entryPoints: [resolve(root, path)], bundle: true, format: 'esm', platform: 'node', write: false, logLevel: 'silent', define })
  return import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)
}
const { createRunController } = await load('src/domain/run/controller.ts')
const { createFiguraClient } = await load('src/api/figura/client.ts', { 'import.meta.env.VITE_FIGURA_GATEWAY_URL': '""' })
const { createFiguraWorkspaceApi } = await load('src/api/figura/workspace.ts')
const run = { runId: 'run', sessionId: 'session', ordinal: 1, status: 'running', provider: 'qwen', model: 'model', createdAt: 'time', startedAt: null, finishedAt: null, terminalCode: null, terminalMessage: null, executionState: 'queued', stopRequestedAt: null, availableActions: ['stop'], chartRenders: [] }
const stopRequest = { requestId: 'request', requestedAt: 'accepted', reason: 'user_requested' }
let reads = 0
let stops = 0
let loseResponse = false
let current = structuredClone(run)
const originalFetch = globalThis.fetch
const seen = []
globalThis.fetch = async (url, init) => {
  seen.push([url, init])
  if (url.endsWith('/stop')) {
    stops++
    current = { ...current, executionState: 'stopping', stopRequestedAt: 'accepted', availableActions: [] }
    if (loseResponse) throw new Error('response lost after acceptance')
    return new Response(JSON.stringify({ run: current, stopRequest }), { status: 202 })
  }
  reads++
  return new Response(JSON.stringify({ run: current, events: [] }), { status: 200 })
}
try {
  const client = createFiguraClient('http://local.test/api/v1')
  const api = createFiguraWorkspaceApi(client)
  const accepted = await api.runs.requestRunStop('session', 'run')
  assert.equal(accepted.status, 'running')
  assert.equal(accepted.executionState, 'stopping')
  assert.deepEqual(accepted.availableActions, [])
  assert.equal(seen[0][1].method, 'POST')
  assert.equal(seen[0][1].body, '{}')
  const histories = []
  let terminals = 0
  let closedSubscriptions = 0
  const controller = createRunController({
    client: { getRunHistory: api.runs.history, subscribeRun() { return { close() { closedSubscriptions++ } } } },
    sessionId: 'session', runId: 'run', activityPollIntervalMs: 5,
    callbacks: { isCurrent: () => true, onEvent() {}, onHistory(h) { histories.push(h.run.executionState) }, onState() {}, onTerminal() { terminals++ }, onUnavailable() {} },
  })
  controller.start()
  const waitFor = async (predicate) => {
    const deadline = Date.now() + 1000
    while (!predicate() && Date.now() < deadline) await new Promise(r => setTimeout(r, 5))
    assert.ok(predicate(), 'controller should converge within bounded polling')
  }
  // Reload discovers an accepted request through the existing lifecycle owner.
  await waitFor(() => histories.includes('stopping'))
  assert.equal(terminals, 0)
  loseResponse = true
  await assert.rejects(api.runs.requestRunStop('session', 'run'), /无法连接/)
  assert.equal((await api.runs.history('session', 'run')).run.executionState, 'stopping')
  current = { ...current, status: 'interrupted', executionState: 'terminal', finishedAt: 'finished' }
  await waitFor(() => terminals === 1)
  const terminalReads = reads
  await new Promise(r => setTimeout(r, 20))
  assert.equal(reads, terminalReads, 'terminal closes activity reads')
  assert.equal(stops, 2, 'history refresh never resubmits stop or user input')
  assert.equal(closedSubscriptions, 1)
  controller.close()
  // A new Run uses a new controller after the previous abnormal terminal.
  current = { ...run, runId: 'next', executionState: 'executing' }
  assert.equal((await api.runs.history('session', 'next')).run.executionState, 'executing')
} finally {
  globalThis.fetch = originalFetch
}
console.log('Figura stop smoke passed (acceptance, reload, lost response, activity convergence, terminal cleanup)')

const temp = mkdtempSync(resolve(tmpdir(), 'figura-stop-ui-'))
try {
  const uiBundle = await build({
    stdin: { contents: `import React from 'react'; import { renderToStaticMarkup } from 'react-dom/server'; import { ConversationPanel, SessionSidebar } from './src/components/workspace'; export function conversation(props) { return renderToStaticMarkup(React.createElement(ConversationPanel, props)); } export function sidebar(props) { return renderToStaticMarkup(React.createElement(SessionSidebar, props)); }`, resolveDir: root, loader: 'tsx' },
    bundle: true, format: 'cjs', platform: 'node', write: false, logLevel: 'silent', jsx: 'automatic', define: { 'import.meta.env': '{}' },
  })
  const path = resolve(temp, 'ui.cjs')
  writeFileSync(path, uiBundle.outputFiles[0].text)
  const { conversation, sidebar } = (await import(pathToFileURL(path).href)).default
  const waiting = conversation({
    data: { session: { id: 'session', name: 'test', runCount: 1 }, messages: [] }, timelines: [], expandedRuns: new Set(),
    mode: 'figura', runState: 'running', provider: 'qwen', loading: true, loadingSession: false,
    providerOptions: [{ id: 'qwen', label: 'Qwen', status: 'ready' }], onFiguraStop() {}, figuraStopping: true, submissionBlocked: true,
  })
  assert.match(waiting, /disabled="" aria-label="停止分析"/)
  assert.match(waiting, /正在停止，等待当前步骤结束/)
  assert.match(waiting, /<textarea[^>]*disabled=""/)
  assert.doesNotMatch(waiting, /Figura Agent 正在思考/)
  const nav = sidebar({ sessions: [{ id: 'session', name: 'test', runCount: 1 }], activeId: 'session', onCreate() {}, onSelect() {}, onDelete() {}, mode: 'figura', showEvaluations: false, disabledDeleteSessionId: 'session' })
  assert.match(nav, /class="session-more" disabled=""/)
  const legacy = conversation({ data: null, timelines: [], expandedRuns: new Set(), mode: 'mock', runState: 'idle', provider: 'qwen', loading: false, loadingSession: false })
  assert.doesNotMatch(legacy, /aria-label="停止分析"/)
  console.log('Figura stop UI rendering passed (waiting text, disabled controls, other-mode compatibility)')
} finally {
  rmSync(temp, { recursive: true, force: true })
}
