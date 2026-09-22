export class GatewayClientError extends Error {
  readonly code: string
  readonly status: number
  readonly reason?: string

  constructor(code: string, message: string, status: number, reason?: string) {
    super(message)
    this.name = 'GatewayClientError'
    this.code = code
    this.status = status
    this.reason = reason
  }
}

let gatewayBaseUrl = (import.meta.env.VITE_CHARTAGENT_GATEWAY_URL || 'http://127.0.0.1:8765/api/v1').replace(/\/$/, '')

export function configureGatewayBaseUrl(value?: string): string {
  if (value) gatewayBaseUrl = value.replace(/\/$/, '')
  return gatewayBaseUrl
}

export function currentGatewayBaseUrl(): string {
  return gatewayBaseUrl
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(gatewayBaseUrl + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    })
  } catch {
    throw new GatewayClientError('gateway_unavailable', '无法连接到本地 Gateway', 0)
  }

  let payload: { error?: { code?: string; message?: string; reason?: string } } & T
  try {
    payload = await response.json()
  } catch {
    throw new GatewayClientError('invalid_gateway_response', 'Gateway 返回了无效响应', response.status)
  }
  if (!response.ok) {
    throw new GatewayClientError(
      payload.error?.code || 'gateway_error',
      payload.error?.message || 'Gateway 请求失败',
      response.status,
      payload.error?.reason,
    )
  }
  return payload
}
