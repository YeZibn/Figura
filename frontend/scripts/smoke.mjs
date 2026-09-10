import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const required = ['src/App.tsx', 'src/api/client.ts', 'src/api/mockClient.ts', 'src/api/gatewayClient.ts', 'src/types/protocol.ts', 'src/runtime.ts', 'src/styles/global.css', 'index.html', 'scripts/dev-gateway.mjs', 'scripts/tauri-dev-gateway.mjs', 'scripts/launcher-smoke.mjs', 'scripts/launcher-lifecycle-smoke.mjs']
for (const file of required) {
  if (!existsSync(resolve(root, file))) throw new Error('missing frontend file: ' + file)
}

const app = readFileSync(resolve(root, 'src/App.tsx'), 'utf8')
const gateway = readFileSync(resolve(root, 'src/api/gatewayClient.ts'), 'utf8')
const stylesheet = readFileSync(resolve(root, 'src/styles/global.css'), 'utf8')
const client = readFileSync(resolve(root, 'src/api/client.ts'), 'utf8')
const attachmentHelpers = readFileSync(resolve(root, 'src/attachments.ts'), 'utf8')
const runtime = readFileSync(resolve(root, 'src/runtime.ts'), 'utf8')
const mock = readFileSync(resolve(root, 'src/api/mockClient.ts'), 'utf8')
const launcher = readFileSync(resolve(root, 'scripts/dev-gateway.mjs'), 'utf8')
const tauriLauncher = readFileSync(resolve(root, 'scripts/tauri-dev-gateway.mjs'), 'utf8')
const packageJson = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
const source = app + gateway + client + attachmentHelpers + stylesheet + runtime + mock + launcher + tauriLauncher
const checks = [['session selection', 'onSelect'], ['new session action', 'onCreate'], ['message submission', 'onSubmit'], ['live run start', 'startRun'], ['live event subscription', 'subscribeRun'], ['Gateway SSE', 'EventSource'], ['Gateway health', 'getHealth'], ['Agent readiness', 'agentState'], ['run state', 'runState'], ['execution details', 'aria-expanded'], ['attachment display', 'AttachmentPanel'], ['attachment picker', 'type="file"'], ['attachment upload', 'uploadAttachment'], ['attachment IDs', 'attachmentIds'], ['visual observations', 'observationId'], ['local preview cleanup', 'revokeObjectURL'], ['client image validation', 'validateImageFile'], ['responsive layout', '@media'], ['gateway requests', 'fetch(gatewayBaseUrl'], ['explicit gateway mode', 'VITE_CHARTAGENT_MODE'], ['environment file contract', 'CHARTAGENT_ENV_FILE'], ['Gateway runtime command', 'gateway_status'], ['gateway errors', 'GatewayClientError'], ['unified Gateway launcher', 'condaExecutable'], ['launcher health gate', 'waitForHealth'], ['launcher cleanup', 'stopChild'], ['Tauri Gateway alias', 'gatewayTauriEnvironment']]
for (const [label, token] of checks) {
  if (!source.includes(token)) throw new Error('missing UI contract: ' + label)
}
for (const script of ['dev:gateway', 'tauri:dev:gateway']) {
  if (typeof packageJson.scripts?.[script] !== 'string') throw new Error('missing package script: ' + script)
}
console.log('frontend smoke passed (' + checks.length + ' UI contracts)')
