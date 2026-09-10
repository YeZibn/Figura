import { spawn } from 'node:child_process'
import { pathToFileURL } from 'node:url'
import process from 'node:process'

const DEFAULT_GATEWAY_HOST = '127.0.0.1'
const DEFAULT_GATEWAY_PORT = 8765
const DEFAULT_FRONTEND_HOST = '127.0.0.1'
const DEFAULT_FRONTEND_PORT = 1420
const DEFAULT_STARTUP_TIMEOUT_MS = 15000
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 2000

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))

function numericEnv(environment, name, fallback, minimum, maximum) {
  const value = Number.parseInt(environment[name] || '', 10)
  return Number.isFinite(value) ? Math.min(Math.max(value, minimum), maximum) : fallback
}

export function readConfig(environment = process.env) {
  const gatewayHost = environment.CHARTAGENT_GATEWAY_HOST || DEFAULT_GATEWAY_HOST
  const gatewayPort = numericEnv(environment, 'CHARTAGENT_GATEWAY_PORT', DEFAULT_GATEWAY_PORT, 1, 65535)
  const frontendHost = environment.VITE_DEV_HOST || DEFAULT_FRONTEND_HOST
  const frontendPort = numericEnv(environment, 'VITE_DEV_PORT', DEFAULT_FRONTEND_PORT, 1, 65535)
  const startupTimeout = numericEnv(environment, 'CHARTAGENT_GATEWAY_STARTUP_MS', DEFAULT_STARTUP_TIMEOUT_MS, 1000, 60000)
  const shutdownTimeout = numericEnv(environment, 'CHARTAGENT_GATEWAY_SHUTDOWN_MS', DEFAULT_SHUTDOWN_TIMEOUT_MS, 100, 10000)
  const condaEnvironment = environment.CHARTAGENT_CONDA_ENV || 'agent'
  const condaExecutable = environment.CHARTAGENT_CONDA_EXECUTABLE || 'conda'
  return { gatewayHost, gatewayPort, frontendHost, frontendPort, startupTimeout, shutdownTimeout, condaEnvironment, condaExecutable }
}

export function buildGatewayArgs(config) {
  return [
    'run',
    '-n',
    config.condaEnvironment,
    'python',
    '-m',
    'chartagent.gateway',
    '--host',
    config.gatewayHost,
    '--port',
    String(config.gatewayPort),
  ]
}

export function gatewayBaseUrl(config) {
  return `http://${config.gatewayHost}:${config.gatewayPort}/api/v1`
}

export function isCompatibleHealth(payload) {
  return payload?.version === 'v1' && payload?.status === 'ok'
}

export function buildGatewayEnvironment(environment, config) {
  const gatewayOrigin = `http://${config.frontendHost}:${config.frontendPort}`
  const configuredOrigins = (environment.CHARTAGENT_GATEWAY_ORIGINS || '')
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean)
  const origins = [...new Set([...configuredOrigins, gatewayOrigin])]
  return {
    ...environment,
    CHARTAGENT_GATEWAY_ORIGINS: origins.join(','),
  }
}

function spawnOptions(environment) {
  return {
    env: environment,
    stdio: 'inherit',
    detached: process.platform !== 'win32',
  }
}

function npmExecutable() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm'
}

function processGroupAlive(child) {
  if (!child || !child.pid) return child && child.exitCode === null && child.signalCode === null
  if (process.platform === 'win32') return child.exitCode === null && child.signalCode === null
  try {
    process.kill(-child.pid, 0)
    return true
  } catch {
    return false
  }
}

function waitForExit(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child?.exitCode ?? 1, signal: child?.signalCode ?? null })
  }
  return new Promise((resolve) => {
    child.once('error', (error) => resolve({ code: 1, signal: null, error }))
    child.once('exit', (code, signal) => resolve({ code, signal }))
  })
}

async function stopChild(child, timeout) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  const exit = waitForExit(child)
  try {
    if (process.platform === 'win32' || !child.pid) child.kill('SIGTERM')
    else process.kill(-child.pid, 'SIGTERM')
  } catch {
    return
  }
  const finished = await Promise.race([exit, sleep(timeout).then(() => null)])
  if (finished && !processGroupAlive(child)) return
  if (!processGroupAlive(child)) return
  try {
    if (process.platform === 'win32' || !child.pid) child.kill('SIGKILL')
    else process.kill(-child.pid, 'SIGKILL')
  } catch {
    // The child may have exited between the status check and the kill call.
  }
  const deadline = Date.now() + timeout
  while (processGroupAlive(child) && Date.now() < deadline) await sleep(25)
}

async function waitForHealth(config, gatewayProcess) {
  const healthUrl = `${gatewayBaseUrl(config)}/health`
  const deadline = Date.now() + config.startupTimeout
  let lastError = 'no compatible health response'
  while (Date.now() < deadline) {
    if (gatewayProcess.spawnError) {
      throw new Error(`Gateway could not be started: ${gatewayProcess.spawnError.message}`)
    }
    if (gatewayProcess.exitCode !== null || gatewayProcess.signalCode !== null) {
      throw new Error('Gateway process exited before becoming ready')
    }
    try {
      const response = await fetch(healthUrl)
      const payload = await response.json()
      if (response.ok && isCompatibleHealth(payload)) return
      lastError = `Gateway health returned HTTP ${response.status}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : 'health request failed'
    }
    await sleep(100)
  }
  throw new Error(`Gateway did not become ready within ${config.startupTimeout}ms: ${lastError}`)
}

export async function run(environment = process.env) {
  const config = readConfig(environment)
  const gatewayEnvironment = buildGatewayEnvironment(environment, config)
  const clientEnvironment = {
    ...gatewayEnvironment,
    VITE_CHARTAGENT_MODE: 'gateway',
    VITE_CHARTAGENT_GATEWAY_URL: gatewayBaseUrl(config),
  }
  let gatewayProcess
  let clientProcess
  let stopping = false

  const cleanup = async () => {
    if (stopping) return
    stopping = true
    await stopChild(clientProcess, config.shutdownTimeout)
    await stopChild(gatewayProcess, config.shutdownTimeout)
  }

  const handleSignal = async (signal) => {
    console.log(`Received ${signal}; stopping local ChartAgent services.`)
    await cleanup()
    process.exitCode = 130
  }
  process.once('SIGINT', handleSignal)
  process.once('SIGTERM', handleSignal)

  try {
    gatewayProcess = spawn(config.condaExecutable, buildGatewayArgs(config), spawnOptions(gatewayEnvironment))
    gatewayProcess.once('error', (error) => { gatewayProcess.spawnError = error })
    await waitForHealth(config, gatewayProcess)
    console.log(`Gateway ready at ${gatewayBaseUrl(config)}`)

    clientProcess = spawn(
      npmExecutable(),
      ['run', 'dev', '--', '--host', config.frontendHost, '--port', String(config.frontendPort)],
      spawnOptions(clientEnvironment),
    )
    clientProcess.once('error', () => {})
    const firstExit = await Promise.race([
      waitForExit(clientProcess).then((result) => ({ owner: 'client', result })),
      waitForExit(gatewayProcess).then((result) => ({ owner: 'gateway', result })),
    ])
    if (firstExit.owner === 'gateway') {
      console.error('Gateway stopped while the frontend was running.')
      return 1
    }
    return firstExit.result.code ?? 0
  } catch (error) {
    console.error(`Unable to start Gateway development mode: ${error instanceof Error ? error.message : String(error)}`)
    return 1
  } finally {
    await cleanup()
    process.removeListener('SIGINT', handleSignal)
    process.removeListener('SIGTERM', handleSignal)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run().then((code) => {
    process.exitCode = code
  })
}
