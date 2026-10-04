import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { resolve } from 'node:path'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'

const root = resolve(import.meta.dirname, '..')
async function load(path) {
  const result = await build({ entryPoints: [resolve(root, path)], bundle: true, format: 'esm', platform: 'node', write: false, logLevel: 'silent' })
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`)
}
const { contextDisplay, selectContextRun } = await load('src/domain/figura/context.ts')
const { createFiguraWorkspaceApi } = await load('src/api/figura/workspace.ts')
const { createRunController } = await load('src/domain/run/controller.ts')
const base = { runId: 'run', sessionId: 'session', ordinal: 1, status: 'running', provider: 'qwen', model: 'original-model', createdAt: 'time', startedAt: null, finishedAt: null, terminalCode: null, terminalMessage: null, executionState: 'executing', chartRenders: [] }
let current = { ...base }
const api = createFiguraWorkspaceApi({ getRunHistory: async () => ({ run: structuredClone(current), events: [], historyGap: false }) })
assert.equal((await api.runs.history('session', 'run')).run.contextUsage, undefined)
current.contextUsage = { inputTokens: 20000, contextWindowTokens: 100000 }
const initial = (await api.runs.history('session', 'run')).run
assert.equal(initial.ordinal, 1)
assert.equal(contextDisplay(initial).label, '上下文 ≈ 20%')
assert.deepEqual(selectContextRun([initial, { ...initial, runId: 'next', ordinal: 2, contextUsage: null }], ''), { ...initial, runId: 'next', ordinal: 2, contextUsage: null })
assert.equal(selectContextRun([initial], 'new-active'), undefined)
assert.equal(selectContextRun([initial], 'run'), initial)
assert.equal(contextDisplay({ ...initial, contextUsage: { inputTokens: 10, contextWindowTokens: null } }).label, '上下文 ≈ 10 tokens')
assert.equal(contextDisplay({ ...initial, contextUsage: { inputTokens: 1, contextWindowTokens: 1000 } }).label, '上下文 ≈ <1%')
assert.equal(contextDisplay({ ...initial, contextUsage: { inputTokens: 120, contextWindowTokens: 100 } }).fill, 100)

const histories = []
let terminalCount = 0
const controller = createRunController({
  client: { getRunHistory: api.runs.history, subscribeRun() { return { close() {} } } },
  sessionId: 'session', runId: 'run', activityPollIntervalMs: 5,
  callbacks: { isCurrent: () => true, onEvent() {}, onHistory(h) { histories.push(h.run) }, onState() {}, onTerminal() { terminalCount++ }, onUnavailable() {} },
})
async function waitFor(predicate) {
  const deadline = Date.now() + 1000
  while (!predicate() && Date.now() < deadline) await new Promise((r) => setTimeout(r, 5))
  assert.ok(predicate(), 'existing controller should update the estimate')
}
try {
  controller.start()
  await waitFor(() => histories.some((r) => r.contextUsage?.inputTokens === 20000))
  current = { ...current, contextUsage: { inputTokens: 30000, contextWindowTokens: 100000 } }
  await waitFor(() => histories.some((r) => r.contextUsage?.inputTokens === 30000))
  // A retry keeps the same binding snapshot, even if the next selected model changes.
  await controller.reconcile()
  assert.equal(contextDisplay(histories.at(-1)).label, '上下文 ≈ 30%')
  assert.match(contextDisplay(histories.at(-1)).detail, /original-model/)
  current = { ...current, status: 'failed', executionState: 'terminal', finishedAt: 'finished' }
  await waitFor(() => terminalCount === 1)
  assert.equal((await api.runs.history('session', 'run')).run.contextUsage.inputTokens, 30000)
} finally { controller.close() }

const temp = mkdtempSync(resolve(tmpdir(), 'figura-context-ui-'))
try {
  const result = await build({
    stdin: { contents: `import React from 'react'; import { renderToStaticMarkup } from 'react-dom/server'; import { ConversationPanel } from './src/components/workspace'; export function render(props) { return renderToStaticMarkup(React.createElement(ConversationPanel, props)); }`, resolveDir: root, loader: 'tsx' },
    bundle: true, format: 'cjs', platform: 'node', write: false, logLevel: 'silent', jsx: 'automatic', define: { 'import.meta.env': '{}' },
  })
  const path = resolve(temp, 'ui.cjs')
  writeFileSync(path, result.outputFiles[0].text)
  const { render } = (await import(pathToFileURL(path).href)).default
  const props = { data: null, timelines: [], expandedRuns: new Set(), mode: 'figura', runState: 'idle', provider: 'qwen', loading: false, loadingSession: false }
  assert.match(render(props), /上下文待估算/)
  const waiting = render({ ...props, contextRun: initial, loading: true })
  assert.match(waiting, /上下文 ≈ 20%/)
  assert.match(waiting, /20,000 \/ 100,000 tokens/)
  const switched = render({ ...props, providerValue: 'deepseek', contextRun: initial })
  assert.match(switched, /original-model/)
  assert.match(switched, /上下文 ≈ 20%/)
  const overflow = render({ ...props, contextRun: { ...initial, contextUsage: { inputTokens: 120, contextWindowTokens: 100 } } })
  assert.match(overflow, /上下文 ≈ 120%/)
  assert.match(overflow, /width:100%/)
  assert.doesNotMatch(overflow, /<textarea[^>]*disabled/)
  assert.doesNotMatch(render({ ...props, mode: 'mock', contextRun: initial }), /context-indicator/)
  if (process.env.FIGURA_CONTEXT_PREVIEW) writeFileSync(process.env.FIGURA_CONTEXT_PREVIEW, '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Figura 上下文估算预览</title><link rel="stylesheet" href="/src/styles/global.css"><body style="padding:24px">' + render({ ...props, contextRun: initial }) + '</body></html>')
} finally { rmSync(temp, { recursive: true, force: true }) }
console.log('Figura context smoke passed (mapping, waiting, retry, refresh, model identity, legacy DTO, overflow, rendering)')
