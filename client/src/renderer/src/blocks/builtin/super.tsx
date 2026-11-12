/**
 * 超块（Super Blocks）
 *
 * 会议需求的样板：每个块自带内容/范围/展示配置，配置随布局保存；
 * 专业模式由 preset 摆好，全面模式在分析库里自己挑。
 */
import { useEffect, useMemo, useState } from 'react'
import { useConnection } from '../../lib/app-context'
import { useBpBoard, useCampCompare } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock, BlockOptions } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function opt(options: BlockOptions | undefined, key: string, fallback: string): string {
  const value = options?.[key]
  return typeof value === 'string' && value ? value : fallback
}
function optNumber(options: BlockOptions | undefined, key: string, fallback: number): number {
  const value = options?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}
function optBool(options: BlockOptions | undefined, key: string, fallback: boolean): boolean {
  const value = options?.[key]
  return typeof value === 'boolean' ? value : fallback
}

interface HeroAgg {
  hero: string
  lane: string
  games: number
  wins: number
  decided: number
  kda: number
  gpm: number
  dpm: number
}

function aggregateHeroes(rows: { hero: string; lane?: string; games: number; wins: number; decided: number; kda?: number | null; gpm?: number | null; dpmTotal?: number | null }[]): HeroAgg[] {
  const map = new Map<string, HeroAgg>()
  for (const row of rows) {
    const item = map.get(row.hero) || { hero: row.hero, lane: row.lane || '', games: 0, wins: 0, decided: 0, kda: 0, gpm: 0, dpm: 0 }
    item.games += row.games || 0
    item.wins += row.wins || 0
    item.decided += row.decided || 0
    item.kda += (row.kda || 0) * (row.decided || 0)
    item.gpm += (row.gpm || 0) * (row.games || 0)
    item.dpm += (row.dpmTotal || 0) * (row.games || 0)
    if (!item.lane && row.lane) item.lane = row.lane
    map.set(row.hero, item)
  }
  return [...map.values()].map((item) => ({
    ...item,
    kda: item.decided ? item.kda / item.decided : 0,
    gpm: item.games ? item.gpm / item.games : 0,
    dpm: item.games ? item.dpm / item.games : 0
  }))
}

function HeroTable({ rows, display, sort, topN }: { rows: HeroAgg[]; display: string; sort: string; topN: number }) {
  const ordered = useMemo(() => {
    const sorted = [...rows].sort((a, b) => {
      if (sort === 'games') return b.games - a.games
      if (sort === 'kda') return b.kda - a.kda
      if (sort === 'gpm') return b.gpm - a.gpm
      return (b.decided ? b.wins / b.decided : 0) - (a.decided ? a.wins / a.decided : 0)
    })
    return topN > 0 ? sorted.slice(0, topN) : sorted
  }, [rows, sort, topN])
  if (!ordered.length) return <BoardEmpty title="当前范围没有英雄样本" />
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead><tr><th>英雄</th><th>分路</th><th>场次</th><th>胜率</th><th>KDA</th><th>分均经济</th><th>分均输出</th></tr></thead>
        <tbody>
          {ordered.map((row) => {
            const winRate = row.decided ? row.wins / row.decided * 100 : null
            return (
              <tr key={row.hero}>
                <td>
                  {display === 'bars' ? (
                    <span className="super-hero-cell">
                      <b>{row.hero}</b>
                      <i className="super-bar"><i style={{ width: `${Math.min(100, winRate || 0)}%` }} /></i>
                    </span>
                  ) : row.hero}
                </td>
                <td>{row.lane || '—'}</td>
                <td className="is-num">{row.games}</td>
                <td className="is-num">{percent(winRate)}</td>
                <td className="is-num">{number(row.kda, 2)}</td>
                <td className="is-num">{number(row.gpm)}</td>
                <td className="is-num">{number(row.dpm)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** 超块：英雄胜率。 */
function HeroWinrateBlock({ options }: { options?: BlockOptions }) {
  const { baseUrl } = useConnection()
  const query = useCampCompare(baseUrl)
  const side = opt(options, 'side', 'own')
  const sort = opt(options, 'sort', 'winRate')
  const display = opt(options, 'display', 'table')
  const topRaw = options?.topN
  const topN = topRaw === undefined || topRaw === '' ? 20 : Number(topRaw)
  const minGames = optNumber(options, 'minGames', 1)
  if (query.isLoading) return <AnalysisSection title="英雄胜率"><Loading label="正在读取英雄…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="英雄胜率"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const own = aggregateHeroes(query.data.heroes.own).filter((row) => row.games >= minGames)
  const enemy = aggregateHeroes(query.data.heroes.enemy).filter((row) => row.games >= minGames)
  const sections = side === 'enemy' ? [['对手', enemy]] as const : side === 'both' ? [['本队', own], ['对手', enemy]] as const : [['本队', own]] as const
  return (
    <AnalysisSection title="英雄胜率" note={`近 ${number(query.data.games)} 局样本 · 按 ${sort === 'games' ? '场次' : sort === 'kda' ? 'KDA' : sort === 'gpm' ? '分均经济' : '胜率'}排序 · 阈值 ≥${minGames} 局`}>
      {sections.map(([label, rows]) => (
        <div key={label} style={{ marginBottom: 12 }}>
          <div className="board-subhead">{label}</div>
          <HeroTable rows={rows} display={display} sort={sort} topN={topN} />
        </div>
      ))}
    </AnalysisSection>
  )
}

interface BpRateRow {
  hero: string
  icon?: string | null
  bans: number
  picks: number
}

function bpRateRows(games: { bans: { own: { name: string; icon?: string | null }[]; enemy: { name: string; icon?: string | null }[] }; picks: { own: { name: string; icon?: string | null }[]; enemy: { name: string; icon?: string | null }[] } }[], side: 'own' | 'enemy' | 'both', sort: string): BpRateRow[] {
  const map = new Map<string, BpRateRow>()
  const bump = (hero: string, icon: string | null | undefined, key: 'bans' | 'picks') => {
    const row = map.get(hero) || { hero, icon, bans: 0, picks: 0 }
    row[key] += 1
    if (!row.icon && icon) row.icon = icon
    map.set(hero, row)
  }
  for (const game of games) {
    const sides: ('own' | 'enemy')[] = side === 'both' ? ['own', 'enemy'] : [side]
    for (const key of sides) {
      for (const entry of game.bans[key]) bump(entry.name, entry.icon, 'bans')
      for (const entry of game.picks[key]) bump(entry.name, entry.icon, 'picks')
    }
  }
  const rows = [...map.values()]
  rows.sort((a, b) => sort === 'bans' ? b.bans - a.bans : sort === 'total' ? (b.bans + b.picks) - (a.bans + a.picks) : b.picks - a.picks)
  return rows
}

/** 超块：BP 率（禁用次数 / 选用次数）。 */
function BpRateBlock({ options }: { options?: BlockOptions }) {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const side = opt(options, 'side', 'own') as 'own' | 'enemy' | 'both'
  const sort = opt(options, 'sort', 'total')
  const display = opt(options, 'display', 'squares')
  const topRaw = options?.topN
  const topN = topRaw === undefined || topRaw === '' ? 30 : Number(topRaw)
  if (query.isLoading) return <AnalysisSection title="BP 率"><Loading label="正在读取 BP…" /></AnalysisSection>
  if (query.isError) return <AnalysisSection title="BP 率"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const games = query.data?.games || []
  if (!games.length) return <AnalysisSection title="BP 率"><BoardEmpty title="还没有 BP 样本" /></AnalysisSection>
  const rows = bpRateRows(games, side, sort).slice(0, topN > 0 ? topN : undefined)
  return (
    <AnalysisSection title="BP 率" note={`${games.length} 局样本 · 按${sort === 'bans' ? '禁用' : sort === 'total' ? '禁+选' : '选用'}次数排序`}>
      {display === 'squares' ? (
        <div className="super-squares">
          {rows.map((row) => (
            <div className="super-square" key={row.hero} title={`禁用 ${row.bans} · 选用 ${row.picks}`}>
              {row.icon ? <img src={row.icon} alt="" loading="lazy" /> : <span className="super-square-mark">{row.hero.slice(0, 1)}</span>}
              <b>{row.hero}</b>
              <em><span>禁 {row.bans}</span><span>选 {row.picks}</span></em>
            </div>
          ))}
        </div>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>英雄</th><th>禁用</th><th>选用</th><th>合计</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.hero}><td>{row.hero}</td><td className="is-num">{row.bans}</td><td className="is-num">{row.picks}</td><td className="is-num">{row.bans + row.picks}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AnalysisSection>
  )
}

const STRENGTH_KEY = 'kpl:opp-strength:v1'
const STRENGTH_TIERS = ['百段队', '段对段千强', '巅峰2200-2400'] as const

function readStrength(): Record<string, string> {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STRENGTH_KEY) || '{}')
    return raw && typeof raw === 'object' ? raw : {}
  } catch {
    return {}
  }
}

/** 超块：对局列表（双方阵容 / 结果 / 经济 / 推塔 / 交手 / 对手强度标注）。 */
function MatchListBlock({ options }: { options?: BlockOptions }) {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const showLineups = optBool(options, 'showLineups', true)
  const showStats = optBool(options, 'showStats', true)
  const showStrength = optBool(options, 'showStrength', true)
  const [strength, setStrength] = useState<Record<string, string>>(readStrength)
  useEffect(() => { setStrength(readStrength()) }, [])
  if (query.isLoading) return <AnalysisSection title="对局列表"><Loading label="正在读取对局…" /></AnalysisSection>
  if (query.isError) return <AnalysisSection title="对局列表"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const games = query.data?.games || []
  if (!games.length) return <AnalysisSection title="对局列表"><BoardEmpty title="还没有对局" /></AnalysisSection>
  const byOpponent = new Map<string, { games: number; wins: number }>()
  for (const game of games) {
    const row = byOpponent.get(game.opponent) || { games: 0, wins: 0 }
    row.games += 1
    if (game.result === 'win') row.wins += 1
    byOpponent.set(game.opponent, row)
  }
  const stat = (side: 'own' | 'enemy', key: string) => {
    const value = games[0]?.stats?.[side]?.[key]
    return typeof value === 'number' ? value : null
  }
  const towerKeyOwn = Object.keys(games[0]?.stats?.own || {}).find((key) => /tower|塔/i.test(key))
  const goldKeyOwn = Object.keys(games[0]?.stats?.own || {}).find((key) => /gold|经济/i.test(key))
  const setTier = (opponent: string, tier: string) => {
    const next = { ...strength }
    if (tier) next[opponent] = tier
    else delete next[opponent]
    setStrength(next)
    try { window.localStorage.setItem(STRENGTH_KEY, JSON.stringify(next)) } catch { /* ignore */ }
  }
  return (
    <AnalysisSection title="对局列表" note={`${games.length} 局 · 对局数/胜负/阵容/交手；对手强度可手注`}>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>时间</th><th>对手</th><th>结果</th><th>时长</th>
              {showLineups ? <th>双方阵容</th> : null}
              {showStats ? <><th>经济</th><th>推塔</th></> : null}
              <th>交手</th>
              {showStrength ? <th>对手强度</th> : null}
            </tr>
          </thead>
          <tbody>
            {games.slice(0, 30).map((game) => {
              const agg = byOpponent.get(game.opponent) || { games: 0, wins: 0 }
              const ownTower = towerKeyOwn ? Number(game.stats.own[towerKeyOwn] || 0) : null
              const enemyTower = towerKeyOwn ? Number(game.stats.enemy[towerKeyOwn] || 0) : null
              const ownGold = goldKeyOwn ? Number(game.stats.own[goldKeyOwn] || 0) : null
              return (
                <tr key={game.key}>
                  <td>{game.start || game.day}</td>
                  <td>{game.opponent}</td>
                  <td>{game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '—'}</td>
                  <td>{Math.floor((game.duration || 0) / 60)} 分</td>
                  {showLineups ? <td>{game.picks.own.map((entry) => entry.name).join(' · ')}<br /><span className="board-muted">vs {game.picks.enemy.map((entry) => entry.name).join(' · ')}</span></td> : null}
                  {showStats ? <td className="is-num">{ownGold !== null ? number(ownGold) : '—'}</td> : null}
                  {showStats ? <td className="is-num">{ownTower !== null ? `${ownTower} : ${enemyTower ?? 0}` : '—'}</td> : null}
                  <td>{agg.games} 局 · {percent(agg.games ? agg.wins / agg.games * 100 : null)}</td>
                  {showStrength ? (
                    <td>
                      <select value={strength[game.opponent] || ''} onChange={(event) => setTier(game.opponent, event.target.value)}>
                        <option value="">未标注</option>
                        {STRENGTH_TIERS.map((tier) => <option key={tier} value={tier}>{tier}</option>)}
                      </select>
                    </td>
                  ) : null}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {showStats ? <p className="board-muted" style={{ marginTop: 6 }}>经济/推塔取终局面板字段；字段缺失时显示 —。</p> : null}
    </AnalysisSection>
  )
}

export const SUPER_BLOCKS: RegisteredBlock[] = [
  {
    id: 'super.hero-winrate',
    base: 'super.hero-winrate',
    variant: '超块',
    domain: 'hero',
    title: '英雄胜率',
    question: '本队/对手各英雄的场次、胜率、KDA、经济输出，能按范围、排序和形态切换。',
    filters: [],
    Component: HeroWinrateBlock,
    options: [
      { key: 'side', label: '观察对象', type: 'select', default: 'own', options: [{ value: 'own', label: '本队' }, { value: 'enemy', label: '对手' }, { value: 'both', label: '本队+对手' }] },
      { key: 'sort', label: '排序', type: 'select', default: 'winRate', options: [{ value: 'winRate', label: '胜率' }, { value: 'games', label: '场次' }, { value: 'kda', label: 'KDA' }, { value: 'gpm', label: '分均经济' }] },
      { key: 'topN', label: '显示数量', type: 'select', default: '20', options: [{ value: '10', label: '前 10' }, { value: '20', label: '前 20' }, { value: '50', label: '前 50' }, { value: '0', label: '全部' }] },
      { key: 'display', label: '展示形态', type: 'select', default: 'table', options: [{ value: 'table', label: '表格' }, { value: 'bars', label: '表格 + 胜率条' }] },
      { key: 'minGames', label: '最少场次', type: 'number', default: 1, min: 1, max: 20, step: 1 }
    ]
  },
  {
    id: 'super.bp-rate',
    base: 'super.bp-rate',
    variant: '超块',
    domain: 'bp',
    title: 'BP 率',
    question: '按禁用/选用次数看 BP 率，本队/对手分别统计，支持小方框和表格。',
    filters: [],
    Component: BpRateBlock,
    options: [
      { key: 'side', label: '观察对象', type: 'select', default: 'own', options: [{ value: 'own', label: '本队' }, { value: 'enemy', label: '对手' }, { value: 'both', label: '本队+对手' }] },
      { key: 'sort', label: '排序', type: 'select', default: 'total', options: [{ value: 'total', label: '禁+选' }, { value: 'bans', label: '禁用次数' }, { value: 'picks', label: '选用次数' }] },
      { key: 'display', label: '展示形态', type: 'select', default: 'squares', options: [{ value: 'squares', label: '小方框' }, { value: 'table', label: '表格' }] },
      { key: 'topN', label: '显示数量', type: 'select', default: '30', options: [{ value: '12', label: '前 12' }, { value: '30', label: '前 30' }, { value: '0', label: '全部' }] }
    ]
  },
  {
    id: 'super.match-list',
    base: 'super.match-list',
    variant: '超块',
    domain: 'match',
    title: '对局列表',
    question: '双方阵容、结果、时长、经济、推塔、交手局数，以及对手强度手注。',
    filters: [],
    Component: MatchListBlock,
    options: [
      { key: 'showLineups', label: '显示双方阵容', type: 'toggle', default: true },
      { key: 'showStats', label: '显示经济/推塔', type: 'toggle', default: true },
      { key: 'showStrength', label: '显示对手强度标注', type: 'toggle', default: true }
    ]
  }
]
