import type { RefObject } from 'react'
import type { PreviewResource } from '../types/protocol'

export type PendingAttachment = {
  key: string
  file: File
  previewUrl: string
  status: 'uploading' | 'error'
  error?: string
}

export type PreviewDescriptor = {
  resource?: PreviewResource
  fallbackUrl?: string
  alt: string
  title: string
  sourceLabel: string
  statusLabel?: string
  triggerRef: RefObject<HTMLElement>
}

export type PreviewOpener = (descriptor: PreviewDescriptor) => void

