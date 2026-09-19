import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { buildGatewayArgs, buildGatewayEnvironment, gatewayBaseUrl, isCompatibleHealth, readConfig } from './dev-gateway.mjs'
import { gatewayTauriEnvironment } from './tauri-dev-gateway.mjs'

const environment = {
  CHARTAGENT_GATEWAY_HOST: '127.0.0.1',
  CHARTAGENT_GATEWAY_PORT: '9876',
  CHARTAGENT_CONDA_ENV: 'agent',
  CHARTAGENT_GATEWAY_ORIGINS: 'http://localhost:1420',
  VITE_DEV_PORT: '1421',
  CHARTAGENT_DATA_DIR: '.chartagent-smoke',
}
const config = readConfig(environment)

assert.equal(config.condaEnvironment, 'agent')
assert.equal(gatewayBaseUrl(config), 'http://127.0.0.1:9876/api/v1')
assert.deepEqual(buildGatewayArgs(config), [
  'run', '-n', 'agent', 'python', '-m', 'chartagent.gateway',
  '--host', '127.0.0.1', '--port', '9876',
  '--data-dir', '.chartagent-smoke',
])
assert.equal(isCompatibleHealth({ version: 'v1', status: 'ok' }), true)
assert.equal(isCompatibleHealth({ version: 'v1', status: 'error' }), false)
const gatewayEnvironment = buildGatewayEnvironment(environment, config)
assert.match(gatewayEnvironment.CHARTAGENT_GATEWAY_ORIGINS, /127\.0\.0\.1:1421/)
assert.equal(gatewayEnvironment.CHARTAGENT_ENV_FILE, config.environmentFile)
assert.equal(gatewayEnvironment.CHARTAGENT_PROJECT_ROOT, config.projectRoot)
assert.equal(config.projectRoot, resolve(import.meta.dirname, '../..'))
assert.equal(config.frontendRoot, resolve(import.meta.dirname, '..'))
assert.equal(gatewayTauriEnvironment({ VITE_CHARTAGENT_MODE: 'mock' }).VITE_CHARTAGENT_MODE, 'gateway')
assert.equal(gatewayTauriEnvironment({}).CHARTAGENT_MODE, 'gateway')
assert.match(gatewayTauriEnvironment({}).CHARTAGENT_ENV_FILE, /\.env$/)

console.log('launcher smoke passed (configuration, health, environment, and process contracts)')
