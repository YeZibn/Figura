import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const bundle = await build({
  entryPoints: [resolve(root, 'src/domain/run/timeline.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  sourcemap: false,
  logLevel: 'silent',
})
const source = bundle.outputFiles[0].text
const timeline = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

const event = (runId, sequence, kind, payload = {}) => ({
  runId,
  sequence,
  kind,
  timestamp: '2026-09-22T00:00:00.000Z',
  payload,
})

const events = [
  event('run-runtime', 1, 'run_started', { process_id: 'run' }),
  event('run-runtime', 2, 'model_started', { turn: 1 }),
  event('run-runtime', 3, 'model_completed', { turn: 1, status: 'ok' }),
  event('run-runtime', 4, 'tool_call', { operation_id: 'measure:1', call_id: 'call-1', tool_name: 'measure_bars' }),
  event('run-runtime', 5, 'tool_result', { operation_id: 'measure:1', call_id: 'call-1', tool_name: 'measure_bars', status: 'success', result: { bars: 3 } }),
  event('run-runtime', 6, 'run_failed', { process_id: 'run', failure_category: 'provider_balance', failure_code: 'provider_balance_required', outcome_known: true }),
]

const units = timeline.projectDecisionTimeline(events)
assert.deepEqual(units.map((unit) => unit.id), [
  'process:run-runtime:run',
  'process:run-runtime:turn:1',
  'process:run-runtime:operation:measure:1',
])
assert.equal(units[0].status, 'failed')
assert.equal(units[1].status, 'completed')
assert.equal(units[2].toolSteps.length, 1)

const replay = timeline.mergeEvents(events.slice(0, 3), [events[2], events[3], events[1]])
assert.deepEqual(replay.map((item) => item.sequence), [1, 2, 3, 4])

const legacyUnits = timeline.projectDecisionTimeline([
  event('legacy-run', 1, 'run_started', { status: 'running' }),
  event('legacy-run', 2, 'run_failed', { code: 'provider_request_failed' }),
])
assert.equal(legacyUnits.length, 1)
assert.equal(legacyUnits[0].id, 'legacy:legacy-run:run')
assert.equal(legacyUnits[0].legacy, true)

const fixture = JSON.parse(readFileSync(resolve(root, 'scripts/fixtures/test5-user-timeline.json'), 'utf8'))
const fixtureEvents = fixture.events.map((item) => ({
  runId: fixture.run_id,
  sequence: item.sequence,
  kind: item.kind,
  timestamp: '2026-09-22T00:00:00.000Z',
  payload: item.payload,
}))
const visible = timeline.projectUserTimeline(fixtureEvents)
assert.deepEqual(visible.map((item) => item.itemType), ['tool', 'generation', 'review', 'error'])
assert.deepEqual(visible.map((item) => item.firstSequence), [5, 9, 10, 16])
assert.equal(visible[0].toolStep.observations.length, 1)
assert.equal(visible[2].visibleEvents.length, 2)
assert.equal(visible[3].failure.category, 'provider_balance')
assert.ok(visible.every((item) => !['process', 'legacy', 'unknown'].includes(item.itemType)))
assert.ok(!visible.some((item) => item.label === '模型轮次开始' || item.label === '模型轮次完成' || item.label === '操作结果已保存'))

const noisyEvents = [
  ...fixtureEvents,
  event('test5-human-timeline', 18, 'measurement_decision_required', {
    unit_id: 'measurement:test5',
    unit_type: 'measurement',
    required: true,
    diagnostic_only: true,
  }),
  event('test5-human-timeline', 19, 'measurement_evidence_used', {
    unit_id: 'measurement:test5',
    unit_type: 'measurement',
    panel_id: 'panel-left',
    attempt_id: 'attempt-test5',
    evidence_refs: ['B1', 'B2'],
  }),
  event('test5-human-timeline', 20, 'review_subcheck', {
    unit_id: 'review:test5',
    unit_type: 'review',
    review_id: 'review:test5',
    check_type: 'deterministic_audit',
    status: 'completed',
  }),
  event('test5-human-timeline', 21, 'review_gate_updated', {
    unit_id: 'review:test5',
    unit_type: 'review',
    review_id: 'review:test5',
    state: 'failed',
    blocking: true,
    next_action: 'repair',
  }),
]
const noisyVisible = timeline.projectUserTimeline(noisyEvents)
assert.deepEqual(noisyVisible.map((item) => item.itemType), ['tool', 'generation', 'review', 'error'])
assert.equal(noisyVisible.find((item) => item.itemType === 'review').visibleEvents.length, 2)
assert.ok(!noisyVisible.some((item) => item.label === '测量决策' || item.label === '等待主 Agent 选择测量证据'))
assert.ok(!noisyVisible.flatMap((item) => item.visibleEvents).some((item) => item.kind === 'review_subcheck' || item.kind === 'review_gate_updated'))

const collectionVisible = timeline.projectUserTimeline([
  event('collection-run', 1, 'generated_chart', { unit_id: 'generation:candidate-collection', unit_type: 'generation', candidate_id: 'candidate-collection' }),
  event('collection-run', 2, 'review_started', { unit_id: 'review:child-a', unit_type: 'review', parent_unit_id: 'review:collection:batch-1', review_id: 'review-a', candidate_id: 'candidate-a', state: 'reviewing' }),
  event('collection-run', 3, 'review_failed', { unit_id: 'review:child-a', unit_type: 'review', parent_unit_id: 'review:collection:batch-1', review_id: 'review-a', candidate_id: 'candidate-a', state: 'failed', safe_message: '左侧候选未通过' }),
  event('collection-run', 4, 'review_started', { unit_id: 'review:child-b', unit_type: 'review', parent_unit_id: 'review:collection:batch-1', review_id: 'review-b', candidate_id: 'candidate-b', state: 'reviewing' }),
  event('collection-run', 5, 'review_completed', { unit_id: 'review:child-b', unit_type: 'review', parent_unit_id: 'review:collection:batch-1', review_id: 'review-b', candidate_id: 'candidate-b', state: 'passed' }),
])
assert.deepEqual(collectionVisible.map((item) => item.itemType), ['generation', 'review'])
assert.equal(collectionVisible.filter((item) => item.itemType === 'review').length, 1)
assert.equal(collectionVisible.find((item) => item.itemType === 'review').failure.safeMessage, '集合审核中有 1 个候选未通过')

const duplicateSequence = timeline.normalizeTimeline([
  event('legacy-tool', 1, 'tool_call', { tool_name: 'measure_bars' }),
  event('legacy-tool', 2, 'visual_observation', { call_id: 'sequence-1', observations: [{ observationId: 'obs-1' }] }),
  event('legacy-tool', 3, 'tool_result', { tool_name: 'measure_bars', status: 'success', result: { bars: 2 } }),
  event('legacy-tool', 3, 'tool_result', { tool_name: 'measure_bars', status: 'success', result: { bars: 99 } }),
])
assert.equal(duplicateSequence.length, 1)
assert.equal(duplicateSequence[0].kind, 'tool')
assert.equal(duplicateSequence[0].step.observations.length, 1)

// Ordinary runs and evaluation cases intentionally call the same pure projection.
assert.deepEqual(
  timeline.projectUserTimeline(fixtureEvents).map(({ id, itemType, label, status, firstSequence }) => ({ id, itemType, label, status, firstSequence })),
  timeline.projectUserTimeline(fixtureEvents).map(({ id, itemType, label, status, firstSequence }) => ({ id, itemType, label, status, firstSequence })),
)

console.log('timeline smoke passed (internal grouping, flat user projection, tool merge, failure promotion, replay dedupe)')
