import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { buildGatewayArgs, buildGatewayEnvironment, gatewayBaseUrl, isCompatibleHealth, readConfig } from './dev-gateway.mjs'
import { buildClientEnvironment, buildGatewayArgs as buildFiguraGatewayArgs, buildGatewayEnvironment as buildFiguraGatewayEnvironment, gatewayBaseUrl as figuraGatewayBaseUrl, isFiguraHealth, readConfig as readFiguraConfig } from './dev-figura.mjs'
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

const figuraConfig = readFiguraConfig({
  FIGURA_GATEWAY_PORT: '9877',
  FIGURA_CONDA_ENV: 'agent',
  FIGURA_DATA_DIR: '.figura-smoke',
  VITE_DEV_PORT: '1422',
})
assert.equal(figuraGatewayBaseUrl(figuraConfig), 'http://127.0.0.1:9877/api/v1')
assert.deepEqual(buildFiguraGatewayArgs(figuraConfig), ['run', '-n', 'agent', 'python', '-m', 'figura.gateway'])
const figuraAllowedOrigins = buildFiguraGatewayEnvironment({}, figuraConfig).FIGURA_WEB_ORIGINS
assert.match(figuraAllowedOrigins, /127\.0\.0\.1:1422/)
assert.match(figuraAllowedOrigins, /localhost:1422/)
assert.match(figuraAllowedOrigins, /\[::1\]:1422/)
assert.equal(buildFiguraGatewayEnvironment({}, figuraConfig).FIGURA_DATA_DIR, '.figura-smoke')
assert.equal(isFiguraHealth({ version: 'v1', status: 'ok', service: 'figura' }), true)
assert.equal(isFiguraHealth({ version: 'v1', status: 'ok', service: 'chartagent' }), false)
const figuraClientEnvironment = buildClientEnvironment({
  FIGURA_QWEN_API_KEY: 'never-forward-this',
  FIGURA_QWEN_BASE_URL: 'https://provider.private.example',
  QWEN_API_KEY: 'also-private',
  QWEN_BASE_URL: 'https://legacy.private.example',
  VITE_FIGURA_QWEN_API_KEY: 'not-allowed',
  VITE_CHARTAGENT_MODE: 'gateway',
}, figuraConfig)
assert.equal(figuraClientEnvironment.FIGURA_QWEN_API_KEY, undefined)
assert.equal(figuraClientEnvironment.FIGURA_QWEN_BASE_URL, undefined)
assert.equal(figuraClientEnvironment.VITE_FIGURA_QWEN_API_KEY, undefined)
assert.equal(figuraClientEnvironment.VITE_CHARTAGENT_MODE, undefined)
assert.equal(figuraClientEnvironment.QWEN_API_KEY, undefined)
assert.equal(figuraClientEnvironment.QWEN_BASE_URL, undefined)
assert.equal(figuraClientEnvironment.VITE_FIGURA_MODE, 'true')
assert.equal(figuraClientEnvironment.VITE_FIGURA_GATEWAY_URL, figuraGatewayBaseUrl(figuraConfig))
assert.equal(figuraClientEnvironment.VITE_DEV_PORT, '1422')

console.log('launcher smoke passed (configuration, health, environment, and process contracts)')
