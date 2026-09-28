import { useState } from 'react'
import { FileImage } from 'lucide-react'
import type { ReactNode } from 'react'
import type { FiguraPanelDto } from '../../api/figura/types'

export function PanelGallery({ panels, contentUrl }: { panels: FiguraPanelDto[]; contentUrl: (panelId: string) => string }): ReactNode {
  if (panels.length === 0) return null
  return <section className="figura-panels" aria-label="本次运行生成的 Panel">
    <div className="figura-panels-heading"><FileImage size={14} /><strong>图像分区</strong><span>{panels.length} 个 Panel</span></div>
    <div className="figura-panels-grid">{panels.map((item) => <PanelPreview key={item.panelId} panel={item} src={contentUrl(item.panelId)} />)}</div>
  </section>
}

function PanelPreview({ panel, src }: { panel: FiguraPanelDto; src: string }) {
  const [failed, setFailed] = useState(false)
  return <figure className="figura-panel-card">
    {failed
      ? <div className="figura-panel-failed" role="status">预览加载失败</div>
      : <img src={src} alt={panel.name} loading="lazy" decoding="async" onError={() => setFailed(true)} />}
    <figcaption><strong>{panel.name}</strong><small>源附件 {panel.sourceAttachmentId}</small></figcaption>
  </figure>
}
