import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const versionedEventKinds = new Set([
  'review_started', 'review_completed', 'review_repair_required', 'review_failed', 'review_subcheck',
  'generated_chart_published', 'generated_chart_rejected', 'tool_call', 'tool_result', 'tool_skipped',
  'visual_observation', 'generated_chart', 'assembly_validation_failure',
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
const source = bundle.outputFiles[0].text
const timeline = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
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
  payload: versionedEventKinds.has(kind) && payload.correlation_version === undefined
    ? { correlation_version: 2, ...payload }
    : payload,
})

const events = [
  event('run-runtime', 1, 'run_started', { process_id: 'run' }),
  event('run-runtime', 2, 'model_started', { turn: 1 }),
  event('run-runtime', 3, 'model_completed', { turn: 1, status: 'ok' }),
  event('run-runtime', 4, 'tool_call', { unit_id: 'measurement:call-1', unit_type: 'measurement', phase: 'action', actor: 'tool', role: 'action', transition_id: 'measurement:call-1:started', operation_id: 'measure:1', call_id: 'call-1', tool_name: 'measure_bars', tool_label: '柱体测量', state: 'running', arguments: { panel_id: 'panel-1' } }),
  event('run-runtime', 5, 'tool_result', { unit_id: 'measurement:call-1', unit_type: 'measurement', phase: 'action', actor: 'tool', role: 'action', transition_id: 'measurement:call-1:completed', operation_id: 'measure:1', call_id: 'call-1', tool_name: 'measure_bars', tool_label: '柱体测量', status: 'success', result: { measurement: { status: 'partial', reference: { session_id: 'session-1', attempt_id: 'attempt-1' }, evidence: { refs: [{ ref: 'B1', kind: 'bar' }] }, quality: { warnings: ['部分柱体缺少标签'] } } } }),
  event('run-runtime', 6, 'run_failed', { process_id: 'run', failure_category: 'provider_balance', failure_code: 'provider_balance_required', outcome_known: true }),
]

const units = timeline.projectDecisionTimeline(events)
assert.deepEqual(units.map((unit) => unit.id), ['measurement:call-1', 'event:run-runtime:6'])
assert.equal(units[0].status, 'completed')
assert.equal(units[1].status, 'failed')
assert.equal(units[0].result?.sequence, 5)
assert.equal(units[0].label, '柱体测量')
assert.deepEqual(units[0].call?.payload.arguments, { panel_id: 'panel-1' })
assert.equal(units[0].result?.payload.result.measurement.status, 'partial')

const toolHeadlines = timeline.projectUserTimeline([
  event('tool-headlines', 1, 'tool_call', { unit_id: 'generation:assemble', unit_type: 'generation', phase: 'assemble', actor: 'tool', role: 'action', transition_id: 'generation:assemble:started', call_id: 'assemble', tool_name: 'assemble_spec', tool_label: '组装图表规格 (assemble_spec)', state: 'running' }),
  event('tool-headlines', 2, 'tool_result', { unit_id: 'generation:assemble', unit_type: 'generation', phase: 'assemble', actor: 'tool', role: 'action', transition_id: 'generation:assemble:completed', call_id: 'assemble', tool_name: 'assemble_spec', tool_label: '组装图表规格 (assemble_spec)', status: 'success' }),
  event('tool-headlines', 3, 'tool_call', { unit_id: 'generation:render', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:render:started', call_id: 'render', tool_name: 'render_chart', tool_label: '生成图表 (render_chart)', state: 'running' }),
  event('tool-headlines', 4, 'tool_result', { unit_id: 'generation:render', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:render:completed', call_id: 'render', tool_name: 'render_chart', tool_label: '生成图表 (render_chart)', status: 'success' }),
  event('tool-headlines', 5, 'generated_chart', { unit_id: 'generation:render', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:render:generated', state: 'available', tool_name: 'render_chart' }),
  event('tool-headlines', 6, 'tool_call', { unit_id: 'generation:late-label', unit_type: 'generation', phase: 'assemble', actor: 'tool', role: 'action', transition_id: 'generation:late-label:started', call_id: 'late-label', tool_name: 'assemble_spec', tool_display_name: 'assemble_spec', state: 'running' }),
  event('tool-headlines', 7, 'tool_result', { unit_id: 'generation:late-label', unit_type: 'generation', phase: 'assemble', actor: 'tool', role: 'action', transition_id: 'generation:late-label:completed', call_id: 'late-label', tool_name: 'assemble_spec', tool_label: '组装图表规格 (assemble_spec)', status: 'success' }),
])
assert.deepEqual(toolHeadlines.map(({ label }) => label), ['组装图表规格 (assemble_spec)', '生成图表 (render_chart)', '组装图表规格 (assemble_spec)'])

const statusEvents = [
  event('status-projection', 1, 'tool_result', { unit_id: 'generation:success', unit_type: 'generation', phase: 'assemble', actor: 'tool', role: 'action', transition_id: 'generation:success:completed', call_id: 'success', status: 'success', result: { count: 3 }, truncated: true }),
  event('status-projection', 2, 'tool_result', { unit_id: 'generation:error', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:error:failed', call_id: 'error', status: 'error', safe_message: '渲染失败原因' }),
  event('status-projection', 3, 'tool_result', { unit_id: 'generation:unexpected', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:unexpected:unknown', call_id: 'unexpected', status: 'retrying' }),
  event('status-projection', 4, 'tool_result', { unit_id: 'generation:missing', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:missing:unknown', call_id: 'missing' }),
  event('status-projection', 5, 'tool_skipped', { unit_id: 'generation:skipped', unit_type: 'generation', phase: 'action', actor: 'system', role: 'action', transition_id: 'generation:skipped:not-started', call_id: 'skipped', state: 'not_started' }),
  event('status-projection', 6, 'tool_skipped', { unit_id: 'generation:skipped-unknown', unit_type: 'generation', phase: 'action', actor: 'system', role: 'action', transition_id: 'generation:skipped-unknown:unknown', call_id: 'skipped-unknown', state: 'blocked' }),
  event('status-projection', 7, 'generated_chart', { unit_id: 'generation:available', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:available:generated', state: 'available' }),
  event('status-projection', 8, 'generated_chart', { unit_id: 'generation:unavailable', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:unavailable:generated', state: 'unavailable' }),
  event('status-projection', 9, 'generated_chart', { unit_id: 'generation:chart-unknown', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:chart-unknown:generated', state: 'queued' }),
  event('status-projection', 10, 'generated_chart', { unit_id: 'generation:chart-missing', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:chart-missing:generated' }),
  event('status-projection', 11, 'tool_call', { unit_id: 'generation:call-unknown', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:call-unknown:started', call_id: 'call-unknown', state: 'queued' }),
  event('status-projection', 12, 'tool_call', { unit_id: 'generation:call-missing', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:call-missing:started', call_id: 'call-missing' }),
  event('status-projection', 13, 'tool_call', { unit_id: 'generation:call-running', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:call-running:started', call_id: 'call-running', state: 'running' }),
  event('status-projection', 14, 'review_repair_required', { unit_id: 'review:blocked', unit_type: 'review', phase: 'repair', actor: 'system', role: 'review', transition_id: 'review:blocked:repair-required', review_id: 'blocked', state: 'repair_required' }),
]
assert.equal(timeline.timelineProtocolStatus(statusEvents).status, 'supported')
assert.deepEqual(timeline.projectUserTimeline(statusEvents).map(({ status }) => status), [
  'completed', 'failed', 'unknown', 'unknown', 'skipped', 'unknown',
  'completed', 'unavailable', 'unknown', 'unknown', 'unknown', 'unknown', 'running', 'blocked',
])
const projectedStatuses = timeline.projectUserTimeline(statusEvents)
assert.equal(projectedStatuses[0].resultTruncated, true)
assert.equal(projectedStatuses[1].failure.safeMessage, '渲染失败原因')
assert.equal(display.timelineEventStatusLabel('tool_call', 'running'), '运行中')
assert.equal(display.timelineEventStatusLabel('tool_result', 'success'), '已完成')
assert.equal(display.timelineEventStatusLabel('tool_skipped', 'not_started'), '未执行')
assert.equal(display.timelineEventStatusLabel('generated_chart', 'available'), '已生成')
assert.equal(display.timelineEventStatusLabel('tool_result', 'retrying'), '状态未知')
assert.equal(display.timelineEventStatusLabel('tool_result', undefined), '状态未知')
assert.equal(display.timelineEventStatusLabel('generated_chart_published', 'published_with_warning'), '已发布·有警告')

const legacyHistory = [event('legacy-v1', 1, 'tool_result', {
  correlation_version: 1,
  unit_id: 'measurement:legacy',
  unit_type: 'measurement',
  phase: 'action',
  actor: 'tool',
  role: 'action',
  transition_id: 'measurement:legacy:completed',
  call_id: 'legacy',
  status: 'success',
})]
assert.equal(timeline.timelineProtocolStatus(legacyHistory).status, 'unsupported_version')
assert.deepEqual(timeline.projectUserTimeline(legacyHistory), [])
const preservedArtifacts = timeline.generatedArtifacts([
  event('legacy-v1', 2, 'generated_chart', {
    correlation_version: 1,
    artifacts: [{ artifactKind: 'generated_chart', artifactId: 'artifact-legacy', title: '已保存结果' }],
  }),
])
assert.equal(preservedArtifacts.length, 1)
assert.equal(preservedArtifacts[0].artifactId, 'artifact-legacy')

const malformedHistory = [event('malformed-v2', 1, 'tool_result', {
  unit_id: 'measurement:malformed',
  unit_type: 'measurement',
  phase: 'action',
  actor: 'tool',
  role: 'action',
  transition_id: 'measurement:malformed:completed',
  call_id: 'malformed',
  state: 'completed',
  status: 'success',
})]
assert.equal(timeline.timelineProtocolStatus(malformedHistory).status, 'malformed')
assert.deepEqual(timeline.projectUserTimeline(malformedHistory), [])

const reviewState = timeline.projectDecisionTimeline([
  event('review-fields', 1, 'review_completed', {
    unit_id: 'review:review-fields',
    unit_type: 'review',
    phase: 'review',
    actor: 'system',
    role: 'review',
    transition_id: 'review:review-fields:passed',
    review_id: 'review-fields',
    state: 'passed',
    review_status: 'failed',
  }),
])
assert.equal(reviewState[0].status, 'passed')
assert.equal(timeline.executionGateValue({ summary: { runId: 'review-fields' }, events: [
  event('review-fields', 2, 'review_completed', { execution_gate: { state: 'failed', blocking: true } }),
], historyGap: false }), null)

const replay = timeline.mergeEvents(events.slice(0, 3), [events[2], events[3], events[1]])
assert.deepEqual(replay.map((item) => item.sequence), [1, 2, 3, 4])

const fixture = JSON.parse(readFileSync(resolve(root, 'scripts/fixtures/test5-user-timeline.json'), 'utf8'))
const fixtureEvents = fixture.events.map((item) => ({
  runId: fixture.run_id,
  sequence: item.sequence,
  kind: item.kind,
  timestamp: '2026-09-22T00:00:00.000Z',
  payload: item.payload,
}))
const visible = timeline.projectUserTimeline(fixtureEvents)
assert.deepEqual(visible.map((item) => item.itemType), ['measurement', 'generation', 'review', 'error'])
assert.equal(visible.filter((item) => item.itemType === 'review').length, 1)
assert.deepEqual(visible.map((item) => item.firstSequence), [5, 9, 10, 16])
assert.equal(visible[0].observations.length, 1)
assert.equal(visible[2].visibleEvents.length, 2)
assert.equal(visible[3].failure.category, 'provider_balance')
assert.ok(visible.every((item) => !['process', 'legacy', 'unknown', 'tool'].includes(item.itemType)))
assert.ok(!visible.some((item) => item.label === '模型轮次开始' || item.label === '模型轮次完成' || item.label === '操作结果已保存'))

const targetedCall = [
  event('targeted-run', 1, 'tool_call', { unit_id: 'measurement:targeted-1', unit_type: 'measurement', phase: 'action', actor: 'tool', role: 'action', transition_id: 'measurement:targeted-1:started', call_id: 'targeted-1', tool_name: 'measure_bars', tool_label: '柱体测量', state: 'running', arguments: { measurement_target: { refs: ['B1'], fields: ['baseline'] } } }),
  event('targeted-run', 2, 'tool_result', { unit_id: 'measurement:targeted-1', unit_type: 'measurement', phase: 'action', actor: 'tool', role: 'action', transition_id: 'measurement:targeted-1:completed', call_id: 'targeted-1', tool_name: 'measure_bars', status: 'success', result: { measurement: { status: 'complete', reference: { attempt_id: 'attempt-2' } } } }),
  event('targeted-run', 3, 'tool_call', { unit_id: 'measurement:targeted-2', unit_type: 'measurement', phase: 'action', actor: 'tool', role: 'action', transition_id: 'measurement:targeted-2:started', call_id: 'targeted-2', tool_name: 'measure_bars', tool_label: '柱体测量', state: 'running', arguments: { measurement_target: { refs: ['B2'], fields: ['baseline'] } } }),
  event('targeted-run', 4, 'tool_result', { unit_id: 'measurement:targeted-2', unit_type: 'measurement', phase: 'action', actor: 'tool', role: 'action', transition_id: 'measurement:targeted-2:completed', call_id: 'targeted-2', tool_name: 'measure_bars', status: 'success', result: { measurement: { status: 'partial', reference: { attempt_id: 'attempt-3' } } } }),
]
const targetedVisible = timeline.projectUserTimeline(targetedCall)
assert.equal(targetedVisible.length, 2)
assert.deepEqual(targetedVisible.map((item) => item.call?.payload.call_id), ['targeted-1', 'targeted-2'])

const noisyEvents = [
  ...fixtureEvents,
  event('test5-human-timeline', 20, 'review_subcheck', {
    unit_id: 'review:test5',
    unit_type: 'review',
    phase: 'review',
    actor: 'system',
    role: 'review',
    transition_id: 'review:test5:subcheck',
    review_id: 'review:test5',
    state: 'completed',
    check_type: 'deterministic_audit',
  }),
]
const noisyVisible = timeline.projectUserTimeline(noisyEvents)
assert.deepEqual(noisyVisible.map((item) => item.itemType), ['measurement', 'generation', 'review', 'error'])
assert.equal(noisyVisible.find((item) => item.itemType === 'review').visibleEvents.length, 2)
assert.ok(!noisyVisible.some((item) => item.label === '测量决策' || item.label === '等待主 Agent 选择测量证据'))
assert.ok(!noisyVisible.flatMap((item) => item.visibleEvents).some((item) => item.kind === 'review_subcheck'))

const ordinaryWorkspaceSource = readFileSync(resolve(root, 'src/components/workspace.tsx'), 'utf8')
const evaluationSource = readFileSync(resolve(root, 'src/components/evaluation.tsx'), 'utf8')
assert.match(ordinaryWorkspaceSource, /import \{ RunTimeline \} from '\.\/run'/)
assert.match(evaluationSource, /import \{ RunTimeline \} from '\.\/run'/)
assert.match(evaluationSource, /events: props\.history\.events/)
const supplementalFilter = evaluationSource.match(/const supplementalEntries = ([^\n]+)/)?.[1] || ''
assert.ok(supplementalFilter)
assert.ok(!supplementalFilter.includes("entry.kind === 'tool_call'") && !supplementalFilter.includes("entry.kind === 'tool_result'"))

const collectionVisible = timeline.projectUserTimeline([
  event('collection-run', 1, 'generated_chart', { unit_id: 'generation:candidate-collection', unit_type: 'generation', phase: 'render', actor: 'tool', role: 'action', transition_id: 'generation:candidate-collection:rendered', state: 'available', candidate_id: 'candidate-collection' }),
  event('collection-run', 2, 'review_started', { unit_id: 'review:child-a', unit_type: 'review', phase: 'review', actor: 'system', role: 'review', transition_id: 'review:child-a:started', parent_unit_id: 'review:collection:batch-1', review_id: 'review-a', candidate_id: 'candidate-a', state: 'reviewing' }),
  event('collection-run', 3, 'review_failed', { unit_id: 'review:child-a', unit_type: 'review', phase: 'review', actor: 'system', role: 'review', transition_id: 'review:child-a:failed', parent_unit_id: 'review:collection:batch-1', review_id: 'review-a', candidate_id: 'candidate-a', state: 'failed', safe_message: '左侧候选未通过' }),
  event('collection-run', 4, 'review_started', { unit_id: 'review:child-b', unit_type: 'review', phase: 'review', actor: 'system', role: 'review', transition_id: 'review:child-b:started', parent_unit_id: 'review:collection:batch-1', review_id: 'review-b', candidate_id: 'candidate-b', state: 'reviewing' }),
  event('collection-run', 5, 'review_completed', { unit_id: 'review:child-b', unit_type: 'review', phase: 'review', actor: 'system', role: 'review', transition_id: 'review:child-b:completed', parent_unit_id: 'review:collection:batch-1', review_id: 'review-b', candidate_id: 'candidate-b', state: 'passed' }),
])
assert.deepEqual(collectionVisible.map((item) => item.itemType), ['generation', 'review', 'review'])
assert.equal(collectionVisible.filter((item) => item.itemType === 'review').length, 2)
assert.equal(collectionVisible.find((item) => item.itemType === 'review').failure.safeMessage, '左侧候选未通过')

const duplicateSequence = timeline.projectUserTimeline(timeline.mergeEvents([
  event('strict-tool', 1, 'tool_call', { unit_id: 'observation:strict-call', unit_type: 'observation', phase: 'action', actor: 'tool', role: 'action', transition_id: 'observation:strict-call:started', call_id: 'strict-call', state: 'running' }),
], [
  event('strict-tool', 2, 'visual_observation', { unit_id: 'observation:strict-call', unit_type: 'observation', phase: 'observe', actor: 'tool', role: 'observation', transition_id: 'observation:strict-call:observed', call_id: 'strict-call', state: 'observed', observations: [{ observationId: 'obs-1' }] }),
  event('strict-tool', 3, 'tool_result', { unit_id: 'observation:strict-call', unit_type: 'observation', phase: 'action', actor: 'tool', role: 'action', transition_id: 'observation:strict-call:completed', call_id: 'strict-call', status: 'success', result: { bars: 2 } }),
  event('strict-tool', 3, 'tool_result', { unit_id: 'observation:strict-call', unit_type: 'observation', phase: 'action', actor: 'tool', role: 'action', transition_id: 'observation:strict-call:completed', call_id: 'strict-call', status: 'success', result: { bars: 99 } }),
]))
assert.equal(duplicateSequence.length, 1)
assert.equal(duplicateSequence[0].itemType, 'observation')
assert.equal(duplicateSequence[0].observations.length, 1)

const runComponentSource = readFileSync(resolve(root, 'src/components/run.tsx'), 'utf8')
assert.ok(/const \[open, setOpen\] = useState\(false\)/.test(runComponentSource))
assert.ok(/open=\{open\} onToggle=\{\(event\) => setOpen\(event\.currentTarget\.open\)\}/.test(runComponentSource))
assert.ok(runComponentSource.includes('key={item.id}'))
assert.ok(runComponentSource.includes('user-timeline-failure-summary'))
assert.ok(runComponentSource.includes('item.resultTruncated && <span className="user-timeline-truncation"'))
assert.ok(ordinaryWorkspaceSource.includes('generatedArtifacts(timeline.events)'))
assert.ok(ordinaryWorkspaceSource.includes('className="run-result"') && ordinaryWorkspaceSource.includes('GeneratedChartView'))
assert.ok(!evaluationSource.includes('projectUserTimeline'))

console.log('timeline smoke passed (internal grouping, flat user projection, tool merge, failure promotion, replay dedupe)')
