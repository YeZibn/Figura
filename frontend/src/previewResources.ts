import { useEffect, useState } from 'react'
import type { PreviewLoadResult, PreviewResource } from './types/protocol'

export const PREVIEW_IMAGE_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
])

export type PreviewLoadError = Error & {
  code?: 'preview_unavailable' | 'preview_invalid_media' | 'preview_invalid_image'
  retryable?: boolean
  status?: number
}

export type PreviewResourceLoader = (
  resource: PreviewResource,
  options?: { signal?: AbortSignal },
) => Promise<PreviewLoadResult>

export function normalizeGatewayBaseUrl(value?: string): string {
  const fallback = 'http://127.0.0.1:8765/api/v1'
  return (value || fallback).replace(/\/$/, '')
}

export function previewResourcePath(resource: PreviewResource): string {
  if (resource.kind === 'evaluation') {
    return `/evaluations/${encodeURIComponent(resource.evaluationId)}/resources/${encodeURIComponent(resource.resourceId)}?case_id=${encodeURIComponent(resource.caseId)}`
  }
  const session = encodeURIComponent(resource.sessionId)
  const run = 'runId' in resource ? `/runs/${encodeURIComponent(resource.runId)}` : ''
  if (resource.kind === 'attachment') return `/sessions/${session}/attachments/${encodeURIComponent(resource.attachmentId)}/content`
  if (resource.kind === 'observation') return `/sessions/${session}${run}/observations/${encodeURIComponent(resource.observationId)}`
  if (resource.kind === 'staged') return `/sessions/${session}${run}/chart-previews/${encodeURIComponent(resource.stagedRef)}`
  return `/sessions/${session}${run}/chart-previews/${encodeURIComponent(resource.artifactId)}`
}

function previewError(code: PreviewLoadError['code'], message: string, retryable: boolean, status?: number): PreviewLoadError {
  const error = new Error(message) as PreviewLoadError
  error.name = 'PreviewLoadError'
  error.code = code
  error.retryable = retryable
  error.status = status
  return error
}

function decodeImage(url: string, contentType: string): Promise<void> {
  if (typeof Image === 'undefined') return Promise.resolve()
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve()
    image.onerror = () => reject(previewError('preview_invalid_image', '预览内容不是有效图片', false))
    image.src = url
    void contentType
  })
}

export function createGatewayPreviewLoader(baseUrl?: string): PreviewResourceLoader {
  const gatewayBaseUrl = normalizeGatewayBaseUrl(baseUrl)
  return async (resource, options = {}) => {
    let response: Response
    try {
      response = await fetch(gatewayBaseUrl + previewResourcePath(resource), { signal: options.signal })
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') throw reason
      throw previewError('preview_unavailable', '无法连接预览资源', true)
    }
    if (!response.ok) {
      const retryable = response.status === 408 || response.status === 429 || response.status >= 500
      throw previewError('preview_unavailable', response.status === 404 ? '预览资源不存在或已过期' : '预览资源暂时不可用', retryable, response.status)
    }
    const contentType = (response.headers.get('Content-Type') || '').split(';', 1)[0].trim().toLowerCase()
    if (!PREVIEW_IMAGE_TYPES.has(contentType)) throw previewError('preview_invalid_media', '预览资源不是受支持的图片格式', false, response.status)
    const blob = await response.blob()
    if (!blob.size) throw previewError('preview_invalid_image', '预览资源为空', false, response.status)
    const objectUrl = URL.createObjectURL(blob)
    try {
      await decodeImage(objectUrl, contentType)
      return { url: objectUrl, contentType, temporary: true }
    } catch (error) {
      URL.revokeObjectURL(objectUrl)
      throw error
    }
  }
}

export function releasePreview(result?: PreviewLoadResult | null): void {
  if (result?.temporary && result.url.startsWith('blob:')) URL.revokeObjectURL(result.url)
}

export type PreviewState = {
  status: 'idle' | 'loading' | 'available' | 'unavailable' | 'invalid'
  url: string
  error?: PreviewLoadError
  retry: () => void
}

export function usePreviewResource(
  loader: PreviewResourceLoader | null,
  resource?: PreviewResource,
  fallbackUrl?: string,
): PreviewState {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<PreviewState>({ status: fallbackUrl ? 'available' : resource ? 'idle' : 'unavailable', url: fallbackUrl || '', retry: () => setAttempt((value) => value + 1) })

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    let loaded: PreviewLoadResult | null = null
    const retry = () => setAttempt((value) => value + 1)
    if (fallbackUrl) {
      setState({ status: 'available', url: fallbackUrl, retry })
      return () => undefined
    }
    if (!loader || !resource) {
      setState({ status: 'unavailable', url: '', retry })
      return () => undefined
    }
    setState({ status: 'loading', url: '', retry })
    void loader(resource, { signal: controller.signal }).then((result) => {
      if (!active) {
        releasePreview(result)
        return
      }
      loaded = result
      setState({ status: 'available', url: result.url, retry })
    }).catch((reason: unknown) => {
      if (!active || (reason instanceof DOMException && reason.name === 'AbortError')) return
      const error = reason as PreviewLoadError
      setState({ status: error.code === 'preview_invalid_media' || error.code === 'preview_invalid_image' ? 'invalid' : 'unavailable', url: '', error, retry })
    })
    return () => {
      active = false
      controller.abort()
      releasePreview(loaded)
    }
  }, [attempt, fallbackUrl, loader, resource])

  return state
}
