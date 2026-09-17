import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const required = ['src/App.tsx', 'src/api/client.ts', 'src/api/mockClient.ts', 'src/api/gatewayClient.ts', 'src/types/protocol.ts', 'src/runtime.ts', 'src/previewResources.ts', 'src/styles/global.css', 'index.html', 'scripts/dev-gateway.mjs', 'scripts/tauri-dev-gateway.mjs', 'scripts/launcher-smoke.mjs', 'scripts/launcher-lifecycle-smoke.mjs']
for (const file of required) {
  if (!existsSync(resolve(root, file))) throw new Error('missing frontend file: ' + file)
}

const app = readFileSync(resolve(root, 'src/App.tsx'), 'utf8')
const gateway = readFileSync(resolve(root, 'src/api/gatewayClient.ts'), 'utf8')
const stylesheet = readFileSync(resolve(root, 'src/styles/global.css'), 'utf8')
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
const source = app + gateway + client + attachmentHelpers + stylesheet + runtime + previewResources + mock + launcher + tauriLauncher + tauriConfig + tauriEntrypoint + tauriPackage + gatewayServer + pythonPackage + readme
const checks = [['Figura brand', 'Figura'], ['Figura window title', 'productName": "Figura'], ['Figura Tauri runtime error', 'error while running Figura desktop client'], ['Figura Tauri package metadata', 'description = "Figura desktop client"'], ['Figura Python package metadata', 'description = "Figura - agentic foundation'], ['internal app identifier compatibility', 'com.chartagent.desktop'], ['internal Python command compatibility', 'python -m chartagent'], ['internal Gateway module compatibility', 'python -m chartagent.gateway'], ['internal environment compatibility', 'CHARTAGENT_'], ['session selection', 'onSelect'], ['new session action', 'onCreate'], ['session deletion', 'deleteSession'], ['session delete confirmation', '确认删除'], ['message submission', 'onSubmit'], ['live run start', 'startRun'], ['live event subscription', 'subscribeRun'], ['Gateway SSE', 'EventSource'], ['Gateway health', 'getHealth'], ['Agent readiness', 'agentState'], ['run state', 'runState'], ['execution details', 'aria-expanded'], ['attachment display', 'AttachmentPanel'], ['attachment picker', 'type="file"'], ['attachment upload', 'uploadAttachment'], ['attachment deletion', 'deleteAttachment'], ['attachment preview resource', 'attachments/${encodeURIComponent(attachmentId)}/content'], ['attachment IDs', 'attachmentIds'], ['visual observations', 'observationId'], ['local preview cleanup', 'revokeObjectURL'], ['client image validation', 'validateImageFile'], ['responsive layout', '@media'], ['gateway requests', 'fetch(gatewayBaseUrl'], ['explicit gateway mode', 'VITE_CHARTAGENT_MODE'], ['environment file contract', 'CHARTAGENT_ENV_FILE'], ['Gateway runtime command', 'gateway_status'], ['gateway errors', 'GatewayClientError'], ['unified Gateway launcher', 'condaExecutable'], ['launcher health gate', 'waitForHealth'], ['launcher cleanup', 'stopChild'], ['Tauri Gateway alias', 'gatewayTauriEnvironment']]
checks.push(['persisted execution history', 'getRunHistory'], ['run-level disclosure', 'RunTimeline'], ['call correlation', 'call_id'], ['cursor recovery', 'afterSequence'], ['history gap state', 'historyGap'], ['safe Markdown', 'SafeMarkdown'], ['answer source fallback', 'answer-source'], ['generated chart event', 'generated_chart'], ['generated artifact URL', 'generatedArtifactUrl'], ['generated chart preview', 'GeneratedChartView'], ['generated chart download', '下载 PNG'], ['provider selector', 'provider-selector'], ['provider request field', 'provider'], ['provider metadata', 'providerLabel'])
checks.push(['provider next-run disclosure', '当前运行不会切换来源'], ['provider session persistence', 'figura.provider.'])
checks.push(['run idempotency key', 'Idempotency-Key'], ['run retry parent', 'retryOf'], ['run interruption API', 'interruptRun'], ['reconnect state', 'reconnecting'], ['cancel-request state', 'cancel_requested'], ['interrupted event', 'run_interrupted'])
checks.push(['unified preview resource', 'PreviewResource'], ['preview HTTP validation', 'PREVIEW_IMAGE_TYPES'], ['preview blob cleanup', 'releasePreview'], ['preview retry state', 'preview_invalid_media'], ['runtime Gateway URL', 'configureGatewayBaseUrl'], ['Tauri preview origin', 'tauri.localhost'])
checks.push(['interactive preview controller', 'InteractivePreview'], ['preview trigger', 'preview-trigger'], ['preview dialog accessibility', 'aria-modal="true"'], ['preview focus trap', 'focusableElements'], ['preview Escape close', "event.key === 'Escape'"], ['preview zoom controls', 'setZoom'], ['preview fit control', '适应窗口'], ['preview attachment trigger', 'attachment-preview-trigger'], ['preview status metadata', 'statusLabel'], ['preview session cleanup', 'setActivePreview(null)'])
for (const [label, token] of checks) {
  if (!source.includes(token)) throw new Error('missing UI contract: ' + label)
}
for (const script of ['dev:gateway', 'tauri:dev:gateway']) {
  if (typeof packageJson.scripts?.[script] !== 'string') throw new Error('missing package script: ' + script)
}
console.log('frontend smoke passed (' + checks.length + ' UI contracts)')
