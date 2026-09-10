import { spawn } from 'node:child_process'
import { pathToFileURL } from 'node:url'
import process from 'node:process'

export function gatewayTauriEnvironment(environment = process.env) {
  return {
    ...environment,
    CHARTAGENT_MODE: 'gateway',
    VITE_CHARTAGENT_MODE: 'gateway',
  }
}

function npmExecutable() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm'
}

export function runTauriGateway(environment = process.env) {
  const child = spawn(npmExecutable(), ['run', 'tauri:dev'], {
    env: gatewayTauriEnvironment(environment),
    stdio: 'inherit',
  })
  child.on('error', (error) => {
    console.error(`Unable to start Tauri Gateway mode: ${error.message}`)
    process.exitCode = 1
  })
  child.on('exit', (code, signal) => {
    process.exitCode = code ?? (signal ? 1 : 0)
  })
  return child
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runTauriGateway()
}
