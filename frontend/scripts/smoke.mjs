import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const required = ['src/App.tsx', 'src/api/client.ts', 'src/api/workspace.ts', 'src/api/mockClient.ts', 'src/api/mock/fixtures.ts', 'src/api/gatewayClient.ts', 'src/api/gateway/transport.ts', 'src/api/gateway/mappers.ts', 'src/api/gateway/runStream.ts', 'src/api/gateway/evaluationResource.ts', 'src/domain/run/controller.ts', 'src/components/common.tsx', 'src/components/dialogs.tsx', 'src/components/evaluation.tsx', 'src/components/preview.tsx', 'src/components/run.tsx', 'src/components/types.ts', 'src/components/workspace.tsx', 'src/types/protocol.ts', 'src/types/run.ts', 'src/runtime.ts', 'src/previewResources.ts', 'src/styles/global.css', 'src/styles/tokens.css', 'src/styles/foundation.css', 'src/styles/workspace.css', 'src/styles/evaluation.css', 'src/styles/attachment-preview.css', 'src/styles/dialogs.css', 'src/styles/run.css', 'src/styles/responsive.css', 'index.html', 'scripts/dev-gateway.mjs', 'scripts/tauri-dev-gateway.mjs', 'scripts/launcher-smoke.mjs', 'scripts/launcher-lifecycle-smoke.mjs', 'scripts/fixtures/test5-user-timeline.json']
for (const file of required) {
  if (!existsSync(resolve(root, file))) throw new Error('missing frontend file: ' + file)
}

const app = readFileSync(resolve(root, 'src/App.tsx'), 'utf8')
const gateway = readFileSync(resolve(root, 'src/api/gatewayClient.ts'), 'utf8')
const workspaceApi = readFileSync(resolve(root, 'src/api/workspace.ts'), 'utf8')
const gatewayTransport = readFileSync(resolve(root, 'src/api/gateway/transport.ts'), 'utf8')
const gatewayMappers = readFileSync(resolve(root, 'src/api/gateway/mappers.ts'), 'utf8')
const gatewayStream = readFileSync(resolve(root, 'src/api/gateway/runStream.ts'), 'utf8')
const evaluationResourceApi = readFileSync(resolve(root, 'src/api/gateway/evaluationResource.ts'), 'utf8')
const controller = readFileSync(resolve(root, 'src/domain/run/controller.ts'), 'utf8')
const domain = ['display', 'errors', 'measurement', 'records', 'review', 'run/timeline'].map((name) => readFileSync(resolve(root, 'src/domain/' + name + '.ts'), 'utf8')).join('\n')
const components = ['common', 'dialogs', 'evaluation', 'preview', 'run', 'workspace'].map((name) => readFileSync(resolve(root, 'src/components/' + name + '.tsx'), 'utf8')).join('\n') + readFileSync(resolve(root, 'src/components/types.ts'), 'utf8')
const runTypes = readFileSync(resolve(root, 'src/types/run.ts'), 'utf8')
const mockFixtures = readFileSync(resolve(root, 'src/api/mock/fixtures.ts'), 'utf8')
const stylesheet = ['global', 'tokens', 'foundation', 'workspace', 'evaluation', 'attachment-preview', 'dialogs', 'run', 'responsive'].map((name) => readFileSync(resolve(root, 'src/styles/' + name + '.css'), 'utf8')).join('\n')
const client = readFileSync(resolve(root, 'src/api/client.ts'), 'utf8')
const attachmentHelpers = readFileSync(resolve(root, 'src/attachments.ts'), 'utf8')
const runtime = readFileSync(resolve(root, 'src/runtime.ts'), 'utf8')
const previewResources = readFileSync(resolve(root, 'src/previewResources.ts'), 'utf8')
const mock = readFileSync(resolve(root, 'src/api/mockClient.ts'), 'utf8')
const launcher = readFileSync(resolve(root, 'scripts/dev-gateway.mjs'), 'utf8')
const tauriLauncher = readFileSync(resolve(root, 'scripts/tauri-dev-gateway.mjs'), 'utf8')
const tauriConfig = readFileSync(resolve(root, '../src-tauri/tauri.conf.json'), 'utf8')
const tauriEntrypoint = readFileSync(resolve(root, '../src-tauri/src/lib.rs'), 'utf8')
const tauriPackage = readFileSync(resolve(root, '../src-tauri/Cargo.toml'), 'utf8')
const gatewayServer = readFileSync(resolve(root, '../src/chartagent/gateway/server.py'), 'utf8')
const pythonPackage = readFileSync(resolve(root, '../pyproject.toml'), 'utf8')
const readme = readFileSync(resolve(root, '../README.md'), 'utf8')
const packageJson = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
const source = app + gateway + workspaceApi + gatewayTransport + gatewayMappers + gatewayStream + evaluationResourceApi + controller + domain + components + runTypes + mockFixtures + client + attachmentHelpers + stylesheet + runtime + previewResources + mock + launcher + tauriLauncher + tauriConfig + tauriEntrypoint + tauriPackage + gatewayServer + pythonPackage + readme
const checks = [['Figura brand', 'Figura'], ['Figura window title', 'productName": "Figura'], ['Figura Tauri runtime error', 'error while running Figura desktop client'], ['Figura Tauri package metadata', 'description = "Figura desktop client"'], ['Figura Python package metadata', 'description = "Figura - agentic foundation'], ['internal app identifier compatibility', 'com.chartagent.desktop'], ['internal Python command compatibility', 'python -m chartagent'], ['internal Gateway module compatibility', 'python -m chartagent.gateway'], ['internal environment compatibility', 'CHARTAGENT_'], ['session selection', 'onSelect'], ['new session action', 'onCreate'], ['session deletion', 'deleteSession'], ['session delete confirmation', '确认删除'], ['message submission', 'onSubmit'], ['live run start', 'startRun'], ['live event subscription', 'subscribeRun'], ['Gateway SSE', 'EventSource'], ['Gateway health', 'getHealth'], ['Agent readiness', 'agentState'], ['run state', 'runState'], ['execution details', 'aria-expanded'], ['attachment display', 'AttachmentPanel'], ['attachment picker', 'type="file"'], ['attachment upload', 'uploadAttachment'], ['attachment deletion', 'deleteAttachment'], ['attachment preview resource', 'attachments/${encodeURIComponent(attachmentId)}/content'], ['attachment IDs', 'attachmentIds'], ['visual observations', 'observationId'], ['local preview cleanup', 'revokeObjectURL'], ['client image validation', 'validateImageFile'], ['responsive layout', '@media'], ['gateway requests', 'fetch(gatewayBaseUrl'], ['explicit gateway mode', 'VITE_CHARTAGENT_MODE'], ['environment file contract', 'CHARTAGENT_ENV_FILE'], ['Gateway runtime command', 'gateway_status'], ['gateway errors', 'GatewayClientError'], ['unified Gateway launcher', 'condaExecutable'], ['launcher health gate', 'waitForHealth'], ['launcher cleanup', 'stopChild'], ['Tauri Gateway alias', 'gatewayTauriEnvironment']]
checks.push(['persisted execution history', 'getRunHistory'], ['run-level disclosure', 'RunTimeline'], ['call correlation', 'call_id'], ['cursor recovery', 'afterSequence'], ['history gap state', 'historyGap'], ['safe Markdown', 'SafeMarkdown'], ['answer source fallback', 'answer-source'], ['generated chart event', 'generated_chart'], ['generated artifact URL', 'generatedArtifactUrl'], ['generated chart preview', 'GeneratedChartView'], ['generated chart download', '下载 PNG'], ['provider selector', 'provider-selector'], ['provider request field', 'provider'], ['provider metadata', 'providerLabel'])
checks.push(['provider next-run disclosure', '当前运行不会切换来源'], ['provider session persistence', 'figura.provider.'])
checks.push(['DeepSeek provider label', 'DeepSeek（V4.1 Flash）'], ['DeepSeek model id', 'deepseek-flash'])
checks.push(['run idempotency key', 'Idempotency-Key'], ['run retry parent', 'retryOf'], ['run interruption API', 'interruptRun'], ['reconnect state', 'reconnecting'], ['cancel-request state', 'cancel_requested'], ['interrupted event', 'run_interrupted'])
checks.push(['measurement repair required event', 'measurement_repair_required'], ['measurement repair rejected event', 'measurement_repair_rejected'], ['measurement repair exhausted event', 'measurement_repair_exhausted'], ['measurement decision event', 'measurement_decision_required'], ['measurement focus event', 'measurement_focus_applied'], ['measurement evidence selection event', 'measurement_evidence_selected'], ['measurement evidence used event', 'measurement_evidence_used'], ['measurement repair event kinds', 'measurementRepairEventKinds'], ['measurement repair summary', 'measurementRepairSummary'], ['measurement repair required label', '等待同一面板内的定向补充'], ['measurement repair rejected label', '定向补充未被接受'], ['measurement repair exhausted label', '定向补充次数已用尽'], ['measurement decision diagnostic label', '已记录实际采用的测量证据'], ['measurement repair mock sample', 'run_mock_repair'], ['measurement repair replay merge', 'mergeEvents'], ['measurement repair reconnect', 'scheduleReconnect'])
checks.push(['explicit resume API', 'resumeRun'], ['resume action', '继续执行'], ['recovery status', 'recovery_blocked'], ['continuation lineage', 'continuationKind'], ['parent run lineage', 'parentRunId'])
checks.push(['run replay duplicate merge', 'mergeEvents'], ['run replay history compensation', 'onHistory(history)'], ['run replay realtime event', 'onEvent(event)'], ['run replay bounded reconnect', 'maxReconnectAttempts'], ['run replay terminal convergence', 'onTerminal(history)'], ['run replay cleanup', 'closeSubscription'])
checks.push(['single timeline node', 'TimelineNode'], ['decision timeline projector', 'projectDecisionTimeline'], ['user timeline projector', 'projectUserTimeline'], ['user timeline item type', 'UserTimelineItem'], ['strict timeline metadata', 'unit_id'], ['technical lifecycle filter', 'technicalTimelineEventKinds'], ['flat timeline component', 'user-timeline-item'], ['review subcheck grouping', 'review_subcheck'], ['decision timeline mock fixture', 'mockMeasurementUnit'], ['evaluation shared timeline view', 'showSummary={false}'])
checks.push(['structured failure context', 'failureContext'], ['failure category label', 'failureCategoryLabel'], ['failure field location', '字段：'], ['tool failure detail', 'traceEventDetail(item.result)'])
checks.push(['unified preview resource', 'PreviewResource'], ['preview HTTP validation', 'PREVIEW_IMAGE_TYPES'], ['preview blob cleanup', 'releasePreview'], ['preview retry state', 'preview_invalid_media'], ['runtime Gateway URL', 'configureGatewayBaseUrl'], ['Tauri preview origin', 'tauri.localhost'])
checks.push(['interactive preview controller', 'InteractivePreview'], ['preview trigger', 'preview-trigger'], ['preview dialog accessibility', 'aria-modal="true"'], ['preview focus trap', 'focusableElements'], ['preview Escape close', "event.key === 'Escape'"], ['preview zoom controls', 'setZoom'], ['preview fit control', '适应窗口'], ['preview attachment trigger', 'attachment-preview-trigger'], ['preview status metadata', 'statusLabel'], ['preview session cleanup', 'setActivePreview(null)'])
checks.push(['evaluation catalog API', "'/evaluations'"], ['evaluation case API', 'getEvaluationCase'], ['evaluation history API', 'getEvaluationHistory'], ['evaluation resource route', 'kind: \'evaluation\''], ['evaluation workspace switch', 'workspace-switcher'], ['evaluation independent state', 'activeEvaluationId'], ['evaluation stage timeline', 'evaluation-stage-list'], ['evaluation evidence gallery', 'evaluation-evidence-grid'], ['evaluation safe report', '评测工作台 · 只读'], ['evaluation polling', 'setInterval(() => {'])
checks.push(['evaluation detail API', 'getEvaluationHistoryDetails'], ['evaluation detail route', '/history/details'], ['evaluation detail DTO', 'EvaluationHistoryDetails'], ['evaluation conversation disclosure', '加载对话与补充记录'], ['evaluation detail truncation state', '本次补充记录受大小上限保护'], ['evaluation sensitive notice', 'props.details.notice'], ['evaluation detail preview mapping', 'mapEvaluationDetailEntry'])
checks.push(['workspace API façade', 'createWorkspaceApi'], ['style import façade', "@import './workspace.css'"], ['responsive style contract', '@media (max-width: 760px)'])
checks.push(['central error mapping', 'toUserMessage'])
for (const [label, token] of checks) {
  if (!source.includes(token)) throw new Error('missing UI contract: ' + label)
}
if (components.includes('DecisionUnitItem')) throw new Error('legacy timeline projection remains in the UI')
for (const script of ['dev:gateway', 'tauri:dev:gateway']) {
  if (typeof packageJson.scripts?.[script] !== 'string') throw new Error('missing package script: ' + script)
}
console.log('frontend smoke passed (' + checks.length + ' UI contracts)')
