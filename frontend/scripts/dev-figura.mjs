import { spawn } from 'node:child_process'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import process from 'node:process'

const DEFAULT_GATEWAY_PORT = 8766
const DEFAULT_FRONTEND_PORT = 1421
const DEFAULT_HOST = '127.0.0.1'
const DEFAULT_STARTUP_TIMEOUT_MS = 15000
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 2000
const PROJECT_ROOT = resolve(import.meta.dirname, '../..')
const FRONTEND_ROOT = resolve(import.meta.dirname, '..')
const sleep = (milliseconds) => new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds))

function portValue(environment, name, fallback) {
  const raw = environment[name]
  if (raw === undefined || raw === '') return fallback
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535`)
  }
  return value
}

function timeoutValue(environment, name, fallback, minimum, maximum) {
  const value = Number(environment[name] || fallback)
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} is outside its supported range`)
  }
  return value
}

function localHost(value, name) {
  const host = value || DEFAULT_HOST
  if (!['127.0.0.1', 'localhost', '::1'].includes(host)) {
    throw new Error(`${name} must be a loopback host`)
  }
  return host
}

export function readConfig(environment = process.env) {
  const gatewayPort = portValue(environment, 'FIGURA_GATEWAY_PORT', DEFAULT_GATEWAY_PORT)
  const frontendPort = portValue(environment, 'VITE_DEV_PORT', DEFAULT_FRONTEND_PORT)
  const gatewayHost = '127.0.0.1'
  const frontendHost = localHost(environment.VITE_DEV_HOST, 'VITE_DEV_HOST')
  const origins = (environment.FIGURA_WEB_ORIGINS || '').split(',').map((item) => item.trim()).filter(Boolean)
  const formattedHost = frontendHost === '::1' ? '[::1]' : frontendHost
  const frontendOrigin = `http://${formattedHost}:${frontendPort}`
  const loopbackHosts = ['127.0.0.1', 'localhost', '[::1]']
  const frontendOrigins = loopbackHosts.map((host) => `http://${host}:${frontendPort}`)
  const configuredOrigins = [...new Set([...origins, ...frontendOrigins])]
  if (configuredOrigins.some((origin) => !/^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):\d+$/.test(origin))) {
    throw new Error('FIGURA_WEB_ORIGINS accepts only explicit loopback HTTP Origins')
  }
  return {
    gatewayHost,
    gatewayPort,
    frontendHost,
    frontendPort,
    frontendOrigin,
    allowedOrigins: configuredOrigins.join(','),
    startupTimeout: timeoutValue(environment, 'FIGURA_GATEWAY_STARTUP_MS', DEFAULT_STARTUP_TIMEOUT_MS, 1000, 60000),
    shutdownTimeout: timeoutValue(environment, 'FIGURA_GATEWAY_SHUTDOWN_MS', DEFAULT_SHUTDOWN_TIMEOUT_MS, 100, 10000),
    condaEnvironment: environment.FIGURA_CONDA_ENV || 'agent',
    condaExecutable: environment.FIGURA_CONDA_EXECUTABLE || 'conda',
    dataDir: environment.FIGURA_DATA_DIR || null,
    projectRoot: PROJECT_ROOT,
    frontendRoot: FRONTEND_ROOT,
  }
}

export function buildGatewayArgs(config) {
  return ['run', '-n', config.condaEnvironment, 'python', '-m', 'figura.gateway']
}

export function gatewayBaseUrl(config) {
  return `http://${config.gatewayHost}:${config.gatewayPort}/api/v1`
}

export function buildGatewayEnvironment(environment, config) {
  const gatewayEnvironment = {
    ...environment,
    FIGURA_GATEWAY_PORT: String(config.gatewayPort),
    FIGURA_WEB_ORIGINS: config.allowedOrigins,
  }
  if (config.dataDir) gatewayEnvironment.FIGURA_DATA_DIR = config.dataDir
  return gatewayEnvironment
}

export function buildClientEnvironment(environment, config) {
  const inherited = Object.fromEntries(
    Object.entries(environment).filter(([name]) => (
      !name.startsWith('VITE_')
      && !name.startsWith('FIGURA_')
      && !/(?:_API_KEY|_BASE_URL)$/.test(name)
    )),
  )
  return {
    ...inherited,
    VITE_FIGURA_MODE: 'true',
    VITE_FIGURA_GATEWAY_URL: gatewayBaseUrl(config),
    VITE_DEV_HOST: config.frontendHost,
    VITE_DEV_PORT: String(config.frontendPort),
  }
}

export function isFiguraHealth(payload) {
  return payload?.version === 'v1' && payload?.status === 'ok' && payload?.service === 'figura'
}

function npmExecutable() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm'
}

function spawnOptions(environment, cwd) {
  return {
    env: environment,
    cwd,
    stdio: 'inherit',
    detached: process.platform !== 'win32',
  }
}

function processGroupAlive(child) {
  if (!child?.pid) return false
  if (process.platform === 'win32') return child.exitCode === null && child.signalCode === null
  try {
    process.kill(-child.pid, 0)
    return true
  } catch {
    return false
  }
}

function signalChild(child, signal) {
  if (!child?.pid) return false
  try {
    if (process.platform === 'win32') child.kill(signal)
    else process.kill(-child.pid, signal)
    return true
  } catch {
    return false
  }
}

function waitForExit(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child?.exitCode ?? 1, signal: child?.signalCode ?? null })
  }
  return new Promise((resolveExit) => {
    child.once('error', (error) => resolveExit({ code: 1, signal: null, error }))
    child.once('exit', (code, signal) => resolveExit({ code, signal }))
  })
}

async function stopChild(child, timeout, label) {
  if (!child?.pid) return true
  const exit = waitForExit(child)
  signalChild(child, 'SIGTERM')
  if (!processGroupAlive(child)) return true
  const finished = await Promise.race([exit, sleep(timeout).then(() => null)])
  if (finished && !processGroupAlive(child)) return true
  if (!processGroupAlive(child)) return true
  signalChild(child, 'SIGKILL')
  const deadline = Date.now() + timeout
  while (processGroupAlive(child) && Date.now() < deadline) await sleep(25)
  if (processGroupAlive(child)) {
    console.error(`${label} process group did not stop within ${timeout * 2}ms.`)
    return false
  }
  return true
}

async function waitForHealth(config, gatewayProcess) {
  const healthUrl = `${gatewayBaseUrl(config)}/health`
  const deadline = Date.now() + config.startupTimeout
  let lastError = 'no compatible health response'
  while (Date.now() < deadline) {
    if (gatewayProcess.spawnError) throw new Error(`Figura Gateway could not start: ${gatewayProcess.spawnError.message}`)
    if (gatewayProcess.exitCode !== null || gatewayProcess.signalCode !== null) {
      throw new Error('Figura Gateway exited before becoming ready')
    }
    try {
      const response = await fetch(healthUrl)
      const payload = await response.json()
      if (response.ok && isFiguraHealth(payload)) return
      lastError = `Gateway health returned HTTP ${response.status}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : 'health request failed'
    }
    await sleep(100)
  }
  throw new Error(`Figura Gateway did not become ready within ${config.startupTimeout}ms: ${lastError}`)
}

export async function run(environment = process.env) {
  const config = readConfig(environment)
  const gatewayEnvironment = buildGatewayEnvironment(environment, config)
  const clientEnvironment = buildClientEnvironment(environment, config)
  let gatewayProcess
  let clientProcess
  let cleanupPromise

  const cleanup = async () => {
    if (cleanupPromise) return cleanupPromise
    cleanupPromise = Promise.all([
      stopChild(clientProcess, config.shutdownTimeout, 'Vite'),
      stopChild(gatewayProcess, config.shutdownTimeout, 'Figura Gateway'),
    ]).then((results) => results.every(Boolean))
    return cleanupPromise
  }

  const handleSignal = async (signal) => {
    console.log(`Received ${signal}; stopping Figura web processes.`)
    await cleanup()
    process.exitCode = signal === 'SIGTERM' ? 143 : 130
  }
  process.on('SIGINT', handleSignal)
  process.on('SIGTERM', handleSignal)

  try {
    gatewayProcess = spawn(config.condaExecutable, buildGatewayArgs(config), spawnOptions(gatewayEnvironment, config.projectRoot))
    gatewayProcess.once('error', (error) => { gatewayProcess.spawnError = error })
    await waitForHealth(config, gatewayProcess)
    console.log(`Figura Gateway ready at ${gatewayBaseUrl(config)}`)

    clientProcess = spawn(
      npmExecutable(),
      ['run', 'dev', '--', '--host', config.frontendHost, '--port', String(config.frontendPort)],
      spawnOptions(clientEnvironment, config.frontendRoot),
    )
    clientProcess.once('error', () => {})
    const firstExit = await Promise.race([
      waitForExit(clientProcess).then((result) => ({ owner: 'frontend', result })),
      waitForExit(gatewayProcess).then((result) => ({ owner: 'gateway', result })),
    ])
    if (firstExit.owner === 'gateway') {
      console.error('Figura Gateway stopped while Vite was running.')
      return 1
    }
    return firstExit.result.code ?? 0
  } catch (error) {
    console.error(`Unable to start Figura web mode: ${error instanceof Error ? error.message : String(error)}`)
    return 1
  } finally {
    await cleanup()
    process.removeListener('SIGINT', handleSignal)
    process.removeListener('SIGTERM', handleSignal)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run().then((code) => { process.exitCode = code })
}
