import { useState, type ReactNode } from 'react'
import { loadEvaluationResource } from '../api/gateway/evaluationResource'
import { eventPayload, failureContext, textDetail } from '../domain/records'
import { failureCategoryLabel, timelineEventStatusLabel } from '../domain/display'
import type { AgentRunEvent } from '../types/protocol'

export function CopyDetailButton({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(textDetail(value))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }
  return <button type="button" className="detail-copy-button" onClick={() => void copy()}>{copied ? '已复制' : '复制 JSON'}</button>
}

export function EvaluationDetailResourceView({ resource, evaluationId, caseId }: { resource: Record<string, unknown>; evaluationId?: string; caseId?: string }) {
  const [state, setState] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle')
  const [value, setValue] = useState<unknown>(null)
  const resourceId = typeof resource.resourceId === 'string' ? resource.resourceId : ''
  const resourceCaseId = typeof resource.caseId === 'string' ? resource.caseId : caseId || ''
  if (!resourceId || !evaluationId || !resourceCaseId) return null
  const load = async () => {
    if (state === 'loading' || state === 'loaded') return
    setState('loading')
    try {
      setValue(await loadEvaluationResource(evaluationId, resourceId, resourceCaseId))
      setState('loaded')
    } catch {
      setState('error')
    }
  }
  return <div className="trace-detail-resource"><div className="trace-detail-resource-heading"><span>完整安全结果</span><button type="button" className="detail-copy-button" onClick={() => void load()} disabled={state === 'loading' || state === 'loaded'}>{state === 'loading' ? '正在加载' : state === 'loaded' ? '已加载' : '加载完整结果'}</button></div>{state === 'error' && <small className="trace-warning">完整结果资源暂时不可用；当前事件只保留了安全摘要。</small>}{state === 'loaded' && <><CopyDetailButton value={value} /><pre>{textDetail(value)}</pre></>}</div>
}

export function traceEventDetail(event: AgentRunEvent): string {
  const payload = eventPayload(event)
  const failure = failureContext(payload, event.kind)
  if (failure) {
    const details = [
      failure.safeMessage || payload.message,
      failure.category ? `分类：${failureCategoryLabel(failure.category)}` : undefined,
      failure.code ? `错误码：${failure.code}` : undefined,
      failure.location ? `字段：${failure.location}` : undefined,
      failure.providerStatus !== undefined ? `Provider 状态：${failure.providerStatus}` : undefined,
      failure.retryable !== undefined ? `可重试：${failure.retryable ? '是' : '否'}` : undefined,
      failure.outcomeKnown === false ? '远端结果：未知' : undefined,
      failure.actionHint,
    ].filter(Boolean).map(String)
    if (details.length > 0) return details.join(' · ')
  }
  const statusField = event.kind === 'tool_result' ? payload.status : payload.state
  const statusSummary = timelineEventStatusLabel(event.kind, statusField)
  return textDetail(payload.message || statusSummary || payload.reason || '')
}

function isSafeLink(value: string): boolean {
  return /^(https?:\/\/|mailto:)/i.test(value)
}

function inlineMarkdown(value: string, keyPrefix: string): ReactNode[] {
  const parts = value.split(/(\[[^\]]+\]\([^\)]+\)|\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_)/g).filter(Boolean)
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`
    const link = part.match(/^\[([^\]]+)\]\(([^\)]+)\)$/)
    if (link) return isSafeLink(link[2]) ? <a key={key} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a> : <span key={key}>{link[1]}</span>
    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) return <strong key={key}>{part.slice(2, -2)}</strong>
    if ((part.startsWith('*') && part.endsWith('*')) || (part.startsWith('_') && part.endsWith('_'))) return <em key={key}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={key}>{part.slice(1, -1)}</code>
    return <span key={key}>{part}</span>
  })
}

export function SafeMarkdown({ source }: { source: string }) {
  const text = source.slice(0, 12000)
  const lines = text.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (line.startsWith('```')) {
      const language = line.slice(3).trim()
      const code: string[] = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) { code.push(lines[index]); index += 1 }
      blocks.push(<pre className="markdown-code" key={`code-${index}`}><code data-language={language || undefined}>{code.join('\n')}</code></pre>)
      index += 1
      continue
    }
    if (!line.trim()) { index += 1; continue }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) { const Tag = `h${heading[1].length}` as 'h1' | 'h2' | 'h3'; blocks.push(<Tag key={`heading-${index}`}>{inlineMarkdown(heading[2], `heading-${index}`)}</Tag>); index += 1; continue }
    if (/^\|.*\|$/.test(line) && index + 1 < lines.length && /^\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const rows: string[][] = []
      while (index < lines.length && /^\|.*\|$/.test(lines[index]) && !/^\|?\s*:?-{3,}/.test(lines[index])) {
        rows.push(lines[index].replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim())); index += 1
        if (index < lines.length && /^\|?\s*:?-{3,}/.test(lines[index])) index += 1
      }
      blocks.push(<table className="markdown-table" key={`table-${index}`}><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => rowIndex === 0 ? <th key={cellIndex}>{inlineMarkdown(cell, `table-${index}-${rowIndex}-${cellIndex}`)}</th> : <td key={cellIndex}>{inlineMarkdown(cell, `table-${index}-${rowIndex}-${cellIndex}`)}</td>)}</tr>)}</tbody></table>)
      continue
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line)
      const items: string[] = []
      while (index < lines.length && (ordered ? /^\s*\d+\.\s+/.test(lines[index]) : /^\s*[-*]\s+/.test(lines[index]))) items.push(lines[index].replace(ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/, '')), index += 1
      const List = ordered ? 'ol' : 'ul'
      blocks.push(<List key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item, `list-${index}-${itemIndex}`)}</li>)}</List>)
      continue
    }
    const paragraph: string[] = [line]
    index += 1
    while (index < lines.length && lines[index].trim() && !lines[index].startsWith('```') && !/^(#{1,3})\s+/.test(lines[index])) { paragraph.push(lines[index]); index += 1 }
    blocks.push(<p key={`paragraph-${index}`}>{paragraph.map((part, partIndex) => <span key={partIndex}>{partIndex > 0 && <br />}{inlineMarkdown(part, `paragraph-${index}-${partIndex}`)}</span>)}</p>)
  }
  return <div className="markdown-content">{blocks}</div>
}
