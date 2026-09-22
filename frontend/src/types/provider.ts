export type Provider = 'openai' | 'qwen' | 'deepseek'

export type GatewayAgentStatus = {
  status: 'ready' | 'unavailable' | 'unknown'
  reason?: string
  provider?: Provider
  model?: string
}

export type GatewayProviderStatus = {
  status: 'ready' | 'unavailable' | 'unknown'
  reason?: string
  provider?: Provider
  model?: string
}

export type GatewayHealth = {
  version: 'v1'
  status: 'ok'
  service: string
  agent?: GatewayAgentStatus & {
    providers?: Partial<Record<Provider, GatewayProviderStatus>>
  }
}
