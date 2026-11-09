import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useConnection } from '../lib/app-context'
import { useCampStatus, useChannels, useOfficialReplays } from '../lib/hooks'
import { api, assetUrl } from '../lib/api'
import { duration as fmtDuration, number, resultLabel, shortDate } from '../lib/format'
import type {
  CampEntry,
  CampListResult,
  CampPlayer,
  CampPoll,
  CampQr,
  CampSync,
  ChannelDetail,
  ChannelMatch,
  ChannelSummary
} from '../lib/types'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import { pushToast } from '../lib/toast'
import { Icon } from '../components/Icon'

function stamp(value?: string | null): string {
  if (!value) return '—'
  const text = String(value)
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text
}

const CAMP_DETAIL_TTL_DAYS = 31

/** 营地列表的 dtEventTime 是秒级记录时间，不是毫秒；开赛时间优先用后端 startedAt。 */
function matchTime(entry: CampEntry): { day: string; clock: string; full: string } {
  const started = String(entry.startedAt || '')
  if (started.length >= 16) {
    return {
      day: started.slice(5, 10),
      clock: started.slice(11, 16),
      full: `${started.slice(0, 10)} ${started.slice(11, 16)}`
    }
  }
  const gametime = String(entry.gametime || '').trim()
  if (gametime) {
    const parts = gametime.split(/\s+/)
    return { day: parts[0] || '', clock: parts[1] || '', full: gametime }
  }
  const sec = Number(entry.dtEventTime || 0)
  const used = Number(entry.usedTime || 0)
  if (sec > 0) {
    const date = new Date((sec - used) * 1000 + 8 * 3600 * 1000)
    const pad = (value: number) => String(value).padStart(2, '0')
    return {
      day: `${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`,
      clock: `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`,
      full: `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
    }
  }
  return { day: '--', clock: '', full: '' }
}

function entryMoment(entry: CampEntry): number {
  const started = String(entry.startedAt || '')
  const parsed = started.length >= 10 ? Date.parse(started) : NaN
  if (Number.isFinite(parsed)) return parsed
  const sec = Number(entry.dtEventTime || 0)
  const used = Number(entry.usedTime || 0)
  return sec > 0 ? (sec - used) * 1000 : 0
}

/** 营地只保留最近一个月详情；以接口字段优先，31 天兜底。 */
function campDetailExpired(entry: CampEntry): boolean {
  if (entry.campDetailAvailable === false) return true
  if (entry.campDetailAvailable === true) return false
  const moment = entryMoment(entry)
  if (!moment) return false
  return Date.now() - moment > CAMP_DETAIL_TTL_DAYS * 86400000
}

function entryClock(entry: CampEntry): string {
  return matchTime(entry).clock || '—'
}

function groupEntries(entries: CampEntry[]): { key: string; entries: CampEntry[] }[] {
  const groups = new Map<string, { entries: CampEntry[]; moment: number }>()
  for (const entry of entries) {
    const key = matchTime(entry).day || '日期未知'
    const group = groups.get(key) || { entries: [], moment: 0 }
    group.entries.push(entry)
    group.moment = Math.max(group.moment, entryMoment(entry))
    groups.set(key, group)
  }
  return [...groups.entries()]
    .sort((a, b) => b[1].moment - a[1].moment)
    .map(([key, group]) => ({
      key,
      entries: group.entries.slice().sort((a, b) => entryMoment(b) - entryMoment(a))
    }))
}

function scoreOf(match?: ChannelMatch): string {
  const scores = match?.scores
  if (!scores) return '—'
  const own = match?.ownSide === 'right' ? scores.right ?? scores.red : scores.left ?? scores.blue
  const other = match?.ownSide === 'right' ? scores.left ?? scores.blue : scores.right ?? scores.red
  return own === undefined || other === undefined ? '—' : `${own} : ${other}`
}

function channelState(channel: ChannelSummary): { tone: string; label: string } {
  if (channel.saved?.status === 'saved') return { tone: 'badge-win', label: '已入库' }
  if (channel.review?.status === 'reviewed') return { tone: 'badge-gold', label: '已通过' }
  return { tone: '', label: '待补缺失' }
}



function replayUrlFromPanel(panel: ParsedCampLink): string {
  if (!panel.gameSvrId || !panel.relaySvrId) {
    throw new Error('面板链接缺少 gameSvrId 或 relaySvrId，无法自动补回放')
  }
  const url = new URL('https://camp.qq.com/h5/webdist/battle-replay/index.html')
  url.searchParams.set('isNavigationBarHidden', '1')
  url.searchParams.set('gameseq', panel.gameSeq)
  url.searchParams.set('relaysvrentity', panel.relaySvrId)
  url.searchParams.set('gamesvrentity', panel.gameSvrId)
  url.searchParams.set('playerid', panel.userId || '')
  return url.toString()
}

interface ParsedCampLink {
  kind: 'panel' | 'replay'
  gameSeq: string
  userId?: string
  roleId?: string
  gameSvrId?: string
  relaySvrId?: string
  battleType?: string
  pvpType?: string
  playerId?: string
}

/** 营地列表条目自带 gameSvrId / relaySvrId；面板链接导入后用它补官方回放。 */
function replayUrlFromEntry(entry: CampEntry): string {
  if (!entry.gameSeq || !entry.gameSvrId || !entry.relaySvrId) {
    throw new Error('这条对局缺少 gameSvrId / relaySvrId，无法补官方回放')
  }
  const url = new URL('https://camp.qq.com/h5/webdist/battle-replay/index.html')
  url.searchParams.set('gameseq', entry.gameSeq)
  url.searchParams.set('gamesvrentity', entry.gameSvrId)
  url.searchParams.set('relaysvrentity', entry.relaySvrId)
  url.searchParams.set('playerid', entry.uniqueRoleId || '')
  return url.toString()
}

function parseCampLink(raw: string): ParsedCampLink {
  const url = new URL(raw.trim())
  if (!/(^|\.)camp\.qq\.com$/i.test(url.hostname)) throw new Error('只接受 camp.qq.com 的营地链接')
  const query = new Map<string, string>()
  url.searchParams.forEach((value, key) => query.set(key.toLowerCase(), value))
  const pick = (...keys: string[]) => {
    for (const key of keys) {
      const value = query.get(key.toLowerCase())
      if (value) return value
    }
    return ''
  }
  const gameSeq = pick('gameseq', 'gameSeq')
  if (!/^\d{3,20}$/.test(gameSeq)) throw new Error('链接里没有有效的 gameSeq')
  if (url.pathname.includes('battle-replay')) {
    const gameSvrId = pick('gamesvrentity', 'gameSvr', 'gameSvrId')
    const relaySvrId = pick('relaysvrentity', 'relaySvr', 'relaySvrId')
    if (!gameSvrId || !relaySvrId) throw new Error('回放链接缺少 gamesvrentity 或 relaysvrentity')
    return { kind: 'replay', gameSeq, gameSvrId, relaySvrId, playerId: pick('playerid', 'playerId', 'userId') }
  }
  const userId = pick('userId', 'userid')
  const roleId = pick('roleId', 'roleid')
  if (!/^\d{5,15}$/.test(userId)) throw new Error('面板链接缺少有效的 userId（营地 ID）')
  if (!roleId) throw new Error('面板链接缺少 roleId')
  return {
    kind: 'panel',
    gameSeq,
    userId,
    roleId,
    gameSvrId: pick('gamesvrid', 'gameSvr', 'gameSvrId'),
    relaySvrId: pick('relaysvrid', 'relaySvr', 'relaySvrId'),
    battleType: pick('battletype'),
    pvpType: pick('pvptype')
  }
}

export function CollectPage() {
  const { baseUrl } = useConnection()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const camp = useCampStatus(baseUrl)
  const channels = useChannels(baseUrl)
  const officialReplays = useOfficialReplays(baseUrl)
  const [qr, setQr] = useState<CampQr | null>(null)
  const [qrStatus, setQrStatus] = useState('')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ message: string; error?: boolean } | null>(null)
  const [playersInput, setPlayersInput] = useState('')
  const [entries, setEntries] = useState<CampEntry[]>([])
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [listNote, setListNote] = useState('')
  const [syncNote, setSyncNote] = useState('')
  const [panelLink, setPanelLink] = useState('')
  const [replayLink, setReplayLink] = useState('')
  const [linkBusy, setLinkBusy] = useState(false)
  const [linkNotice, setLinkNotice] = useState<{ message: string; error?: boolean } | null>(null)
  const [linkChannel, setLinkChannel] = useState('')
  const [expandAll, setExpandAll] = useState(false)
  const [openDates, setOpenDates] = useState<Set<string>>(new Set())
  const [syncProgress, setSyncProgress] = useState<{ done: number; total: number } | null>(null)
  const [heroBySeq, setHeroBySeq] = useState<Record<string, string>>({})
  const [passBusy, setPassBusy] = useState(false)
  const heroAttempted = useRef<Set<string>>(new Set())

  const importLinks = async () => {
    if (!panelLink.trim() && !replayLink.trim()) {
      setLinkNotice({ message: '先粘贴至少一条营地链接。', error: true })
      return
    }
    setLinkBusy(true)
    setLinkNotice(null)
    setLinkChannel('')
    try {
      const panel = panelLink.trim() ? parseCampLink(panelLink) : null
      const replay = replayLink.trim() ? parseCampLink(replayLink) : null
      if (panel && panel.kind !== 'panel') throw new Error('第一条链接不是赛后面板链接（mp-redirect）')
      if (replay && replay.kind !== 'replay') throw new Error('第二条链接不是官方回放链接（battle-replay）')
      if (panel && replay && panel.gameSeq !== replay.gameSeq) throw new Error(`两条链接不是同一局：${panel.gameSeq} / ${replay.gameSeq}`)
      let channelId = ''
      if (panel) {
        if (!auth?.authorized) throw new Error('导入赛后面板需要先完成营地授权。')
        await api(baseUrl, '/api/camp/sync', {
          method: 'POST',
          body: {
            campUserId: panel.userId,
            nickname: '链接导入',
            entries: [{
              gameSeq: panel.gameSeq,
              gameSvrId: panel.gameSvrId,
              relaySvrId: panel.relaySvrId,
              battleType: panel.battleType,
              pvpType: panel.pvpType,
              uniqueRoleId: panel.roleId
            }]
          }
        })
        let status: CampSync | null = null
        for (let i = 0; i < 150; i += 1) {
          status = await api<CampSync>(baseUrl, '/api/camp/sync')
          if (!status.running) break
          await new Promise((resolve) => window.setTimeout(resolve, 2000))
        }
        const detail = (status?.details || []).find((item) => String(item.gameSeq) === String(panel.gameSeq) && item.channelId)
        channelId = detail?.channelId || ''
        if (!channelId) {
          const existing = (camp.data?.details || []).find((item) => String(item.gameSeq) === String(panel.gameSeq) && item.channelId)
          channelId = existing?.channelId || ''
        }
        if (!channelId) throw new Error('面板已同步，但没有自动生成通道；请在下面通道列表里查看，或稍后重试。')
      }
      let replayUrl = replayLink.trim()
      let replayError = ''
      if (!replayUrl && panel) replayUrl = replayUrlFromPanel(panel)
      if (replayUrl) {
        const replaySeq = replay?.gameSeq || panel?.gameSeq || ''
        if (!channelId) {
          const existing = (camp.data?.details || []).find((item) => String(item.gameSeq) === String(replaySeq) && item.channelId)
          channelId = existing?.channelId || ''
        }
        if (!channelId) {
          if (panel) throw new Error('面板已同步，但没有自动生成通道；请在下面通道列表里查看。')
          throw new Error('没有找到这一局的面板通道；请先导入赛后十人面板链接，再关联回放。')
        }
        try {
          const imported = await api<{ id?: string }>(baseUrl, '/api/official/replay', { method: 'POST', body: { url: replayUrl } })
          if (!imported?.id) throw new Error('回放没有返回 ID')
          await api(baseUrl, `/api/channels/${encodeURIComponent(channelId)}/official`, { method: 'POST', body: { officialId: imported.id } })
        } catch (error) {
          replayError = error instanceof Error ? error.message : '回放导入失败'
          if (!panel) throw error
        }
      }
      await refreshAll()
      setLinkChannel(channelId)
      setLinkNotice({
        message: replayError
          ? `面板已导入；回放没有导成：${replayError}。可以稍后在校对页补回放。`
          : replayUrl
            ? '本局已导入：十人面板 + 官方回放。'
            : '本局面板已导入；没有回放参数，稍后在校对页补官方回放。',
        error: Boolean(replayError)
      })
    } catch (error) {
      setLinkNotice({ message: error instanceof Error ? error.message : '导入失败', error: true })
    } finally {
      setLinkBusy(false)
    }
  }

  const channelRows = useMemo(() => channels.data || [], [channels.data])
  const auth = camp.data?.auth
  const players = camp.data?.config?.players || []
  const expired = Boolean(auth?.authorized && auth?.expired)

  useEffect(() => {
    if (!qr) return
    const timer = window.setInterval(async () => {
      try {
        const result = await api<CampPoll>(baseUrl, `/api/camp/auth/poll?taskId=${encodeURIComponent(qr.taskId)}`)
        if (result.status === 'waiting') { setQrStatus('等待扫码…'); return }
        if (result.status === 'scanned') { setQrStatus('已扫码，请在手机上确认'); return }
        if (result.status === 'success') {
          setQr(null)
          setQrStatus('')
          setNotice({ message: `授权成功${result.nickname ? `：${result.nickname}` : ''}` })
          await queryClient.invalidateQueries({ queryKey: ['camp-status', baseUrl] })
          return
        }
        if (result.status === 'expired' || result.status === 'canceled' || result.status === 'error') {
          setQr(null)
          setQrStatus('')
          setNotice({ message: result.message || (result.status === 'canceled' ? '已取消扫码' : '二维码已过期，请重新扫码'), error: true })
        }
      } catch (error) {
        setQr(null)
        setQrStatus('')
        setNotice({ message: error instanceof Error ? error.message : '轮询失败', error: true })
      }
    }, 2500)
    return () => window.clearInterval(timer)
  }, [qr, baseUrl, queryClient])

  const channelBySeq = useMemo(() => {
    const map = new Map<string, string>()
    for (const detail of camp.data?.details || []) {
      if (detail.channelId) map.set(String(detail.gameSeq), detail.channelId)
    }
    return map
  }, [camp.data?.details])
  const channelsById = useMemo(() => new Map((channels.data || []).map((channel) => [channel.id, channel])), [channels.data])
  const replayIds = useMemo(() => new Set((officialReplays.data?.replays || []).map((item) => item.id)), [officialReplays.data])
  const entryGroups = useMemo(() => groupEntries(entries), [entries])
  const expiredEntries = entries.filter((entry) => !entry.imported && !channelBySeq.has(String(entry.gameSeq)) && campDetailExpired(entry))
  const selectableEntries = entries.filter((entry) => !entry.imported && !channelBySeq.has(String(entry.gameSeq)) && !campDetailExpired(entry))
  const checkedCount = selectableEntries.filter((entry) => checked[entry.gameSeq]).length

  useEffect(() => {
    let alive = true
    const wanted = entries
      .filter((entry) => !entry.hero && !heroBySeq[entry.gameSeq] && !heroAttempted.current.has(entry.gameSeq))
      .map((entry) => ({ entry, channelId: channelBySeq.get(String(entry.gameSeq)) }))
      .filter((item) => Boolean(item.channelId))
      .slice(0, 20)
    for (const item of wanted) {
      heroAttempted.current.add(item.entry.gameSeq)
      void api<ChannelDetail>(baseUrl, `/api/channels/${encodeURIComponent(item.channelId!)}`)
        .then((channel) => {
          if (!alive) return
          const players = channel.draft?.players || []
          const player = players.find((row) => row.nickname === item.entry.ownerName)
          if (player?.hero) setHeroBySeq((current) => ({ ...current, [item.entry.gameSeq]: player.hero! }))
        })
        .catch(() => {})
    }
    return () => { alive = false }
  }, [entries, channelBySeq, baseUrl, heroBySeq])

  if (camp.isLoading) return <SkeletonPage cards={3} />
  if (camp.isError || !camp.data) {
    return <div className="page"><ErrorState error={camp.error} onRetry={() => void camp.refetch()} /></div>
  }

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['camp-status', baseUrl] }),
      queryClient.invalidateQueries({ queryKey: ['channels', baseUrl] }),
      queryClient.invalidateQueries({ queryKey: ['overview', baseUrl] }),
      queryClient.invalidateQueries({ queryKey: ['matches', baseUrl] }),
      queryClient.invalidateQueries({ queryKey: ['player-board', baseUrl] })
    ])
  }

  const startQr = async () => {
    setBusy('qr')
    setNotice(null)
    try {
      const result = await api<CampQr>(baseUrl, '/api/camp/auth/qr', { method: 'POST' })
      setQr(result)
      setQrStatus('等待扫码…')
    } catch (error) {
      setNotice({ message: error instanceof Error ? error.message : '二维码生成失败', error: true })
    } finally {
      setBusy('')
    }
  }

  const cancelQr = async () => {
    if (!qr) return
    try { await api(baseUrl, `/api/camp/auth/cancel?taskId=${encodeURIComponent(qr.taskId)}`, { method: 'POST' }) } catch {}
    setQr(null)
    setQrStatus('')
  }

  const checkAuth = async () => {
    setBusy('check')
    setNotice(null)
    try {
      const result = await api<{ valid?: boolean | null; reason?: string; checkedAt?: string }>(baseUrl, '/api/camp/auth/check?force=1', { method: 'POST' })
      setNotice({
        message: result.valid === false
          ? (result.reason || '营地授权已失效，请补充授权。')
          : result.valid === true
            ? '营地授权有效。'
            : (result.reason || '暂时无法完成检测，不影响本地数据。'),
        error: result.valid === false
      })
      await queryClient.invalidateQueries({ queryKey: ['camp-status', baseUrl] })
    } catch (error) {
      setNotice({ message: error instanceof Error ? error.message : '检测失败', error: true })
    } finally {
      setBusy('')
    }
  }

  const clearAuth = async () => {
    if (!window.confirm('删除本机的营地登录凭证？已入库的数据不受影响。')) return
    setBusy('clear')
    try {
      await api(baseUrl, '/api/camp/auth/clear', { method: 'POST' })
      setNotice({ message: '已删除营地凭证。' })
      await queryClient.invalidateQueries({ queryKey: ['camp-status', baseUrl] })
    } catch (error) {
      setNotice({ message: error instanceof Error ? error.message : '删除失败', error: true })
    } finally {
      setBusy('')
    }
  }

  const addPlayers = async () => {
    const tokens = playersInput.split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean)
    if (!tokens.length) return
    setBusy('player')
    const next = [...players]
    const added: string[] = []
    const failed: string[] = []
    try {
      for (const token of tokens) {
        try {
          let campUserId = token
          let nickname = ''
          if (!/^\d{5,15}$/.test(token)) {
            const resolved = await api<{ userId?: string; nickname?: string }>(baseUrl, '/api/camp/resolve', { method: 'POST', body: { url: token } })
            campUserId = String(resolved.userId || '')
            nickname = resolved.nickname || ''
            if (!/^\d{5,15}$/.test(campUserId)) throw new Error('链接里没有营地 ID')
          }
          if (next.some((player) => player.campUserId === campUserId)) {
            failed.push(`${campUserId}（已存在）`)
            continue
          }
          const player: CampPlayer = { campUserId, nickname: nickname || `选手 ${campUserId.slice(-4)}` }
          next.push(player)
          added.push(player.nickname)
        } catch (error) {
          failed.push(`${token.slice(0, 16)}：${error instanceof Error ? error.message : '解析失败'}`)
        }
      }
      if (added.length) {
        await api(baseUrl, '/api/camp/config', { method: 'POST', body: { players: next } })
        setPlayersInput('')
        await queryClient.invalidateQueries({ queryKey: ['camp-status', baseUrl] })
      }
      setNotice({
        message: [added.length ? `已添加 ${added.length} 位：${added.join('、')}` : '', failed.length ? `${failed.length} 个没成功：${failed.slice(0, 2).join('；')}` : ''].filter(Boolean).join('；') || '没有可添加的内容。',
        error: !added.length && failed.length > 0
      })
    } catch (error) {
      setNotice({ message: error instanceof Error ? error.message : '保存白名单失败', error: true })
    } finally {
      setBusy('')
    }
  }

  const removePlayer = async (campUserId: string) => {
    setBusy('player')
    try {
      const next = players.filter((player) => player.campUserId !== campUserId)
      await api(baseUrl, '/api/camp/config', { method: 'POST', body: { players: next } })
      await queryClient.invalidateQueries({ queryKey: ['camp-status', baseUrl] })
      setNotice({ message: '已移除该选手。' })
    } catch (error) {
      setNotice({ message: error instanceof Error ? error.message : '移除失败', error: true })
    } finally {
      setBusy('')
    }
  }

  const pullList = async () => {
    if (!players.length) { setNotice({ message: '先添加营地选手，再拉取对局。', error: true }); return }
    setBusy('pull')
    setEntries([])
    setChecked({})
    setListNote('正在读取营地最近对局…')
    setNotice(null)
    const merged = new Map<string, CampEntry>()
    const problems: string[] = []
    let authProblem = ''
    try {
      for (const player of players) {
        try {
          let lastTime = 0
          let pages = 0
          let hasMore = true
          while (hasMore && pages < 20) {
            pages += 1
            setListNote(`正在读取 ${player.nickname} 第 ${pages} 页…`)
            const result = await api<CampListResult>(baseUrl, '/api/camp/list', { method: 'POST', body: { campUserId: player.campUserId, lastTime } })
            for (const entry of result.entries || []) {
              const existing = merged.get(entry.gameSeq)
              if (existing) {
                existing.owners = [...(existing.owners || []), player.nickname]
                continue
              }
              merged.set(entry.gameSeq, { ...entry, ownerName: player.nickname, ownerCampUserId: player.campUserId, owners: [player.nickname] })
            }
            if (result.gaming) problems.push(`${player.nickname} 有一局进行中，未包含在列表里`)
            hasMore = Boolean(result.hasMore)
            const next = Number(result.lastTime || 0)
            if (!hasMore || !next || next === lastTime) break
            lastTime = next
            await new Promise((resolve) => window.setTimeout(resolve, 250))
          }
          if (hasMore) problems.push(`${player.nickname} 只读取了最近 20 页`)
        } catch (error) {
          problems.push(`${player.nickname}：${error instanceof Error ? error.message : '读取失败'}`)
          const authInvalid = Boolean((error as { authInvalid?: boolean })?.authInvalid)
          if (authInvalid) {
            authProblem = (error as Error).message
            break
          }
        }
      }
      const next = [...merged.values()].sort((a, b) => entryMoment(b) - entryMoment(a))
      const withChannel = new Set((camp.data?.details || []).filter((detail) => detail.channelId).map((detail) => String(detail.gameSeq)))
      const autoChecked: Record<string, boolean> = {}
      let skippedExpired = 0
      for (const entry of next) {
        if (withChannel.has(String(entry.gameSeq)) || entry.imported) continue
        if (campDetailExpired(entry)) { skippedExpired += 1; continue }
        autoChecked[entry.gameSeq] = true
      }
      setEntries(next)
      setOpenDates(new Set(groupEntries(next).slice(0, 1).map((group) => group.key)))
      setExpandAll(false)
      setChecked(autoChecked)
      if (skippedExpired) problems.push(`${skippedExpired} 局营地无详情（超过一个月），已自动跳过，请用截图/录屏补录`)
      setListNote(problems.join('；') || `拉到 ${next.length} 局，已自动勾选可入库的。`)
      if (authProblem) {
        setNotice({ message: `营地授权已失效，拉取已停止：${authProblem}`, error: true })
        await queryClient.invalidateQueries({ queryKey: ['camp-status', baseUrl] })
      }
    } catch (error) {
      setListNote('')
      setNotice({ message: error instanceof Error ? error.message : '拉取失败', error: true })
    } finally {
      setBusy('')
    }
  }

  const passChannelList = async (list: ChannelSummary[]) => {
    let ok = 0
    let failed = 0
    for (const channel of list) {
      if (channel.saved?.status === 'saved') continue
      try {
        // 用户要求：不再强制复核；保存接口本身不校验复核，直接写正式统计。
        await api(baseUrl, `/api/channels/${encodeURIComponent(channel.id)}/save`, { method: 'POST' })
        ok += 1
      } catch {
        failed += 1
      }
    }
    return { ok, failed }
  }

  const autoPassComplete = async () => {
    try {
      const data = await api<{ channels: ChannelSummary[] }>(baseUrl, '/api/channels')
      const passable = (data.channels || []).filter((channel) =>
        channel.saved?.status !== 'saved'
        && channel.sourceStatus?.complete === true
        && !(channel.missing?.length)
      )
      if (!passable.length) return { ok: 0, failed: 0 }
      const result = await passChannelList(passable)
      await refreshAll()
      return result
    } catch {
      return { ok: 0, failed: 0 }
    }
  }

  const passAllAudit = async () => {
    const audit = channelRows.filter((channel) => channel.saved?.status !== 'saved')
    if (!audit.length) return
    if (!window.confirm(`将一键通过 ${audit.length} 局未入库对局；仍有缺失值的字段会保持为空。确定继续吗？`)) return
    setPassBusy(true)
    const result = await passChannelList(audit)
    await refreshAll()
    setPassBusy(false)
    if (result.ok) {
      pushToast(`已通过 ${result.ok} 局`, 'success')
      void window.kpl.notify({ title: '缺失值审查', body: `已通过 ${result.ok} 局` })
    }
    if (result.failed) pushToast(`${result.failed} 局没有通过：后端仍要求补齐材料，请打开逐项检查`, 'error')
  }

  const importSelected = async () => {
    const chosen = entries.filter((entry) => checked[entry.gameSeq] && !campDetailExpired(entry) && !entry.imported)
    if (!chosen.length) { setNotice({ message: '先勾选要入库的对局；超过一个月的局营地无详情，请走截图/录屏。', error: true }); return }
    const groups = new Map<string, { nickname: string; entries: CampEntry[] }>()
    for (const entry of chosen) {
      const key = entry.ownerCampUserId || ''
      if (!groups.has(key)) groups.set(key, { nickname: entry.ownerName || '', entries: [] })
      groups.get(key)!.entries.push(entry)
    }
    setSyncProgress({ done: 0, total: chosen.length })
    setBusy('sync')
    setSyncNote(`已提交 ${chosen.length} 局，后台同步中…`)
    setNotice(null)
    const baseDetails = Number(camp.data?.detailsCount || 0)
    try {
      for (const [campUserId, group] of groups) {
        await api(baseUrl, '/api/camp/sync', {
          method: 'POST',
          body: {
            campUserId,
            nickname: group.nickname,
            entries: group.entries.map((entry) => ({
              gameSeq: entry.gameSeq,
              dtEventTime: entry.dtEventTime,
              usedTime: entry.usedTime,
              mapName: entry.mapName,
              gametime: entry.gametime,
              battleType: entry.battleType,
              winCamp: entry.winCamp,
              gameSvrId: entry.gameSvrId,
              relaySvrId: entry.relaySvrId,
              uniqueRoleId: entry.uniqueRoleId,
              killcnt: entry.killcnt,
              deadcnt: entry.deadcnt,
              assistcnt: entry.assistcnt
            }))
          }
        })
        let status: CampSync | null = null
        for (let i = 0; i < 600; i += 1) {
          status = await api<CampSync>(baseUrl, '/api/camp/sync')
          if (!status.running) break
          const completed = new Set((status.details || []).map((detail) => String(detail.gameSeq)))
          const saved = chosen.filter((entry) => completed.has(String(entry.gameSeq))).length
          const added = Math.max(0, Number(status.detailsCount || 0) - baseDetails)
          const done = Math.min(chosen.length, Math.max(saved, added))
          setSyncProgress({ done, total: chosen.length })
          setSyncNote(`正在同步 ${group.nickname}：已处理 ${done} / ${chosen.length} 局…`)
          await new Promise((resolve) => window.setTimeout(resolve, 2000))
        }
        if (status?.running) throw new Error('同步仍在进行，请稍后在通道列表查看结果。')
        const authFailure = (status?.result?.players || []).find((item) => item.authInvalid)
        if (authFailure) throw new Error(authFailure.reason || '营地授权已失效，这次入库没有完成')
      }
      const message = `营地同步完成：已入库 ${chosen.length} 局`
      setSyncProgress({ done: chosen.length, total: chosen.length })
      pushToast(message, 'success')
      void window.kpl.notify({ title: '赛训台 · 营地同步完成', body: message })
      setEntries([])
      setChecked({})
      setSyncNote('')
      setNotice({ message: '所选对局已入库；无缺失的已自动通过，有缺失的进入缺失值审查。' })
      const autoPassed = await autoPassComplete()
      await refreshAll()
      if (autoPassed.ok) pushToast(`无缺失值自动通过 ${autoPassed.ok} 局`, 'success')
      window.setTimeout(() => setSyncProgress(null), 1800)
    } catch (error) {
      const message = error instanceof Error ? error.message : '入库失败'
      setSyncProgress(null)
      setSyncNote('')
      setNotice({ message, error: true })
      pushToast(`营地同步失败：${message}`, 'error')
      void window.kpl.notify({ title: '赛训台 · 营地同步失败', body: message })
      await refreshAll()
    } finally {
      setBusy('')
    }
  }

  const openOcr = async () => {
    try {
      const result = await window.kpl.openWorkbenchPage({ baseUrl, route: '#capture' })
      if (!result.ok) pushToast(result.error || '工作台没有打开', 'error')
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '工作台没有打开', 'error')
    }
  }

  const repairTargets = entries.filter((entry) => {
    if (!entry.imported || !entry.gameSvrId || !entry.relaySvrId) return false
    return !replayIds.has(`camp-${entry.gameSeq}`)
  })

  const repairReplays = async () => {
    if (!repairTargets.length) return
    setBusy('repair')
    setNotice(null)
    let ok = 0
    let failed = 0
    let firstError = ''
    for (const entry of repairTargets) {
      const channelId = channelBySeq.get(String(entry.gameSeq))
      if (!channelId) { failed += 1; continue }
      let lastError: unknown = null
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const replay = await api<{ id?: string }>(baseUrl, '/api/official/replay', {
            method: 'POST',
            body: { url: replayUrlFromEntry(entry) },
            timeout: 120_000
          })
          if (!replay?.id) throw new Error('回放没有返回 ID')
          await api(baseUrl, `/api/channels/${encodeURIComponent(channelId)}/official`, {
            method: 'POST',
            body: { officialId: replay.id }
          })
          ok += 1
          lastError = null
          setNotice({ message: `正在补官方回放：${ok + failed} / ${repairTargets.length} 局…` })
          break
        } catch (error) {
          lastError = error
          if (attempt === 0) await new Promise((resolve) => window.setTimeout(resolve, 800))
        }
      }
      if (lastError !== null) {
        failed += 1
        if (!firstError) firstError = lastError instanceof Error ? lastError.message : '回放导入失败'
      }
    }
    await queryClient.invalidateQueries({ queryKey: ['official-replays', baseUrl] })
    await refreshAll()
    setBusy('')
    setNotice({
      message: failed
        ? `已补 ${ok} 局官方回放；${failed} 局失败${firstError ? `（${firstError}）` : ''}`
        : `已补 ${ok} 局官方回放，刷新后单局分析可用。`,
      error: failed > 0
    })
    if (ok) pushToast(`已补 ${ok} 局官方回放`, 'success')
  }

  const pendingChannels = channelRows.filter((channel) => channel.saved?.status !== 'saved').length
  const lastSync = (camp.data?.details || []).reduce((max, detail) => Math.max(max, Number(detail.syncedAt) || 0), 0)

  const renderEntry = (entry: CampEntry) => {
    const channelId = channelBySeq.get(String(entry.gameSeq))
    const channel = channelId ? channelsById.get(channelId) : undefined
    const replayOn = replayIds.has(`camp-${entry.gameSeq}`)
    const panelOn = Boolean(entry.imported)
    const inReview = Boolean(channelId) || Boolean(entry.channelReady)
    const expiredEntry = !panelOn && !inReview && campDetailExpired(entry)
    const selectable = !panelOn && !inReview && !expiredEntry
    const hero = entry.hero || entry.heroName || heroBySeq[entry.gameSeq]
    const heroIcon = entry.heroIcon ? assetUrl(baseUrl, entry.heroIcon) : ''
    return (
      <label className={`camp-entry${checked[entry.gameSeq] && selectable ? ' is-checked' : ''}${expiredEntry ? ' is-expired' : ''}`} key={entry.gameSeq}>
        <input type="checkbox" checked={selectable && Boolean(checked[entry.gameSeq])} disabled={!selectable} onChange={(event) => setChecked((current) => ({ ...current, [entry.gameSeq]: event.target.checked }))} />
        <span className="camp-entry-hero">{hero ? <Portrait name={hero} size="sm" /> : heroIcon ? <img className="camp-hero-img" src={heroIcon} alt="英雄" loading="lazy" /> : <span className="camp-hero-empty" title="英雄随十人面板入库后显示"><Icon name="heroes" size={13} /></span>}</span>
        <span className="camp-entry-date">{entryClock(entry)}</span>
        <b className="camp-entry-map">{entry.mapName || entry.battleType || '训练赛'}</b>
        <span className="camp-entry-kda">{number(entry.killcnt)} / {number(entry.deadcnt)} / {number(entry.assistcnt)}</span>
        <span className="quiet">{fmtDuration(entry.usedTime)}</span>
        <span className="camp-entry-owner">{entry.ownerName || '—'}</span>
        <span className="camp-flags">
          <span className={`camp-flag ${panelOn ? 'is-on' : 'is-off'}`} title={panelOn ? '赛后十人面板已入库' : '赛后十人面板未入库'}>{panelOn ? '赛后 ✓' : '赛后 –'}</span>
          <span className={`camp-flag ${replayOn ? 'is-on' : channelId ? 'is-off' : 'is-unknown'}`} title={replayOn ? '官方回放已关联' : channelId ? '官方回放未关联' : '还没有通道，无法判断回放'}>{replayOn ? '回放 ✓' : channelId ? '回放 –' : '回放 ?'}</span>
        </span>
      </label>
    )
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="CAMP · INGEST"
        title={<>营地采集<em>授权一次，之后每天拉取最近的战绩；客户端只接入王者营地</em></>}
        subtitle="拉取后无缺失值自动入库；营地只保留最近一个月的对局详情，更早的局请用截图/录屏 OCR（工作台）。"
        meta={[
          auth?.authorized ? (expired ? '授权已失效' : '营地已授权') : '未授权',
          `${players.length} 位选手`,
          `${pendingChannels} 个待审查`,
          lastSync ? `上次同步 ${new Date(lastSync * 1000).toLocaleDateString('zh-CN')}` : '还没有同步记录'
        ].map((text) => <span key={text}>{text}</span>)}
        actions={<><button type="button" className="btn" onClick={() => void openOcr()}>截图/录屏补录 <Icon name="external" /></button><button type="button" className="btn" onClick={() => void window.kpl.openExternal(baseUrl)}>打开工作台 <Icon name="external" /></button></>}
      />

      <section className="card">
        <div className="card-head"><div><h2 className="card-title">营地链接导入</h2><div className="card-sub">赛后十人面板（mp-redirect）和官方回放（battle-replay）分两条链接；用 gameSeq 自动配对。</div></div><span className="badge">同局导入</span></div>
        <div className="card-body link-import">
          <div className="field">
            <label htmlFor="panel-link">赛后十人面板链接</label>
            <textarea id="panel-link" className="input" rows={3} value={panelLink} onChange={(event) => setPanelLink(event.target.value)} placeholder="https://camp.qq.com/h5/webdist/mp-redirect/index.html?userId=...&gameSeq=..." spellCheck={false} />
            <small className="quiet">走营地授权，拿到十人终局面板；是审核的终局数据。</small>
          </div>
          <div className="field">
            <label htmlFor="replay-link">官方回放链接（可留空）</label>
            <textarea id="replay-link" className="input" rows={3} value={replayLink} onChange={(event) => setReplayLink(event.target.value)} placeholder="https://camp.qq.com/h5/webdist/battle-replay/index.html?gameseq=..." spellCheck={false} />
            <small className="quiet">可留空：只贴面板链接时，客户端会用 userId 作为 playerId 自动补回放。</small>
          </div>
          <div className="link-import-foot">
            <p>只贴赛后十人面板链接也能一次采集两种数据；官方回放链接用于覆盖 playerId 或导入旧局回放。</p>
            <div className="row">
              <button type="button" className="btn btn-primary" disabled={linkBusy} onClick={() => void importLinks()}>{linkBusy ? '正在导入…' : '导入本局'}</button>
              {linkChannel ? <Link className="btn" to={`/collect/${encodeURIComponent(linkChannel)}`}>去校对 <Icon name="arrow" /></Link> : null}
            </div>
          </div>
          {linkNotice ? <div className={`connect-status${linkNotice.error ? ' is-error' : ' is-ok'}`}>{linkNotice.message}</div> : null}
        </div>
      </section>

      <div className="collect-grid">
        <section className="card">
          <div className="card-head"><div><h2 className="card-title">营地连接</h2><div className="card-sub">凭证只存在本机；授权失效时拉取会暂停。</div></div><span className={`badge ${expired ? 'badge-loss' : auth?.authorized ? 'badge-win' : ''}`}>{expired ? '已失效' : auth?.authorized ? '已授权' : '未授权'}</span></div>
          <div className="card-body stack">
            {auth?.authorized ? (
              <div className={`camp-auth${expired ? ' is-stale' : ''}`}>
                <span className="camp-dot" />
                <div><b>{auth.nickname || '已登录'}</b><small>营地 ID {auth.userId || '—'}{auth.loginAt ? ` · 授权于 ${stamp(auth.loginAt)}` : ''}{auth.checkedAt ? ` · 最近检测 ${stamp(auth.checkedAt)}` : ''}</small></div>
                <span className={`badge ${expired ? 'badge-loss' : 'badge-win'}`}>{expired ? '失效' : '有效'}</span>
              </div>
            ) : (
              <div className="camp-auth is-off"><span className="camp-dot" /><div><b>还没有营地凭证</b><small>扫码授权后才能拉取选手的最近对局</small></div><span className="badge">未授权</span></div>
            )}
            {expired ? <div className="notice"><Icon name="alert" size={15} /><span><b>营地授权已失效，拉取已暂停。</b>{auth?.reason || '重新扫码补充授权后即可继续拉取；已入库数据不受影响。'}</span></div> : null}
            {qr ? (
              <div className="camp-qr">
                <img src={`data:image/png;base64,${qr.qrcodeBase64}`} alt="营地授权二维码" />
                <div><b>用王者营地 App 扫码</b><p>{qrStatus || '等待扫码…'}</p><button type="button" className="btn btn-sm" onClick={() => void cancelQr()}>取消这次授权</button></div>
              </div>
            ) : (
              <div className="row" style={{ flexWrap: 'wrap' }}>
                <button type="button" className={`btn ${expired || !auth?.authorized ? 'btn-primary' : ''}`} disabled={busy === 'qr'} onClick={() => void startQr()}>{busy === 'qr' ? '正在生成…' : expired ? '补充授权' : auth?.authorized ? '重新扫码' : '扫码授权'}</button>
                {auth?.authorized ? <button type="button" className="btn" disabled={busy === 'check'} onClick={() => void checkAuth()}>{busy === 'check' ? '检测中…' : '检测授权'}</button> : null}
                {auth?.authorized ? <button type="button" className="btn btn-ghost" disabled={busy === 'clear'} onClick={() => void clearAuth()}>删除凭证</button> : null}
              </div>
            )}
            {notice ? <div className={`connect-status${notice.error ? ' is-error' : ' is-ok'}`}>{notice.message}</div> : null}
          </div>
        </section>

        <section className="card">
          <div className="card-head"><div><h2 className="card-title">选手白名单</h2><div className="card-sub">一行一个营地 ID，也可以粘贴分享链接；链接会自动解析。</div></div><span className="badge">{number(players.length)} 位</span></div>
          <div className="card-body stack">
            {players.length ? (
              <div className="camp-player-list">
                {players.map((player) => (
                  <div className="camp-player" key={player.campUserId}>
                    <span className="camp-avatar">{player.nickname.slice(0, 1)}</span>
                    <div><b>{player.nickname}</b><small>{player.campUserId}</small></div>
                    <button type="button" className="icon-btn is-danger" onClick={() => void removePlayer(player.campUserId)} aria-label={`移除 ${player.nickname}`}><Icon name="close" /></button>
                  </div>
                ))}
              </div>
            ) : <div className="empty-state"><b>还没有绑定选手</b><p>绑定一位每场都上的选手就够；一局详情自带双方十人面板。</p></div>}
            <div className="field">
              <label htmlFor="camp-identities">添加营地 ID 或分享链接</label>
              <textarea id="camp-identities" className="input" rows={3} value={playersInput} onChange={(event) => setPlayersInput(event.target.value)} placeholder="1000000001&#10;https://camp.qq.com/...&userId=..." spellCheck={false} />
            </div>
            <div className="row"><button type="button" className="btn btn-primary" disabled={busy === 'player' || !playersInput.trim()} onClick={() => void addPlayers()}>{busy === 'player' ? '正在解析…' : '批量添加'}</button><span className="quiet" style={{ fontSize: 10 }}>每位选手只做一次</span></div>
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head"><div><h2 className="card-title">拉取对局</h2><div className="card-sub">{players.length ? '读取白名单选手的最近战绩，勾选后入库；已入库的会自动排除。' : '先在右侧绑定选手，再拉取。'}</div></div><div className="row">{repairTargets.length ? <button type="button" className="btn" disabled={busy === 'repair'} onClick={() => void repairReplays()}>{busy === 'repair' ? '正在补齐…' : `补齐官方回放 ${repairTargets.length} 局`}</button> : null}<button type="button" className="btn" disabled={busy === 'pull' || !players.length || expired} onClick={() => void pullList()}>{busy === 'pull' ? '正在拉取…' : '拉取对局'}</button><button type="button" className="btn btn-primary" disabled={busy === 'sync' || !checkedCount} onClick={() => void importSelected()}>{busy === 'sync' ? '正在入库…' : `入库所选 ${checkedCount} 局`}</button></div></div>
        <div className="card-body stack">
          {listNote ? <div className="notice"><Icon name="info" size={15} /><span>{listNote}</span></div> : null}
          {syncNote ? <div className="notice"><Icon name="refresh" size={15} /><span>{syncNote}</span></div> : null}
          {syncProgress ? <div className="import-progress"><div><span>{busy === 'sync' ? '正在入库' : '入库进度'}</span><b>{syncProgress.done} / {syncProgress.total} 局</b></div><div className="progress-track"><i style={{ width: `${syncProgress.total ? Math.min(100, (syncProgress.done / syncProgress.total) * 100) : 0}%` }} /></div><p>入库在后台进行，可以切换到其他页面；完成后会提醒。</p></div> : null}
          {camp.data.running && busy !== 'sync' ? <div className="notice"><Icon name="refresh" size={15} /><span>工作台正在后台同步，完成后会提醒。</span></div> : null}
          {entries.length ? (
            <>
              <div className="camp-entry-head">
                <label className="check"><input type="checkbox" checked={selectableEntries.length > 0 && checkedCount === selectableEntries.length} onChange={(event) => { const next: Record<string, boolean> = {}; if (event.target.checked) selectableEntries.forEach((entry) => { next[entry.gameSeq] = true }); setChecked(next) }} /> 全选</label>
                <span>{entries.length} 局 · 可入库 {selectableEntries.length} · 已选 {checkedCount} 局{expiredEntries.length ? ` · 营地无详情 ${expiredEntries.length}` : ''} · 按日期折叠</span>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setExpandAll((value) => !value)}>{expandAll ? '收起日期' : '展开全部日期'}</button>
              </div>
              <p className="camp-list-note">赛后 = 十人面板已拉取；回放 = 官方回放已关联。英雄图标在面板入库后显示；未入库行等列表接口补 heroId。</p>
              {expiredEntries.length ? <div className="notice"><Icon name="alert" size={15} /><span><b>{expiredEntries.length} 局营地无详情</b>：营地只保留最近一个月的对局详情（手机营地 App 里也打不开）。这些局请用同一局七张截图 + 完整录屏走 OCR 补录。</span><button type="button" className="btn btn-sm" onClick={() => void openOcr()}>去工作台补录 →</button></div> : null}
              <div className="camp-day-list">
                {entryGroups.map((group, index) => (
                  <details className="camp-day" key={group.key} open={expandAll || openDates.has(group.key)} onToggle={(event) => { const open = event.currentTarget.open; setOpenDates((current) => { const next = new Set(current); if (open) next.add(group.key); else next.delete(group.key); return next }) }}>
                    <summary><b>{group.key}</b><span>{group.entries.length} 局</span></summary>
                    <div className="camp-entry-list">{group.entries.map(renderEntry)}</div>
                  </details>
                ))}
              </div>
            </>
          ) : <div className="empty-state"><b>还没有拉取结果</b><p>绑定选手后点「拉取对局」，可入库的会默认勾选（超过一个月的除外）。</p></div>}
        </div>
      </section>

      <section className="card">
        <div className="card-head"><div><h2 className="card-title">缺失值审查</h2><div className="card-sub">只列未入库的对局；无缺失值会自动通过，有缺失才需要在这里处理。</div></div><div className="row"><span className="badge">{number(channelRows.filter((channel) => channel.saved?.status !== 'saved').length)} 待审查</span><button type="button" className="btn btn-sm" disabled={passBusy || !channelRows.some((channel) => channel.saved?.status !== 'saved')} onClick={() => void passAllAudit()}>{passBusy ? '通过中…' : '一键通过'}</button></div></div>
        {channels.isLoading ? <div className="card-body"><div className="skeleton skeleton-card" /></div> : (
          <div className="camp-channel-list">
            {channelRows.filter((channel) => channel.saved?.status !== 'saved').map((channel) => {
              const state = channelState(channel)
              const missingCount = (channel.sourceStatus?.missing?.length || 0) + (Array.isArray(channel.missing) ? channel.missing.length : 0)
              return (
                <Link className="camp-channel" to={`/collect/${encodeURIComponent(channel.id)}`} key={channel.id}>
                  <span className="camp-channel-hero">{channel.match?.heroName ? <Portrait name={channel.match.heroName} size="sm" /> : channel.match?.heroIcon ? <img className="camp-hero-img" src={assetUrl(baseUrl, channel.match.heroIcon)} alt="英雄" loading="lazy" /> : null}</span>
                  <div className="camp-channel-main"><b>{channel.match?.opponent ? `对阵 ${channel.match.opponent}` : '对手未标注'}</b><small>{[shortDate(channel.match?.date), channel.match?.session, channel.match?.mode].filter(Boolean).join(' · ')}</small></div>
                  <span className="camp-channel-score">{scoreOf(channel.match)}</span>
                  <span className={`badge ${state.tone}`}>{state.label}</span>
                  <span className={`quiet ${missingCount ? 'is-warn' : ''}`}>{missingCount ? `缺 ${missingCount} 项` : '材料齐'}</span>
                  <span className="camp-channel-arrow">→</span>
                </Link>
              )
            })}
            {!channelRows.some((channel) => channel.saved?.status !== 'saved') ? <div className="empty-state"><b>没有待审查的对局</b><p>无缺失值的对局会自动入库；同步新数据后，有缺失的才会出现在这里。</p></div> : null}
          </div>
        )}
      </section>
    </div>
  )
}
