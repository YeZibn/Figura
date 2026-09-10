export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

export const SUPPORTED_IMAGE_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
])

const extensionTypes: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
}

export function mediaTypeForFile(file: File): string {
  if (file.type) return file.type
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  return extensionTypes[extension] || ''
}

export function validateImageFile(file: File): string | null {
  if (file.size > MAX_ATTACHMENT_BYTES) return '图片不能超过 20 MiB。'
  if (!SUPPORTED_IMAGE_TYPES.has(mediaTypeForFile(file))) return '仅支持 PNG、JPEG、GIF 和 WebP 图片。'
  if (file.size === 0) return '不能上传空文件。'
  return null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
