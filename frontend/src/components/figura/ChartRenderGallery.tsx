import { useState, type ReactNode } from 'react'
import { ChartNoAxesCombined } from 'lucide-react'
import type { FiguraChartRenderDto } from '../../api/figura/types'

export function ChartRenderGallery({
  renders,
  contentUrl,
}: {
  renders: FiguraChartRenderDto[]
  contentUrl: (render: FiguraChartRenderDto) => string
}): ReactNode {
  if (renders.length === 0) return null
  return <section className="figura-renders" aria-label="本次运行生成的图表预览">
    <div className="figura-renders-heading"><ChartNoAxesCombined size={14} /><strong>图表预览</strong><span>{renders.length} 张</span></div>
    <div className="figura-renders-grid">{renders.map((render) => <RenderPreview key={render.callId} render={render} src={contentUrl(render)} />)}</div>
  </section>
}

function RenderPreview({ render, src }: { render: FiguraChartRenderDto; src: string }) {
  const [failed, setFailed] = useState(false)
  return <figure className="figura-render-card">
    {failed
      ? <div className="figura-render-failed" role="status">预览加载失败</div>
      : <img src={src} alt={render.figureTitle || '生成的图表'} loading="lazy" decoding="async" onError={() => setFailed(true)} />}
    <figcaption><strong>{render.figureTitle || '未命名 Figure'}</strong><small>{render.width} × {render.height} · PNG</small></figcaption>
  </figure>
}
