import type { FormEvent } from 'react'
import { Trash2 } from 'lucide-react'
import type { Attachment, Session } from '../types/protocol'

export type ConfirmAction =
  | { kind: 'session'; session: Session }
  | { kind: 'attachment'; attachment: Attachment }

export function CreateSessionDialog({ name, onNameChange, onCancel, onSubmit }: { name: string; onNameChange: (value: string) => void; onCancel: () => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  return <div className="dialog-backdrop"><form className="session-dialog" onSubmit={onSubmit}><h2>新建会话</h2><label htmlFor="session-name">会话名称</label><input id="session-name" value={name} onChange={(event) => onNameChange(event.target.value)} placeholder="例如：季度销售分析" autoFocus /><div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={onCancel}>取消</button><button type="submit" className="dialog-primary" disabled={!name.trim()}>创建会话</button></div></form></div>
}

export function ConfirmDeleteDialog({ action, deleting, error, figuraSession = false, onCancel, onConfirm }: { action: ConfirmAction; deleting: boolean; error?: string | null; figuraSession?: boolean; onCancel: () => void; onConfirm: () => void }) {
  const isSession = action.kind === 'session'
  const message = action.kind === 'session'
    ? figuraSession
      ? `将永久删除“${action.session.name}”及其对话、运行记录、附件、Panel 和生成的图表图像。`
      : `将永久删除“${action.session.name}”及其运行记录和附件。`
    : `将删除“${action.attachment.filename}”及其源文件。`
  return <div className="dialog-backdrop"><div className="session-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title"><h2 id="delete-dialog-title">{isSession ? '删除会话？' : '删除附件？'}</h2><p className="dialog-message">{message}</p>{error && <p className="dialog-error" role="alert">{error}</p>}<div className="dialog-actions"><button type="button" className="dialog-secondary" onClick={onCancel} disabled={deleting}>取消</button><button type="button" className="dialog-danger" onClick={onConfirm} disabled={deleting}><Trash2 size={13} />{deleting ? '正在删除' : '确认删除'}</button></div></div></div>
}
