import { invoke } from '@tauri-apps/api/core'

export type GatewayRuntimeStatus = {
  state: 'starting' | 'ready' | 'unavailable' | 'stopped'
  url: string
  owned: boolean
  error?: string | null
}

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__)
}

export async function getGatewayRuntimeStatus(): Promise<GatewayRuntimeStatus | null> {
  if (!isTauriRuntime()) return null
  try {
    return await invoke<GatewayRuntimeStatus>('gateway_status')
  } catch {
    return { state: 'unavailable', url: '', owned: false, error: '桌面运行时不可用' }
  }
}
