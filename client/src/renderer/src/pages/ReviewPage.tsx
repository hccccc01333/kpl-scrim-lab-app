import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useConnection } from '../lib/app-context'
import { useChannel } from '../lib/hooks'
import { api } from '../lib/api'
import { duration as fmtDuration, number } from '../lib/format'
import type { ChannelMatch, DraftPlayer } from '../lib/types'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import { pushToast } from '../lib/toast'
import { Icon } from '../components/Icon'

const FIELDS: [string, string][] = [
  ['kills', '击杀'],
  ['deaths', '死亡'],
  ['assists', '助攻'],
  ['gold', '经济'],
  ['damage', '输出'],
  ['taken', '承伤'],
  ['participation', '参团'],
  ['rating', '评分']
]

const SOURCE_LABEL: Record<string, string> = {
  official: '官方回放',
  camp: '营地',
  table: '表格',
  video: '录屏',
  screenshot: '截图',
  replay: '回放'
}

function stamp(value?: string | null): string {
  if (!value) return '—'
  const text = String(value)
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text
}

function scoreOf(match?: ChannelMatch): string {
  const scores = match?.scores
  if (!scores) return '—'
  return `${scores.left ?? scores.blue ?? '—'} : ${scores.right ?? scores.red ?? '—'}`
}

export function ReviewPage() {
  const { baseUrl } = useConnection()
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const query = useChannel(baseUrl, id)
  const [rows, setRows] = useState<DraftPlayer[]>([])
  const [loadedFor, setLoadedFor] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ message: string; error?: boolean } | null>(null)
  const [officialUrl, setOfficialUrl] = useState('')
  const [officialBusy, setOfficialBusy] = useState(false)
  const [officialNotice, setOfficialNotice] = useState<{ message: string; error?: boolean } | null>(null)

  useEffect(() => {
    if (!query.data || loadedFor === query.data.id) return
    const players = (query.data.draft?.players || []).map((player) => ({
      ...player,
      fields: Object.fromEntries(Object.entries(player.fields || {}).map(([key, field]) => [key, { ...field }]))
    }))
    setRows(players)
    setNotes(query.data.review?.notes || '')
    setLoadedFor(query.data.id)
  }, [query.data, loadedFor])

  const channel = query.data
  const reviewed = channel?.review?.status === 'reviewed'
  const saved = channel?.saved?.status === 'saved'
  const counts = channel?.sourceStatus?.counts || {}
  const required = channel?.sourceStatus?.requiredSources || []
  const statusLabel = saved ? '已入库' : reviewed ? '已通过' : '待补缺失'
  const statusTone = saved ? 'badge-win' : reviewed ? 'badge-gold' : ''

  const players = useMemo(() => rows.slice().sort((a, b) => {
    const sideA = a.side === 'left' ? 0 : 1
    const sideB = b.side === 'left' ? 0 : 1
    return sideA - sideB || a.slot - b.slot
  }), [rows])

  const updateRow = (side: string, slot: number, key: string, value: string) => {
    setRows((current) => current.map((player) => {
      if (player.side !== side || player.slot !== slot) return player
      if (key === 'hero') return { ...player, hero: value }
      const fields = { ...(player.fields || {}) }
      fields[key] = { ...(fields[key] || {}), value }
      return { ...player, fields }
    }))
  }

  const attachOfficial = async () => {
    if (!channel) return
    const url = officialUrl.trim()
    if (!url) { setOfficialNotice({ message: '先粘贴王者营地回放链接。', error: true }); return }
    setOfficialBusy(true)
    setOfficialNotice(null)
    try {
      const imported = await api<{ id?: string }>(baseUrl, '/api/official/replay', { method: 'POST', body: { url } })
      if (!imported?.id) throw new Error('回放没有返回 ID')
      await api(baseUrl, `/api/channels/${encodeURIComponent(channel.id)}/official`, { method: 'POST', body: { officialId: imported.id } })
      setOfficialUrl('')
      setOfficialNotice({ message: '官方回放已关联；补齐缺失后可直接入库。' })
      await queryClient.invalidateQueries({ queryKey: ['channel', baseUrl, channel.id] })
      await queryClient.invalidateQueries({ queryKey: ['channels', baseUrl] })
    } catch (error) {
      setOfficialNotice({ message: error instanceof Error ? error.message : '关联失败', error: true })
    } finally {
      setOfficialBusy(false)
    }
  }

  const draftPayload = () => rows.map((player) => ({
    side: player.side,
    slot: player.slot,
    hero: player.hero || '',
    fields: Object.fromEntries(FIELDS.map(([field]) => [field, player.fields?.[field]?.value ?? '']))
  }))

  const saveDraft = async () => {
    if (!channel) return
    setBusy('draft')
    setNotice({ message: '正在保存修改…' })
    try {
      await api(baseUrl, `/api/channels/${encodeURIComponent(channel.id)}/draft`, { method: 'PATCH', body: { players: draftPayload() } })
      await queryClient.invalidateQueries({ queryKey: ['channel', baseUrl, channel.id] })
      await queryClient.invalidateQueries({ queryKey: ['channels', baseUrl] })
      setLoadedFor('')
      setNotice({ message: '修改已保存为草稿；补齐缺失后可直接通过并入库。' })
    } catch (error) {
      setNotice({ message: error instanceof Error ? error.message : '保存失败', error: true })
    } finally {
      setBusy('')
    }
  }

  const saveFormal = async () => {
    if (!channel) return
    setBusy('save')
    setNotice({ message: '正在补齐并入库…' })
    try {
      await api(baseUrl, `/api/channels/${encodeURIComponent(channel.id)}/draft`, { method: 'PATCH', body: { players: draftPayload() } })
      // 不再要求单独的复核/标记步骤；保存接口只写正式统计，不拦复核状态。
      await api(baseUrl, `/api/channels/${encodeURIComponent(channel.id)}/save`, { method: 'POST' })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['channel', baseUrl, channel.id] }),
        queryClient.invalidateQueries({ queryKey: ['channels', baseUrl] }),
        queryClient.invalidateQueries({ queryKey: ['overview', baseUrl] }),
        queryClient.invalidateQueries({ queryKey: ['matches', baseUrl] }),
        queryClient.invalidateQueries({ queryKey: ['player-board', baseUrl] })
      ])
      setLoadedFor('')
      setNotice({ message: '缺失值已补齐，已写入正式统计。' })
      pushToast('缺失值审查通过，已入库', 'success')
      void window.kpl.notify({ title: '缺失值审查', body: '已通过并写入正式统计' })
    } catch (error) {
      const message = error instanceof Error ? error.message : '入库失败'
      setNotice({ message, error: true })
      pushToast(`入库失败：${message}`, 'error')
    } finally {
      setBusy('')
    }
  }

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !channel) {
    return (
      <div className="page">
        <PageHeader eyebrow="REVIEW" title="通道没有找到" actions={<button type="button" className="btn" onClick={() => navigate('/collect')}><Icon name="back" />返回采集</button>} />
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </div>
    )
  }

  const match = channel.match || {}
  const won = match.winner && match.ownSide ? match.winner === match.ownSide : null
  const result = won === null ? '结果未知' : won ? '胜' : '负'
  const hasScore = Boolean(match.scores && Object.values(match.scores).some((value) => value !== null && value !== undefined))

  return (
    <div className="page">
      <PageHeader
        eyebrow="REVIEW · CHANNEL"
        title={<>缺失值审查<em>{[match.date, match.session, match.mode].filter(Boolean).join(' · ')}</em></>}
        subtitle="只处理有缺失值的对局；补齐后一键通过并入库，无缺失的对局会自动通过。"
        actions={<><button type="button" className="btn" onClick={() => navigate('/collect')}><Icon name="back" />返回采集</button><button type="button" className="btn" onClick={() => window.print()}><Icon name="printer" />打印</button></>}
      />

      <div className={`review-status${saved ? ' is-saved' : reviewed ? ' is-reviewed' : ''}`}>
        <div><span className="eyebrow">CHANNEL</span><div className="review-score"><strong>{scoreOf(match)}</strong><span className={`badge ${won === true ? 'badge-win' : won === false ? 'badge-loss' : ''}`}>{result}</span><span className={`badge ${statusTone}`}>{statusLabel}</span></div></div>
        <div className="review-status-meta"><span>{fmtDuration(match.durationSec)}</span>{!hasScore ? <span>个人回放无 5v5 比分</span> : null}<span>{channel.sourceStatus?.counts ? `${Object.values(counts).filter((value) => Number(value) > 0).length} 类来源` : '无来源'}</span><span>更新 {stamp(channel.updatedAt)}</span></div>
        <div className="row">
          <button type="button" className="btn" disabled={busy !== ''} onClick={() => void saveDraft()}>{busy === 'draft' ? '保存中…' : '保存修改'}</button>
          <button type="button" className="btn btn-primary" disabled={busy !== '' || saved} onClick={() => void saveFormal()}>{busy === 'save' ? '入库中…' : saved ? '已入库' : '补齐并入库'}</button>
        </div>
      </div>

      {notice ? <div className={`connect-status${notice.error ? ' is-error' : ' is-ok'}`} style={{ padding: '0 4px' }}>{notice.message}</div> : null}
      {!players.length ? <div className="notice"><Icon name="alert" size={15} /><span><b>缺十人面板：</b>{channel.sourceStatus?.missing?.join('；') || '官方回放只提供过程数据；个人排位赛没有 5v5 比分。请补营地 mp-redirect 面板或从营地列表重新入库。'}</span></div> : null}

      <div className="review-layout">
        <section className="card review-main">
          <div className="card-head"><div><h2 className="card-title">十人数据</h2><div className="card-sub">昵称只在身份维护里改；这里修改英雄和面板数值。</div></div><span className="badge">{number(players.length)} 人</span></div>
          {players.length ? (
            <div className="review-table-wrap">
              <table className="review-table">
                <thead><tr><th>位置</th><th>昵称</th><th>英雄</th>{FIELDS.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
                <tbody>
                  {players.map((player) => (
                    <tr key={`${player.side}-${player.slot}`}>
                      <td className="review-side"><i>{player.side === 'left' ? '左' : '右'}</i>{player.slot + 1}</td>
                      <td className="review-name" title={player.nickname || ''}>{player.nickname || '—'}</td>
                      <td><input className="input review-input is-text" value={player.hero || ''} onChange={(event) => updateRow(player.side, player.slot, 'hero', event.target.value)} aria-label="英雄" /></td>
                      {FIELDS.map(([field]) => (
                        <td key={field}><input className="input review-input is-num" type="number" step="any" value={player.fields?.[field]?.value ?? ''} onChange={(event) => updateRow(player.side, player.slot, field, event.target.value)} aria-label={field} /></td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div className="empty-state"><b>这个通道没有十人面板</b><p>草稿来自营地十人面板或七图+录屏；只有官方回放时不会生成十人数据和比分。先补营地 mp-redirect 面板，再回来审查。</p></div>}
        </section>

        <aside className="review-side">
          <section className="card">
            <div className="card-head"><div><h2 className="card-title">官方回放</h2><div className="card-sub">必采来源；粘贴王者营地回放分享链接，导入后关联本局。</div></div><span className={`badge ${Number(counts.official || 0) ? 'badge-win' : 'badge-loss'}`}>{Number(counts.official || 0) ? '已关联' : '缺失'}</span></div>
            <div className="card-body stack">
              <div className="field"><label htmlFor="official-url">回放分享链接</label><textarea id="official-url" className="input" rows={2} value={officialUrl} onChange={(event) => setOfficialUrl(event.target.value)} placeholder="https://camp.qq.com/h5/..." spellCheck={false} /></div>
              <button type="button" className="btn btn-primary" disabled={officialBusy || !officialUrl.trim()} onClick={() => void attachOfficial()}>{officialBusy ? '正在导入…' : '导入并关联'}</button>
              {officialNotice ? <div className={`connect-status${officialNotice.error ? ' is-error' : ' is-ok'}`}>{officialNotice.message}</div> : null}
              {!counts.official ? <p className="card-sub">营地同步之后，这里补上本局回放链接，材料才算齐。</p> : null}
            </div>
          </section>

          <section className="card">
            <div className="card-head"><div><h2 className="card-title">缺失值处理</h2><div className="card-sub">补齐缺失字段后点右上角「补齐并入库」；直接写正式统计，不再走复核。</div></div></div>
            <div className="card-body stack">
              <div className="field"><label htmlFor="review-notes">备注</label><textarea id="review-notes" className="input" rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="例如：按营地十人面板核对，缺失的英雄已补齐" /></div>
              <p className="card-sub">保存后直接写正式统计；缺字段保持为空，分析页会标注来源。</p>
              {reviewed ? <div className="notice"><Icon name="check" size={15} /><span>已通过 · {stamp(channel.review?.reviewedAt)}</span></div> : null}
            </div>
          </section>

          <section className="card">
            <div className="card-head"><div><h2 className="card-title">素材来源</h2><div className="card-sub">营地为主；其它来源只作参考。</div></div></div>
            <div className="review-sources">
              {Object.entries(SOURCE_LABEL).map(([key, label]) => (
                <div key={key} className={Number(counts[key] || 0) ? '' : 'is-off'}>
                  <span>{label}</span><b>{counts[key] || 0}</b>{required.includes(key) ? <small>必采</small> : null}
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="card-head"><div><h2 className="card-title">变更记录</h2><div className="card-sub">最近 6 条</div></div></div>
            <div className="review-log">
              {(channel.changeLog || []).slice(-6).reverse().map((item, index) => <div key={`${item.at || ''}-${index}`}><span>{stamp(item.at)}</span><b>{item.action || '修改'}</b></div>)}
              {!(channel.changeLog || []).length ? <div className="empty-state"><b>还没有记录</b></div> : null}
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
