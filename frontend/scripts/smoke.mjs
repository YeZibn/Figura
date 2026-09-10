import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const required = ['src/App.tsx', 'src/api/client.ts', 'src/api/mockClient.ts', 'src/api/gatewayClient.ts', 'src/types/protocol.ts', 'src/styles/global.css', 'index.html']
for (const file of required) {
  if (!existsSync(resolve(root, file))) throw new Error('missing frontend file: ' + file)
}

const app = readFileSync(resolve(root, 'src/App.tsx'), 'utf8')
const gateway = readFileSync(resolve(root, 'src/api/gatewayClient.ts'), 'utf8')
const stylesheet = readFileSync(resolve(root, 'src/styles/global.css'), 'utf8')
const client = readFileSync(resolve(root, 'src/api/client.ts'), 'utf8')
const attachmentHelpers = readFileSync(resolve(root, 'src/attachments.ts'), 'utf8')
const source = app + gateway + client + attachmentHelpers + stylesheet
const checks = [['session selection', 'onSelect'], ['new session action', 'onCreate'], ['message submission', 'onSubmit'], ['execution details', 'aria-expanded'], ['attachment display', 'AttachmentPanel'], ['attachment picker', 'type="file"'], ['attachment upload', 'uploadAttachment'], ['attachment IDs', 'attachmentIds'], ['local preview cleanup', 'revokeObjectURL'], ['client image validation', 'validateImageFile'], ['responsive layout', '@media'], ['gateway requests', 'fetch(gatewayBaseUrl'], ['explicit gateway mode', 'VITE_CHARTAGENT_MODE'], ['gateway errors', 'GatewayClientError']]
for (const [label, token] of checks) {
  if (!source.includes(token)) throw new Error('missing UI contract: ' + label)
}
console.log('frontend smoke passed (' + checks.length + ' UI contracts)')
