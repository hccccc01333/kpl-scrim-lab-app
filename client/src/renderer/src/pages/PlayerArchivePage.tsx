import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { usePlayersBoard } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { playerPath } from '../lib/routes'
import {
  PLAYER_LANES,
  formLabel,
  formTone,
  laneIndex,
  playerCsv,
  scoreTier,
  sideName,
  type PlayerLane
} from '../lib/analysis/players'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid, TierBadge } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'
import type { BoardPlayer } from '../lib/types'

const SORTS = [
  { key: 'score', label: '表现分' },
  { key: 'kda', label: 'KDA' },
  { key: 'winRate', label: '胜率' },
  { key: 'games', label: '局数' },
  { key: 'damageShare', label: '输出占比' },
  { key: 'mvp', label: 'MVP' }
] as const

type SortKey = (typeof SORTS)[number]['key']
type SideFilter = 'all' | 'own' | 'enemy'
type BoundFilter = 'all' | 'bound' | 'unbound'

export function PlayerArchivePage() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  const [search, setSearch] = useState('')
  const [side, setSide] = useState<SideFilter>('all')
  const [lane, setLane] = useState('')
  const [bound, setBound] = useState<BoundFilter>('all')
  const [minGames, setMinGames] = useState(1)
  const [sort, setSort] = useState<SortKey>('score')
  const [layout, setLayout] = useState<'grid' | 'list'>('grid')
  const [page, setPage] = useState(0)
  const board = query.data

  const filtered = useMemo(() => {
    if (!board) return []
    const keyword = search.trim().toLowerCase()
    return board.players
      .filter((player) => {
        if (keyword && !player.name.toLowerCase().includes(keyword)) return false
        if (side !== 'all' && player.side !== side) return false
        if (lane && player.lane !== lane) return false
        if (bound === 'bound' && !player.bound) return false
        if (bound === 'unbound' && player.bound) return false
        if (player.games < minGames) return false
        return true
      })
      .sort((a, b) => (b[sort] as number || 0) - (a[sort] as number || 0) || b.games - a.games)
  }, [board, search, side, lane, bound, minGames, sort])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !board) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const pageSize = 32
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(page, pages - 1)
  const visible = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize)
  const leaderPool = board.players.filter((player) => player.games >= 2)
  const minThree = board.players.filter((player) => player.games >= 3)
  const leaders = [
    { label: '最高表现分', player: [...(leaderPool.length ? leaderPool : board.players)].sort((a, b) => (b.score || 0) - (a.score || 0))[0], value: (player: BoardPlayer) => player.score ?? '—', digits: 1 },
    { label: '最高 KDA', player: [...minThree].sort((a, b) => (b.kda || 0) - (a.kda || 0))[0], value: (player: BoardPlayer) => player.kda ?? '—', digits: 2 },
    { label: '最高输出占比', player: [...minThree].sort((a, b) => (b.damageShare || 0) - (a.damageShare || 0))[0], value: (player: BoardPlayer) => player.damageShare ?? '—', digits: 1 },
    { label: '最高胜率', player: [...minThree].sort((a, b) => (b.winRate || 0) - (a.winRate || 0))[0], value: (player: BoardPlayer) => player.winRate ?? '—', digits: 1 }
  ]
  const ownCount = board.players.filter((player) => player.side === 'own').length
  const unbound = board.players.filter((player) => !player.bound).length

  const download = () => {
    const blob = new Blob([`\ufeff${playerCsv(filtered)}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '选手档案.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="PLAYER ARCHIVE"
        title="选手档案"
        subtitle="逐人档案卡；点卡片进个人页看同位置分位、关键局、搭档与英雄池。"
        actions={<>
          <button type="button" className="btn" onClick={download}><Icon name="copy" />导出 CSV</button>
          <Link className="btn" to="/players/compare">选手对比</Link>
        </>}
      />

      <StatGrid items={[
        { label: '选手总数', value: number(board.players.length), note: `本队 ${ownCount} · 对手 ${board.players.length - ownCount}` },
        { label: '有 2 局以上', value: number(board.players.filter((player) => player.games >= 2).length), note: '可做基础比较' },
        { label: '已认领', value: number(board.players.filter((player) => player.bound).length), note: `${unbound} 个昵称待认领` },
        { label: '筛选命中', value: number(filtered.length), note: '随筛选实时变化' }
      ]} />

      <div className="leader-strip">
        {leaders.map((leader) => leader.player ? (
          <Link to={playerPath(leader.player.name)} key={leader.label} className="leader-chip">
            <small>{leader.label}</small>
            <b>{leader.player.name}</b>
            <span>{leader.value(leader.player)}</span>
          </Link>
        ) : null)}
      </div>

      <div className="board-toolbar">
        <input
          className="board-search"
          value={search}
          onChange={(event) => { setSearch(event.target.value); setPage(0) }}
          placeholder="搜索选手昵称"
          aria-label="搜索选手"
        />
        <div className="segmented">
          {(['all', 'own', 'enemy'] as SideFilter[]).map((value) => (
            <button type="button" key={value} className={side === value ? 'is-active' : ''} onClick={() => { setSide(value); setPage(0) }}>
              {value === 'all' ? '全部' : sideName(value)}
            </button>
          ))}
        </div>
        <select value={lane} onChange={(event) => { setLane(event.target.value); setPage(0) }} aria-label="分路">
          <option value="">全部分路</option>
          {PLAYER_LANES.map((item) => <option value={item} key={item}>{item}</option>)}
        </select>
        <select value={bound} onChange={(event) => { setBound(event.target.value as BoundFilter); setPage(0) }} aria-label="认领状态">
          <option value="all">全部认领状态</option>
          <option value="bound">已认领</option>
          <option value="unbound">待认领</option>
        </select>
        <select value={minGames} onChange={(event) => { setMinGames(Number(event.target.value)); setPage(0) }} aria-label="最少局数">
          {[1, 2, 3, 5, 10].map((value) => <option value={value} key={value}>≥{value} 局</option>)}
        </select>
        <select value={sort} onChange={(event) => setSort(event.target.value as SortKey)} aria-label="排序">
          {SORTS.map((item) => <option value={item.key} key={item.key}>按{item.label}</option>)}
        </select>
        <div className="segmented">
          <button type="button" className={layout === 'grid' ? 'is-active' : ''} onClick={() => setLayout('grid')}>卡片</button>
          <button type="button" className={layout === 'list' ? 'is-active' : ''} onClick={() => setLayout('list')}>列表</button>
        </div>
      </div>

      <AnalysisSection title={`档案 · ${filtered.length} 人`} note="分位与表现分来自同分路同阵营样本；对手选手也可查，但不参与本队分位。">
        {!visible.length ? <BoardEmpty title="没有符合筛选的选手">放宽阵营、分路或最少局数再试。</BoardEmpty>
          : layout === 'grid' ? (
            <div className="player-card-grid">
              {visible.map((player) => <PlayerCard player={player} key={player.name} />)}
            </div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>选手</th><th>阵营</th><th>分路</th><th>局数</th><th>胜率</th><th>KDA</th><th>MVP</th><th>参团</th><th>输出</th><th>表现</th></tr></thead>
                <tbody>
                  {visible.map((player) => (
                    <tr key={player.name}>
                      <td><Link className="text-link" to={playerPath(player.name)}>{player.name}</Link></td>
                      <td>{sideName(player.side)}</td>
                      <td>{player.lane}</td>
                      <td className="is-num">{player.games}</td>
                      <td className="is-num">{percent(player.winRate)}</td>
                      <td className="is-num">{number(player.kda, 2)}</td>
                      <td className="is-num">{player.mvp}</td>
                      <td className="is-num">{percent(player.participation)}</td>
                      <td className="is-num">{percent(player.damageShare)}</td>
                      <td className="is-num">{number(player.score, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {pages > 1 ? (
          <div className="board-pager">
            <button type="button" className="btn btn-sm" disabled={safePage <= 0} onClick={() => setPage(safePage - 1)}>上一页</button>
            <span>{safePage + 1} / {pages}</span>
            <button type="button" className="btn btn-sm" disabled={safePage >= pages - 1} onClick={() => setPage(safePage + 1)}>下一页</button>
          </div>
        ) : null}
      </AnalysisSection>

      <div className="board-foot">CSV 导出当前筛选结果；表现分 = KDA / 分均经济 / 分均输出 / 参团四项分位均值。</div>
    </div>
  )
}

function PlayerCard({ player }: { player: BoardPlayer }) {
  const tier = scoreTier(player.score)
  return (
    <Link to={playerPath(player.name)} className="player-card">
      <div className="player-card-head">
        <Portrait name={player.name} size="md" />
        <span className="player-card-id"><b>{player.name}</b><small>{player.lane} · {sideName(player.side)} · {player.bound ? '已认领' : '待认领'}</small></span>
        <TierBadge tier={tier} />
      </div>
      <div className="player-card-score">
        <strong>{number(player.score, 1)}</strong>
        <span><small>表现分</small><em>{player.games} 局 · {percent(player.winRate)}</em></span>
      </div>
      <div className="player-card-metrics">
        <span><small>KDA</small><b>{number(player.kda, 2)}</b></span>
        <span><small>参团</small><b>{percent(player.participation)}</b></span>
        <span><small>输出占比</small><b>{percent(player.damageShare)}</b></span>
        <span><small>MVP</small><b>{player.mvp}</b></span>
      </div>
      <div className="player-card-foot">
        <span className={`board-tag tone-${formTone(player.form)}`}>{formLabel(player.form)}</span>
        {player.laneMix && player.laneMix.length > 1 ? <span className="board-muted">兼 {player.laneMix.filter((mix) => mix.lane !== player.lane).map((mix) => mix.lane).join(' / ')}</span> : null}
      </div>
    </Link>
  )
}
