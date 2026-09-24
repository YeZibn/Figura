import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const strictKinds = new Set([
  'chart_staged', 'chart_verification_result', 'chart_promotion_result',
  'tool_call', 'tool_result', 'tool_skipped', 'visual_observation', 'assembly_validation_failure',
])
const bundle = await build({
  entryPoints: [resolve(root, 'src/domain/run/timeline.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  sourcemap: false,
  logLevel: 'silent',
})
const timeline = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)
const displayBundle = await build({
  entryPoints: [resolve(root, 'src/domain/display.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  sourcemap: false,
  logLevel: 'silent',
})
const display = await import(`data:text/javascript;base64,${Buffer.from(displayBundle.outputFiles[0].text).toString('base64')}`)

const event = (runId, sequence, kind, payload = {}) => ({
  runId,
  sequence,
  kind,
  timestamp: '2026-09-22T00:00:00.000Z',
  payload: strictKinds.has(kind) && payload.correlation_version === undefined
    ? { correlation_version: 2, ...payload }
    : payload,
})
const trace = (unit, type, phase, actor, role, transition, extra = {}) => ({
  unit_id: unit,
  unit_type: type,
  phase,
  actor,
  role,
  transition_id: transition,
  ...extra,
})

const toolEvents = [
  event('run-runtime', 1, 'tool_call', trace('measurement:call-1', 'measurement', 'action', 'tool', 'action', 'measurement:call-1:started', { call_id: 'call-1', tool_name: 'measure_bars', tool_label: '柱体测量', state: 'running' })),
  event('run-runtime', 2, 'tool_result', trace('measurement:call-1', 'measurement', 'action', 'tool', 'action', 'measurement:call-1:completed', { call_id: 'call-1', tool_name: 'measure_bars', status: 'success', result: { bars: 3 } })),
]
const toolTimeline = timeline.projectUserTimeline(toolEvents)
assert.equal(toolTimeline.length, 1)
assert.equal(toolTimeline[0].itemType, 'measurement')
assert.equal(toolTimeline[0].status, 'completed')
assert.equal(toolTimeline[0].call.sequence, 1)
assert.equal(toolTimeline[0].result.sequence, 2)
assert.equal(toolTimeline[0].label, '柱体测量')

const chartEvents = [
  event('chart-run', 1, 'chart_staged', trace('generation:stg_abc12345', 'generation', 'render', 'tool', 'action', 'generation:stg_abc12345:staged', {
    call_id: 'render-1', staged_ref: 'stg_abc12345', state: 'staged', chart_type: 'bar', title: '销售额',
    media_type: 'image/png', caption: '销售额', width: 640, height: 400, chart_spec_digest: 'sha256:spec',
  })),
  event('chart-run', 2, 'chart_verification_result', trace('verification:ver_abc12345', 'verification', 'verify', 'system', 'verification', 'verification:ver_abc12345:completed', {
    parent_unit_id: 'generation:stg_abc12345', staged_ref: 'stg_abc12345', verification_ref: 'ver_abc12345', state: 'pass_with_warning',
    verification: { verificationRef: 'ver_abc12345', stagedRef: 'stg_abc12345', status: 'pass_with_warning', checks: { encoded_artifact: 'pass' }, issues: [{ code: 'small_label', severity: 'warning' }] },
  })),
  event('chart-run', 3, 'chart_promotion_result', trace('artifact:artifact_0123456789abcdef', 'artifact', 'publish', 'system', 'artifact', 'artifact:artifact_0123456789abcdef:published', {
    parent_unit_id: 'generation:stg_abc12345', staged_ref: 'stg_abc12345', verification_ref: 'ver_abc12345', artifact_id: 'artifact_0123456789abcdef', state: 'published_with_warning', warning: true,
  })),
]
assert.equal(timeline.timelineProtocolStatus(chartEvents).status, 'supported')
const chartTimeline = timeline.projectUserTimeline(chartEvents)
assert.deepEqual(chartTimeline.map(({ itemType }) => itemType), ['generation', 'verification', 'artifact'])
assert.deepEqual(chartTimeline.map(({ status }) => status), ['completed', 'passed', 'published'])
const generated = timeline.generatedArtifacts(chartEvents)
assert.equal(generated.length, 1)
assert.equal(generated[0].stagedRef, 'stg_abc12345')
assert.equal(generated[0].verification.status, 'pass_with_warning')
assert.equal(generated[0].artifactId, 'artifact_0123456789abcdef')
assert.equal(display.timelineEventStatusLabel('chart_promotion_result', 'published_with_warning'), '已发布·有警告')
assert.equal(display.timelineEventStatusLabel('chart_verification_result', 'fail'), '验证未通过')

const collectionEvents = [
  event('collection-run', 1, 'chart_staged', trace('generation:stg_child_a', 'generation', 'render', 'tool', 'action', 'generation:stg_child_a:staged', {
    call_id: 'render-a', staged_ref: 'stg_child_a', collection_id: 'collection-1', parent_unit_id: 'generation:collection:collection-1', state: 'staged',
  })),
  event('collection-run', 2, 'chart_staged', trace('generation:stg_child_b', 'generation', 'render', 'tool', 'action', 'generation:stg_child_b:staged', {
    call_id: 'render-b', staged_ref: 'stg_child_b', collection_id: 'collection-1', parent_unit_id: 'generation:collection:collection-1', state: 'staged',
  })),
  event('collection-run', 3, 'chart_verification_result', trace('verification:ver_child_a', 'verification', 'verify', 'system', 'verification', 'verification:ver_child_a:completed', {
    parent_unit_id: 'generation:stg_child_a', staged_ref: 'stg_child_a', verification_ref: 'ver_child_a', state: 'fail',
    verification: { verificationRef: 'ver_child_a', stagedRef: 'stg_child_a', status: 'fail', checks: { spec: 'fail' }, issues: [{ code: 'bad_spec', severity: 'error' }] },
  })),
  event('collection-run', 4, 'chart_verification_result', trace('verification:ver_child_b', 'verification', 'verify', 'system', 'verification', 'verification:ver_child_b:completed', {
    parent_unit_id: 'generation:stg_child_b', staged_ref: 'stg_child_b', verification_ref: 'ver_child_b', state: 'pass',
    verification: { verificationRef: 'ver_child_b', stagedRef: 'stg_child_b', status: 'pass', checks: { spec: 'pass' }, issues: [] },
  })),
  event('collection-run', 5, 'chart_promotion_result', trace('artifact:artifact_abcdef0123456789', 'artifact', 'publish', 'system', 'artifact', 'artifact:artifact_abcdef0123456789:published', {
    parent_unit_id: 'generation:stg_child_b', staged_ref: 'stg_child_b', verification_ref: 'ver_child_b', artifact_id: 'artifact_abcdef0123456789', state: 'published',
  })),
]
const collectionTimeline = timeline.projectUserTimeline(collectionEvents)
assert.equal(collectionTimeline[0].id, 'generation:collection:collection-1')
assert.equal(collectionTimeline[0].status, 'partial')
assert.deepEqual(collectionTimeline[0].children.map((child) => child.id), ['generation:stg_child_a', 'generation:stg_child_b'])
assert.equal(collectionTimeline[0].children[0].children[0].status, 'failed')
assert.equal(collectionTimeline[0].children[0].children.length, 1)
assert.equal(collectionTimeline[0].children[1].children.length, 2)

const duplicateVerification = event('duplicate-run', 2, 'chart_verification_result', trace(
  'verification:ver_duplicate', 'verification', 'verify', 'system', 'verification', 'verification:ver_duplicate:completed',
  { staged_ref: 'stg_duplicate', verification_ref: 'ver_duplicate', state: 'fail', verification: { status: 'fail', issues: [] } },
))
const deduped = timeline.projectUserTimeline([
  event('duplicate-run', 1, 'chart_staged', trace('generation:stg_duplicate', 'generation', 'render', 'tool', 'action', 'generation:stg_duplicate:staged', { call_id: 'render', staged_ref: 'stg_duplicate', state: 'staged' })),
  duplicateVerification,
  { ...duplicateVerification, sequence: 3 },
])
assert.equal(deduped.find((item) => item.itemType === 'verification').visibleEvents.length, 1)

const retired = event('old-history', 1, 'review_completed', { correlation_version: 2 })
assert.equal(timeline.timelineProtocolStatus([retired]).status, 'unsupported_version')
assert.deepEqual(timeline.projectUserTimeline([retired]), [])
const retiredField = event('old-field', 1, 'chart_staged', trace('generation:stg_old_field', 'generation', 'render', 'tool', 'action', 'generation:stg_old_field:staged', {
  call_id: 'render', staged_ref: 'stg_old_field', state: 'staged', candidate_id: 'candidate_old',
}))
assert.equal(timeline.timelineProtocolStatus([retiredField]).status, 'malformed')

const fixture = JSON.parse(readFileSync(resolve(root, 'scripts/fixtures/test5-user-timeline.json'), 'utf8'))
const fixtureEvents = fixture.events.map((item) => ({
  runId: fixture.run_id,
  sequence: item.sequence,
  kind: item.kind,
  timestamp: '2026-09-22T00:00:00.000Z',
  payload: item.payload,
}))
const visible = timeline.projectUserTimeline(fixtureEvents)
assert.deepEqual(visible.map((item) => item.itemType), ['measurement', 'generation', 'verification', 'error'])
assert.deepEqual(visible.map((item) => item.firstSequence), [5, 9, 10, 16])
assert.equal(visible[0].observations.length, 1)
assert.equal(visible[2].status, 'failed')
assert.equal(visible[3].failure.category, 'provider_balance')
assert.ok(!visible.some((item) => item.label === '模型轮次开始' || item.label === '模型轮次完成'))

console.log('Timeline smoke passed')
