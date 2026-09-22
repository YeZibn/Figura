import { useEffect, useRef, useState } from 'react'
import { BarChart3, Download, FileImage, LoaderCircle, Maximize2, Minus, X } from 'lucide-react'
import { formatBytes } from '../attachments'
import { chartTypeLabel } from '../domain/display'
import { releasePreview, usePreviewResource, type PreviewResourceLoader } from '../previewResources'
import type { GeneratedChartReference, PreviewResource } from '../types/protocol'
import type { PreviewDescriptor, PreviewOpener } from './types'

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
}

export function InteractivePreview({ preview, loader, onClose }: { preview: PreviewDescriptor; loader: PreviewResourceLoader | null; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const [zoom, setZoom] = useState(100)
  const [imageFailed, setImageFailed] = useState(false)
  const resource = usePreviewResource(loader, preview.resource, preview.fallbackUrl)

  useEffect(() => {
    setZoom(100)
    setImageFailed(false)
  }, [preview.resource, preview.fallbackUrl])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const trigger = preview.triggerRef
    const focusTarget = closeRef.current || dialog
    const focusFrame = window.requestAnimationFrame(() => focusTarget.focus())
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const elements = focusableElements(dialog)
      if (elements.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
      window.requestAnimationFrame(() => {
        const element = trigger.current
        if (element?.isConnected) element.focus()
      })
    }
  }, [onClose, preview.triggerRef])

  const changeZoom = (amount: number) => setZoom((value) => Math.min(400, Math.max(50, value + amount)))
  const imageAvailable = resource.status === 'available' && Boolean(resource.url) && !imageFailed

  return <div className="preview-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div ref={dialogRef} className="interactive-preview" role="dialog" aria-modal="true" aria-labelledby="interactive-preview-title" tabIndex={-1}>
      <header className="interactive-preview-header">
        <div className="interactive-preview-heading">
          <span className="eyebrow">{preview.sourceLabel}</span>
          <h2 id="interactive-preview-title">{preview.title}</h2>
          {preview.statusLabel && <span className="interactive-preview-status">{preview.statusLabel}</span>}
        </div>
        <button ref={closeRef} type="button" className="preview-close" onClick={onClose} aria-label="关闭图片预览" title="关闭图片预览"><X size={17} /></button>
      </header>
      <div className="preview-viewport" aria-busy={resource.status === 'loading'}>
        {resource.status === 'loading' && <div className="preview-overlay-message"><LoaderCircle className="spin-icon" size={20} />正在加载预览</div>}
        {imageAvailable && <img className="interactive-preview-image" src={resource.url} alt={preview.alt} style={zoom === 100 ? undefined : { width: `${zoom}%`, maxWidth: 'none', maxHeight: 'none' }} onError={() => setImageFailed(true)} />}
        {!imageAvailable && resource.status !== 'loading' && <div className="preview-overlay-message" role="status">{imageFailed || resource.status === 'invalid' ? '预览格式无效' : resource.error?.message || '预览资源不可用或已过期'}</div>}
      </div>
      <footer className="interactive-preview-controls">
        <div className="preview-zoom-controls" aria-label="图片缩放控制">
          <button type="button" className="preview-control" onClick={() => changeZoom(-25)} disabled={!imageAvailable || zoom <= 50} aria-label="缩小图片" title="缩小图片"><Minus size={14} /></button>
          <span aria-live="polite">{zoom}%</span>
          <button type="button" className="preview-control" onClick={() => changeZoom(25)} disabled={!imageAvailable || zoom >= 400} aria-label="放大图片" title="放大图片"><Maximize2 size={14} /></button>
          <button type="button" className="preview-fit" onClick={() => setZoom(100)} disabled={!imageAvailable} aria-label="适应窗口" title="适应窗口"><Maximize2 size={13} />适应窗口</button>
        </div>
        <span className="preview-control-hint">使用 Tab 操作控件，按 Esc 关闭</span>
      </footer>
    </div>
  </div>
}

export function PreviewImage({ loader, resource, fallbackUrl, alt, className, onError, onPreview, sourceLabel = '图片', title, statusLabel }: { loader: PreviewResourceLoader | null; resource?: PreviewResource; fallbackUrl?: string; alt: string; className?: string; onError?: () => void; onPreview?: PreviewOpener; sourceLabel?: string; title?: string; statusLabel?: string }) {
  const preview = usePreviewResource(loader, resource, fallbackUrl)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [imageError, setImageError] = useState(false)
  useEffect(() => setImageError(false), [preview.url])
  if (preview.status === 'loading') return <div className="preview-placeholder loading-preview"><LoaderCircle className="spin-icon" size={18} />正在加载预览</div>
  if (preview.status === 'available' && preview.url && !imageError) {
    const image = <img className={className} src={preview.url} alt={alt} onError={() => { setImageError(true); onError?.() }} />
    if (!onPreview) return image
    return <button ref={triggerRef} type="button" className="preview-trigger" onClick={() => onPreview({ resource, fallbackUrl, alt, title: title || alt, sourceLabel, statusLabel, triggerRef })} aria-label={`查看${title || alt}大图`} title={`查看${title || alt}大图`}>{image}</button>
  }
  return <div className="preview-placeholder">{preview.status === 'invalid' || imageError ? '预览格式无效' : '预览资源不可用或已过期'}{preview.error?.retryable && <button type="button" className="preview-retry" onClick={preview.retry}>重试</button>}</div>
}

export function ObservationView({ observation, loader, onPreview }: { observation: Record<string, unknown>; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const caption = String(observation.caption || '视觉观察')
  const resource = observation.previewResource as PreviewResource | undefined
  return <div className="trace-observation"><div className="observation-label"><FileImage size={13} /><strong>视觉观察</strong></div><PreviewImage loader={loader} onPreview={onPreview} sourceLabel="视觉观察" title={caption} resource={resource} fallbackUrl={typeof observation.imageUrl === 'string' ? observation.imageUrl : undefined} alt={caption} /><small>{caption}</small></div>
}

export function GeneratedChartView({ artifact, loader, onPreview }: { artifact: GeneratedChartReference; loader: PreviewResourceLoader | null; onPreview?: PreviewOpener }) {
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const [imageFailed, setImageFailed] = useState(false)
  useEffect(() => setImageFailed(false), [artifact.imageUrl, artifact.previewResource])
  const publicationStatus = artifact.publicationStatus || ''
  const reviewStatus = artifact.reviewStatus || ''
  const candidateStatus = artifact.candidateStatus || ''
  const reviewMode = artifact.reviewMode || ''
  const status = publicationStatus === 'published' ? 'available' : publicationStatus === 'published_with_warning' ? 'warning' : publicationStatus === 'rejected' || candidateStatus === 'review_failed' || candidateStatus === 'timed_out' || candidateStatus === 'retry_exhausted' ? 'failed' : reviewStatus === 'pending' || reviewStatus === 'requires_model_decision' || candidateStatus === 'review_pending' || artifact.status === 'pending' ? 'pending' : artifact.status === 'unavailable' || (!artifact.imageUrl && !artifact.previewResource) || imageFailed ? 'unavailable' : artifact.status === 'warning' ? 'warning' : 'available'
  const statusLabel = status === 'available' ? '已发布' : status === 'warning' ? '已发布·有警告' : status === 'pending' ? (reviewMode === 'vlm' ? 'VLM 审核中' : '待审核') : status === 'failed' ? (candidateStatus === 'retry_exhausted' ? '未发布·修复次数已耗尽' : '未发布·审核未通过') : '暂不可用'
  const metadata = [
    artifact.chartType ? chartTypeLabel(artifact.chartType) : '',
    artifact.figureId ? `复合图 ${artifact.figureId}` : '',
    artifact.childChartIds?.length ? `${artifact.childChartIds.length} 个子图` : '',
    artifact.width && artifact.height ? `${artifact.width} × ${artifact.height}` : '',
    typeof artifact.byteCount === 'number' ? formatBytes(artifact.byteCount) : '',
  ].filter(Boolean).join(' · ')
  const figureDetail = artifact.figureId ? [
    artifact.source?.panel_id ? `来源面板：${artifact.source.panel_id}` : '',
    artifact.coverage?.status ? `覆盖：${artifact.coverage.status === 'complete' ? '完整' : artifact.coverage.status}` : '',
    artifact.coverage?.omitted_series?.length ? `遗漏系列：${artifact.coverage.omitted_series.join('、')}` : '',
  ].filter(Boolean).join(' · ') : ''
  const download = async () => {
    if ((!artifact.downloadUrl && !artifact.previewResource) || downloading) return
    setDownloading(true)
    setDownloadError('')
    try {
      let objectUrl = artifact.downloadUrl || ''
      let temporary = false
      if (loader && artifact.previewResource) {
        const result = await loader(artifact.previewResource)
        objectUrl = result.url
        temporary = result.temporary
      } else {
        const response = await fetch(objectUrl)
        if (!response.ok) throw new Error('download failed')
        const blob = await response.blob()
        objectUrl = URL.createObjectURL(blob)
        temporary = true
      }
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = `${artifact.title || 'figura-chart'}.png`
      document.body.appendChild(link)
      link.click()
      link.remove()
      if (temporary) releasePreview({ url: objectUrl, temporary })
    } catch {
      setDownloadError('下载失败，请稍后重试')
    } finally {
      setDownloading(false)
    }
  }
  return <article className={'generated-chart ' + status}>
    <div className="generated-chart-heading"><div className="observation-label"><BarChart3 size={13} /><strong>生成图表</strong><span>{statusLabel}</span></div>{(artifact.downloadUrl || artifact.previewResource) && (status === 'available' || status === 'warning') && <button className="chart-download" type="button" onClick={() => void download()} disabled={downloading} title="下载生成图表"><Download size={13} />{downloading ? '正在下载' : '下载 PNG'}</button>}</div>
    {(artifact.imageUrl || artifact.previewResource) && (status === 'available' || status === 'warning' || status === 'pending' || status === 'failed') ? <PreviewImage loader={loader} onPreview={onPreview} sourceLabel="生成图表" statusLabel={statusLabel} title={artifact.title || artifact.caption || '生成图表'} resource={artifact.previewResource} fallbackUrl={artifact.previewResource ? undefined : artifact.imageUrl} alt={artifact.title || artifact.caption || '生成图表'} onError={() => setImageFailed(true)} /> : <div className="observation-placeholder">{status === 'failed' ? '图表审核未通过，未产生可下载文件' : '图表文件已过期或暂不可用'}</div>}
    <div className="generated-chart-copy"><strong>{artifact.title || artifact.caption || '未命名图表'}</strong>{metadata && <small>{metadata}</small>}{figureDetail && <small>{figureDetail}</small>}{artifact.reason && <small className="generated-chart-reason">{artifact.reason}</small>}{artifact.review?.issues?.slice(0, 3).map((issue, index) => issue.message ? <small className="generated-chart-reason" key={`${issue.code || 'issue'}-${index}`}>{issue.message}</small> : null)}{downloadError && <small className="generated-chart-reason">{downloadError}</small>}</div>
  </article>
}

