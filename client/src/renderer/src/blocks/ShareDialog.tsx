import { useEffect, useState } from 'react'
import { Icon } from '../components/Icon'
import { exportBundle, importBundle } from './layout-store'
import { copyText, decryptLayout, encryptLayout } from './share'

interface ShareDialogProps {
  open: boolean
  initialTab: 'share' | 'import'
  onClose: () => void
  onImported: (pages: number) => void
}

export function ShareDialog({ open, initialTab, onClose, onImported }: ShareDialogProps) {
  const [tab, setTab] = useState<'share' | 'import'>(initialTab)
  const [code, setCode] = useState('')
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState<'code' | 'key' | ''>('')

  useEffect(() => {
    if (!open) return
    setTab(initialTab)
    setError('')
    setBusy(false)
    setCopied('')
  }, [open, initialTab])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  const generate = async () => {
    setBusy(true)
    setError('')
    try {
      const bundle = exportBundle()
      const result = await encryptLayout({ mode: bundle.mode, pages: bundle.pages as unknown as Record<string, unknown> })
      setCode(result.code)
      setKey(result.key)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '生成分享码失败。')
    } finally {
      setBusy(false)
    }
  }

  const copy = async (kind: 'code' | 'key') => {
    const ok = await copyText(kind === 'code' ? code : key)
    setCopied(ok ? kind : '')
    if (!ok) setError('复制失败，请手动全选复制。')
  }

  const doImport = async () => {
    setBusy(true)
    setError('')
    try {
      const content = await decryptLayout(code, key)
      const result = importBundle(content)
      onImported(result.applied)
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '导入失败，检查分享码和密钥。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="god-modal" role="dialog" aria-modal="true" aria-label="布局分享">
      <div className="god-modal-backdrop" onClick={onClose} />
      <div className="god-modal-card">
        <div className="god-modal-head">
          <div>
            <b>布局分享</b>
            <small>只含三套模式（全面/专业/自定义）的页面、块顺序和显隐，不含任何比赛或选手数据。</small>
          </div>
          <button type="button" className="god-modal-close" onClick={onClose} aria-label="关闭"><Icon name="close" size={16} /></button>
        </div>

        <div className="god-seg">
          <button type="button" className={tab === 'share' ? 'is-active' : ''} onClick={() => { setTab('share'); setError(''); setCopied('') }}>分享我的布局</button>
          <button type="button" className={tab === 'import' ? 'is-active' : ''} onClick={() => { setTab('import'); setError(''); setCopied('') }}>导入别人的布局</button>
        </div>

        {tab === 'share' ? (
          <div className="god-modal-body">
            {!code ? (
              <>
                <p className="god-modal-note">生成后把「分享码」和「密钥」分两条发给同事，两样都要才能导入。</p>
                <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void generate()}>
                  {busy ? '正在生成…' : '生成分享码'}
                </button>
              </>
            ) : (
              <>
                <label className="god-field">
                  <span>分享码</span>
                  <textarea readOnly value={code} rows={4} onFocus={(event) => event.currentTarget.select()} />
                </label>
                <button type="button" className="btn btn-sm" onClick={() => void copy('code')}>{copied === 'code' ? '已复制' : '复制分享码'}</button>
                <label className="god-field">
                  <span>密钥</span>
                  <input readOnly value={key} onFocus={(event) => event.currentTarget.select()} />
                </label>
                <button type="button" className="btn btn-sm" onClick={() => void copy('key')}>{copied === 'key' ? '已复制' : '复制密钥'}</button>
                <p className="god-modal-note">对方在「自定义布局 → 导入布局」里粘贴两样内容即可。分享码是一次性的，不要公开发在群里。</p>
              </>
            )}
          </div>
        ) : (
          <div className="god-modal-body">
            <label className="god-field">
              <span>分享码</span>
              <textarea value={code} rows={4} placeholder="粘贴以 KPLG1 开头的分享码" onChange={(event) => setCode(event.target.value)} />
            </label>
            <label className="god-field">
              <span>密钥</span>
              <input value={key} placeholder="粘贴 KPL1- 开头的密钥" onChange={(event) => setKey(event.target.value)} />
            </label>
            <p className="god-modal-note">导入会合并到本机：同一页的布局以分享为准，其他页不变。</p>
            <button type="button" className="btn btn-primary" disabled={busy || !code.trim() || !key.trim()} onClick={() => void doImport()}>
              {busy ? '正在导入…' : '导入布局'}
            </button>
          </div>
        )}

        {error ? <div className="god-modal-error">{error}</div> : null}
      </div>
    </div>
  )
}
