import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const read = (path) => readFileSync(resolve(root, path), 'utf8')
const gallery = read('src/components/figura/PanelGallery.tsx')
const renderGallery = read('src/components/figura/ChartRenderGallery.tsx')
const app = read('src/FiguraApp.tsx')
const workspace = read('src/components/workspace.tsx')
const api = [
  read('src/api/figura/types.ts'),
  read('src/api/figura/client.ts'),
  read('src/api/figura/workspace.ts'),
].join('\n')
const checks = [
  ['empty Panel state', 'if (panels.length === 0) return null'],
  ['multiple Panel cards', 'panels.map((item)'],
  ['on-demand lazy image loading', 'loading="lazy"'],
  ['failed image state', '预览加载失败'],
  ['image error handling', 'onError={() => setFailed(true)}'],
  ['Session-scoped Panel list', 'listPanels(sessionId)'],
  ['Panel content URL', 'panelContentUrl(sessionId, panelId)'],
  ['Panels grouped by originating Run', 'item.runId === runId'],
  ['Figura-only presentation callback', 'runPanels={(runId) =>'],
  ['ChartAgent remains on its own app', 'return <ChartAgentApp />'],
  ['empty Chart render state', 'if (renders.length === 0) return null'],
  ['multiple Chart render previews', 'renders.map((render)'],
  ['Chart render lazy image loading', 'loading="lazy"'],
  ['Chart render failed state', '预览加载失败'],
  ['missing Figure title fallback', '未命名 Figure'],
  ['Chart render content URL', 'chartRenderContentUrl(sessionId, runId, callId)'],
  ['Chart renders grouped by originating Run', 'summary.chartRenders'],
  ['Chart render preview component', '<ChartRenderGallery'],
]
for (const [label, token] of checks) {
  const source = label === 'empty Panel state' || label === 'multiple Panel cards' || label === 'on-demand lazy image loading' || label === 'failed image state' || label === 'image error handling'
    ? gallery
    : label === 'empty Chart render state' || label === 'multiple Chart render previews' || label === 'Chart render lazy image loading' || label === 'Chart render failed state' || label === 'missing Figure title fallback'
      ? renderGallery
      : label === 'Chart renders grouped by originating Run' || label === 'Chart render preview component'
        ? app
        : label === 'Chart render content URL'
          ? api
    : label === 'Panels grouped by originating Run' || label === 'Figura-only presentation callback'
      ? app
      : label === 'ChartAgent remains on its own app'
        ? read('src/App.tsx')
        : label === 'Session-scoped Panel list' || label === 'Panel content URL'
          ? api
          : workspace
  if (!source.includes(token)) throw new Error('missing Panel UI contract: ' + label)
}
if (!workspace.includes('runPanels?.(timeline.summary.runId)')) throw new Error('Run blocks do not render the Figura Panel supplement')
console.log('Figura image and render preview smoke passed (' + checks.length + ' UI contracts)')
