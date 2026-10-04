import { contextDisplay } from '../../domain/figura/context'
import type { RunSummary } from '../../types/run'

export function ContextIndicator({ run }: { run?: RunSummary }) {
  const display = contextDisplay(run)
  return <details className="context-indicator">
    <summary title={display.detail} aria-label={display.label}>{display.label}</summary>
    <div className="context-detail">
      <p>{display.detail}</p>
      {display.fill !== null && <div className="context-meter" role="progressbar" aria-label="上下文估算占比" aria-valuemin={0} aria-valuemax={100} aria-valuenow={display.fill}>
        <span style={{ width: `${display.fill}%` }} />
      </div>}
    </div>
  </details>
}
