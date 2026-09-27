import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import process from 'node:process'
import net from 'node:net'

const root = resolve(import.meta.dirname, '..')
const npmExecutable = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const sleep = (milliseconds) => new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds))

async function findFreePort() {
  const server = net.createServer()
  await new Promise((resolveListen, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolveListen)
  })
  const address = server.address()
  const port = typeof address === 'object' && address ? address.port : null
  await new Promise((resolveClose) => server.close(resolveClose))
  if (!port) throw new Error('could not allocate a free port')
  return port
}

function portAcceptsConnections(port) {
  return new Promise((resolveConnection) => {
    const socket = net.createConnection({ host: '127.0.0.1', port })
    const finish = (available) => {
      socket.destroy()
      resolveConnection(available)
    }
    socket.once('connect', () => finish(true))
    socket.once('error', () => finish(false))
    socket.setTimeout(500, () => finish(false))
  })
}

async function waitFor(predicate, description, timeout = 20000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await predicate()) return
    await sleep(100)
  }
  throw new Error(`Timed out waiting for ${description}`)
}

function startLauncher(frontendPort, gatewayPort) {
  let output = ''
  const child = spawn(npmExecutable, ['run', 'dev:gateway'], {
    cwd: root,
    env: {
      ...process.env,
      VITE_DEV_PORT: String(frontendPort),
      CHARTAGENT_GATEWAY_PORT: String(gatewayPort),
      CHARTAGENT_GATEWAY_STARTUP_MS: '10000',
      CHARTAGENT_GATEWAY_SHUTDOWN_MS: '1000',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: process.platform !== 'win32',
  })
  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.stdout.on('data', (chunk) => { output += chunk })
  child.stderr.on('data', (chunk) => { output += chunk })
  return { child, getOutput: () => output }
}

function signalLauncher(child, signal) {
  if (child.exitCode !== null || child.signalCode !== null) return
  if (process.platform === 'win32') child.kill(signal)
  else process.kill(-child.pid, signal)
}

function forceStopLauncher(child) {
  if (child.exitCode !== null || child.signalCode !== null) return
  try {
    if (process.platform === 'win32') child.kill('SIGKILL')
    else process.kill(-child.pid, 'SIGKILL')
  } catch {
    // The launcher may have exited while the test was cleaning up.
  }
}

async function waitForLauncherExit(child, description) {
  await waitFor(() => child.exitCode !== null || child.signalCode !== null, description)
}

async function waitForGatewayAndFrontend(frontendPort, gatewayPort, launcher) {
  await waitFor(async () => {
    if (launcher.child.exitCode !== null || launcher.child.signalCode !== null) return false
    try {
      const health = await fetch(`http://127.0.0.1:${gatewayPort}/api/v1/health`)
      const frontend = await fetch(`http://127.0.0.1:${frontendPort}/`)
      return health.ok && frontend.ok
    } catch {
      return false
    }
  }, 'Gateway and Vite readiness')
}

async function runSignalScenario(signal) {
  const frontendPort = await findFreePort()
  const gatewayPort = await findFreePort()
  const launcher = startLauncher(frontendPort, gatewayPort)
  try {
    await waitForGatewayAndFrontend(frontendPort, gatewayPort, launcher)
    signalLauncher(launcher.child, signal)
    await waitForLauncherExit(launcher.child, `${signal} launcher exit`)
    await waitFor(async () => !(await portAcceptsConnections(frontendPort)), `${signal} frontend port release`)
    await waitFor(async () => !(await portAcceptsConnections(gatewayPort)), `${signal} Gateway port release`)
  } catch (error) {
    throw new Error(`${signal} scenario failed: ${error instanceof Error ? error.message : String(error)}\n${launcher.getOutput()}`)
  } finally {
    forceStopLauncher(launcher.child)
  }
}

async function runFrontendConflictScenario() {
  const frontendPort = await findFreePort()
  const gatewayPort = await findFreePort()
  const external = createServer((_request, response) => response.end('external listener'))
  await new Promise((resolveListen, reject) => {
    external.once('error', reject)
    external.listen(frontendPort, '127.0.0.1', resolveListen)
  })
  const launcher = startLauncher(frontendPort, gatewayPort)
  try {
    await waitForLauncherExit(launcher.child, 'frontend conflict launcher exit')
    assert.equal(await portAcceptsConnections(frontendPort), true, 'the unrelated frontend listener must remain alive')
    await waitFor(async () => !(await portAcceptsConnections(gatewayPort)), 'Gateway cleanup after frontend conflict')
    const response = await fetch(`http://127.0.0.1:${frontendPort}/`)
    assert.equal(await response.text(), 'external listener')
  } finally {
    forceStopLauncher(launcher.child)
    await new Promise((resolveClose) => external.close(resolveClose))
  }
}

function startFiguraLauncher(frontendPort, gatewayPort, dataDir, environment = {}) {
  let output = ''
  const child = spawn(npmExecutable, ['run', 'dev:figura'], {
    cwd: root,
    env: {
      ...process.env,
      ...environment,
      VITE_DEV_PORT: String(frontendPort),
      FIGURA_GATEWAY_PORT: String(gatewayPort),
      FIGURA_GATEWAY_STARTUP_MS: '10000',
      FIGURA_GATEWAY_SHUTDOWN_MS: '1000',
      FIGURA_DATA_DIR: dataDir,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: process.platform !== 'win32',
  })
  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.stdout.on('data', (chunk) => { output += chunk })
  child.stderr.on('data', (chunk) => { output += chunk })
  return { child, getOutput: () => output }
}

async function waitForFiguraReady(frontendPort, gatewayPort, launcher) {
  await waitFor(async () => {
    if (launcher.child.exitCode !== null || launcher.child.signalCode !== null) return false
    try {
      const healthResponse = await fetch(`http://127.0.0.1:${gatewayPort}/api/v1/health`)
      const health = await healthResponse.json()
      const frontendResponse = await fetch(`http://127.0.0.1:${frontendPort}/`)
      return healthResponse.ok && health.service === 'figura' && frontendResponse.ok
    } catch {
      return false
    }
  }, 'Figura Gateway and Vite readiness')
}

async function runFiguraSignalScenario(signal) {
  const frontendPort = await findFreePort()
  const gatewayPort = await findFreePort()
  const dataDir = await mkdtemp(join(tmpdir(), 'figura-web-smoke-'))
  const launcher = startFiguraLauncher(frontendPort, gatewayPort, dataDir)
  try {
    await waitForFiguraReady(frontendPort, gatewayPort, launcher)
    signalLauncher(launcher.child, signal)
    await waitForLauncherExit(launcher.child, `Figura ${signal} launcher exit`)
    await waitFor(async () => !(await portAcceptsConnections(frontendPort)), `Figura ${signal} frontend port release`)
    await waitFor(async () => !(await portAcceptsConnections(gatewayPort)), `Figura ${signal} Gateway port release`)
  } catch (error) {
    throw new Error(`Figura ${signal} scenario failed: ${error instanceof Error ? error.message : String(error)}\n${launcher.getOutput()}`)
  } finally {
    forceStopLauncher(launcher.child)
    await rm(dataDir, { recursive: true, force: true })
  }
}

async function runFiguraFrontendConflictScenario() {
  const frontendPort = await findFreePort()
  const gatewayPort = await findFreePort()
  const dataDir = await mkdtemp(join(tmpdir(), 'figura-web-smoke-'))
  const external = createServer((_request, response) => response.end('external listener'))
  await new Promise((resolveListen, reject) => {
    external.once('error', reject)
    external.listen(frontendPort, '127.0.0.1', resolveListen)
  })
  const launcher = startFiguraLauncher(frontendPort, gatewayPort, dataDir)
  try {
    await waitForLauncherExit(launcher.child, 'Figura frontend conflict launcher exit')
    assert.equal(await portAcceptsConnections(frontendPort), true, 'the unrelated Vite listener must remain alive')
    await waitFor(async () => !(await portAcceptsConnections(gatewayPort)), 'Figura Gateway cleanup after Vite conflict')
    const response = await fetch(`http://127.0.0.1:${frontendPort}/`)
    assert.equal(await response.text(), 'external listener')
  } finally {
    forceStopLauncher(launcher.child)
    await new Promise((resolveClose) => external.close(resolveClose))
    await rm(dataDir, { recursive: true, force: true })
  }
}

async function runFiguraGatewayStartupFailureScenario() {
  const frontendPort = await findFreePort()
  const gatewayPort = await findFreePort()
  const dataDir = await mkdtemp(join(tmpdir(), 'figura-web-smoke-'))
  const external = createServer((_request, response) => {
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({ version: 'v1', status: 'ok', service: 'not-figura' }))
  })
  await new Promise((resolveListen, reject) => {
    external.once('error', reject)
    external.listen(gatewayPort, '127.0.0.1', resolveListen)
  })
  const launcher = startFiguraLauncher(frontendPort, gatewayPort, dataDir, { FIGURA_GATEWAY_STARTUP_MS: '2500' })
  try {
    await waitForLauncherExit(launcher.child, 'Figura Gateway startup failure exit')
    assert.equal(await portAcceptsConnections(frontendPort), false, 'Vite must not start before Figura health succeeds')
    assert.equal(await portAcceptsConnections(gatewayPort), true, 'the unrelated Gateway listener must remain alive')
    assert.match(launcher.getOutput(), /exited before becoming ready|did not become ready/)
  } finally {
    forceStopLauncher(launcher.child)
    await new Promise((resolveClose) => external.close(resolveClose))
    await rm(dataDir, { recursive: true, force: true })
  }
}

await runSignalScenario('SIGINT')
await runSignalScenario('SIGTERM')
await runFrontendConflictScenario()
await runFiguraSignalScenario('SIGINT')
await runFiguraSignalScenario('SIGTERM')
await runFiguraFrontendConflictScenario()
await runFiguraGatewayStartupFailureScenario()
console.log('launcher lifecycle smoke passed (ChartAgent and Figura readiness, failure, signal cleanup, port release, and ownership)')
