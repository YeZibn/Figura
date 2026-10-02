import { useState, type ReactNode } from 'react'
import { ChartNoAxesCombined, Download, LoaderCircle } from 'lucide-react'
import type { FiguraChartRenderDto } from '../../api/figura/types'
import { PreviewImage } from '../preview'
import type { PreviewOpener } from '../types'

export function ChartRenderGallery({
  renders,
  contentUrl,
  downloadContent,
  onPreview,
}: {
  renders: FiguraChartRenderDto[]
  contentUrl: (render: FiguraChartRenderDto) => string
  downloadContent: (render: FiguraChartRenderDto) => Promise<Blob>
  onPreview: PreviewOpener
}): ReactNode {
  if (renders.length === 0) return null
  return <section className="figura-renders" aria-label="本次运行生成的图表预览">
    <div className="figura-renders-heading"><ChartNoAxesCombined size={14} /><strong>图表预览</strong><span>{renders.length} 张</span></div>
    <div className="figura-renders-grid">{renders.map((render) => <RenderPreview key={render.callId} render={render} src={contentUrl(render)} downloadContent={downloadContent} onPreview={onPreview} />)}</div>
  </section>
}

function RenderPreview({ render, src, downloadContent, onPreview }: {
  render: FiguraChartRenderDto
  src: string
  downloadContent: (render: FiguraChartRenderDto) => Promise<Blob>
  onPreview: PreviewOpener
}) {
  const [failed, setFailed] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const title = render.figureTitle || '未命名 Figure'

  const download = async () => {
    if (downloading) return
    setDownloading(true)
    setDownloadError('')
    let objectUrl = ''
    try {
      const blob = await downloadContent(render)
      objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      try {
        link.href = objectUrl
        link.download = chartRenderFilename(render.figureTitle)
        document.body.appendChild(link)
        link.click()
        const downloadUrl = objectUrl
        window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000)
        objectUrl = ''
      } finally {
        link.remove()
      }
    } catch {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      setDownloadError('下载失败，请稍后重试。')
    } finally {
      setDownloading(false)
    }
  }

  return <figure className="figura-render-card">
    {failed
      ? <div className="figura-render-failed" role="status">预览加载失败</div>
      : <PreviewImage loader={null} fallbackUrl={src} alt={title} title={title} sourceLabel="生成图表" className="figura-render-image" loading="lazy" decoding="async" onError={() => setFailed(true)} onPreview={onPreview} />}
    <figcaption>
      <div className="figura-render-caption">
        <div><strong>{title}</strong><small>{render.width} × {render.height} · PNG</small></div>
        <button className="figura-render-download" type="button" onClick={() => void download()} disabled={downloading} aria-label={`下载 ${title}`}>
          {downloading ? <LoaderCircle className="spin-icon" size={12} /> : <Download size={12} />}
          {downloading ? '正在下载' : '下载 PNG'}
        </button>
      </div>
      {downloadError && <small className="figura-render-download-error" role="status">{downloadError}</small>}
    </figcaption>
  </figure>
}

function chartRenderFilename(title: string): string {
  const sanitized = title
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, '_')
    .trim()
    .replace(/[. ]+$/g, '')
    .replace(/\.png$/i, '')
    .trim()
  const baseName = sanitized || 'figura-chart'
  const safeBaseName = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(baseName) ? `_${baseName}` : baseName
  return `${safeBaseName}.png`
}
