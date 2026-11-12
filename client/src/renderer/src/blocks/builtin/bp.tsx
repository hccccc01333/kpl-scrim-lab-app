/**
 * 上帝模式 · BP 域注册块
 *
 * 数据来自 bp-board（营地终局名单，数组顺序即该侧手序）和 /api/analysis/bp
 * （逐局 BP 记录，含保留空位的 banSlots / pickSlots）。
 * 这些块可以加到任意页面；同一分析可以注册多个变体。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useConnection } from '../../lib/app-context'
import { api } from '../../lib/api'
import { useBpBoard } from '../../lib/hooks'
import { duration as fmtDuration, percent } from '../../lib/format'
import { pickBanCounts } from '../../lib/analysis/bp'
import {
  buildDraftSegments,
  firstBanHero,
  isCompleteDraft,
  sideLabel,
  type DraftSide,
  type DraftSource
} from '../../lib/analysis/draft'
import { useBlockFilter } from '../filter-context'
import { dateInBlockRange, type BlockFilterKey } from '../filters'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState, Portrait } from '../../components/ui'
import type { BpGame } from '../../lib/types'
import type { RegisteredBlock } from '../registry'

const FULL_FILTERS: BlockFilterKey[] = ['range', 'opponent', 'player', 'hero', 'side', 'result']
const NO_HERO_FILTERS: BlockFilterKey[] = ['range', 'opponent', 'player', 'side', 'result']

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function hasHero(game: BpGame, hero: string): boolean {
  return [...game.picks.own, ...game.picks.enemy, ...game.bans.own, ...game.bans.enemy]
    .some((entry) => entry.name === hero)
}

function useFilteredBp() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const filters = useBlockFilter()
  const games = (query.data?.games || []).filter((game) => {
    if (!dateInBlockRange(game.start, filters)) return false
    if (filters.opponent && game.opponent !== filters.opponent) return false
    if (filters.player && ![...game.players.own, ...game.players.enemy].includes(filters.player)) return false
    if (filters.hero && !hasHero(game, filters.hero)) return false
    if (filters.side && game.side !== filters.side) return false
    if (filters.result && game.result !== filters.result) return false
    return true
  })
  return { query, games }
}

/* ── 营地名单类 ───────────────────────────────────────────────────── */

function BpProfileBlock() {
  const { query, games } = useFilteredBp()
  const counts = pickBanCounts(games)
  const columns = [
    { title: '本队选用', rows: counts.ownPicks.slice(0, 8), tone: 'own' },
    { title: '本队禁用', rows: counts.ownBans.slice(0, 8), tone: 'muted' },
    { title: '对手选用', rows: counts.enemyPicks.slice(0, 8), tone: 'foe' },
    { title: '对手禁用', rows: counts.enemyBans.slice(0, 8), tone: 'muted' }
  ]
  return (
    <AnalysisSection title={`条件 BP 画像 · ${games.length} 局`} note="块库 · 当前筛选下的四类名单；每块可单独筛。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : (
            <div className="condition-grid">
              {columns.map((column) => {
                const max = column.rows[0]?.count || 1
                return (
                  <div className="condition-column" key={column.title}>
                    <h4>{column.title}</h4>
                    {column.rows.length ? column.rows.map((row, index) => (
                      <div className="condition-row" key={row.hero}>
                        <span className="rank-index">{index + 1}</span>
                        <span className="condition-name">{row.hero}</span>
                        <i className={`tone-${column.tone}`}><em style={{ width: `${Math.min(100, row.count / max * 100)}%` }} /></i>
                        <b>{row.count}</b>
                      </div>
                    )) : <p className="board-muted">暂无样本</p>}
                  </div>
                )
              })}
            </div>
          )}
    </AnalysisSection>
  )
}

function BpPicksBlock() {
  const { query, games } = useFilteredBp()
  const rows = pickBanCounts(games).ownPicks.slice(0, 12)
  return (
    <AnalysisSection title="本队选用榜" note="块库 · 本队选用次数与胜率；营地终局名单口径。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>英雄</th><th>选用</th><th>胜率</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.hero}>
                      <td><span className="hero-line"><Portrait name={row.hero} size="sm" /><span>{row.hero}</span></span></td>
                      <td className="is-num">{row.count}</td>
                      <td className="is-num">{percent(row.winRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选没有选用样本" />}
    </AnalysisSection>
  )
}

function BpBansBlock() {
  const { query, games } = useFilteredBp()
  const counts = pickBanCounts(games)
  const column = (title: string, rows: typeof counts.ownBans) => (
    <div>
      <h4>{title}</h4>
      {rows.length ? rows.slice(0, 8).map((row) => (
        <div className="condition-row" key={row.hero}>
          <span className="condition-name">{row.hero}</span>
          <b>{row.count}</b>
        </div>
      )) : <p className="board-muted">暂无样本</p>}
    </div>
  )
  return (
    <AnalysisSection title="禁用资源" note="块库 · 本队与对手各自禁用次数前 8；不推断针对意图。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : (
            <div className="bp-mini-grid">
              {column('本队禁用', counts.ownBans)}
              {column('对手禁用', counts.enemyBans)}
            </div>
          )}
    </AnalysisSection>
  )
}

function BpLensBlock() {
  const { query, games } = useFilteredBp()
  const [hero, setHero] = useState('')
  const rows = hero ? games.flatMap((game) => {
    const win = game.result === 'win' ? true : game.result === 'loss' ? false : null
    const found: { key: string; date: string; opponent: string; role: string; win: boolean | null }[] = []
    if (game.picks.own.some((entry) => entry.name === hero)) found.push({ key: `${game.key}-own-pick`, date: game.start, opponent: game.opponent, role: '本方选用', win })
    if (game.picks.enemy.some((entry) => entry.name === hero)) found.push({ key: `${game.key}-enemy-pick`, date: game.start, opponent: game.opponent, role: '对手选用', win })
    if (game.bans.own.some((entry) => entry.name === hero)) found.push({ key: `${game.key}-own-ban`, date: game.start, opponent: game.opponent, role: '本方禁用', win })
    if (game.bans.enemy.some((entry) => entry.name === hero)) found.push({ key: `${game.key}-enemy-ban`, date: game.start, opponent: game.opponent, role: '对手禁用', win })
    return found
  }) : []
  const heroes = [...new Set(games.flatMap((game) => [...game.picks.own, ...game.picks.enemy, ...game.bans.own, ...game.bans.enemy].map((entry) => entry.name)))].sort()
  return (
    <AnalysisSection title="英雄透镜" note="块库 · 选一个英雄，看它在当前筛选的对局里出现在哪一侧。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : (
            <>
              <div className="board-toolbar">
                <select value={hero} onChange={(event) => setHero(event.target.value)} aria-label="选择英雄">
                  <option value="">选择英雄</option>
                  {heroes.map((item) => <option value={item} key={item}>{item}</option>)}
                </select>
                <span className="board-muted">{hero ? `${rows.length} 条命中` : '选一个英雄看它的选禁记录'}</span>
              </div>
              {hero ? (rows.length ? (
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead><tr><th>日期</th><th>对手</th><th>角色</th><th>结果</th></tr></thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.key}>
                          <td>{row.date}</td>
                          <td>{row.opponent}</td>
                          <td><span className={`board-tag tone-${row.role.includes('本方') ? 'own' : 'foe'}`}>{row.role}</span></td>
                          <td>{row.win === null ? '—' : row.win ? '胜' : '负'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <BoardEmpty title="当前筛选下没有这名英雄" />) : <BoardEmpty title="还没有选择英雄" />}
            </>
          )}
    </AnalysisSection>
  )
}

function BpGamesBlock() {
  const { query, games } = useFilteredBp()
  return (
    <AnalysisSection title={`逐局 BP 名单 · ${games.length} 局`} note="块库 · 最多 8 局；选用五人、禁用五格，按营地终局名单原样展示。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : games.length ? (
            <div className="bp-game-list">
              {games.slice(0, 8).map((game) => (
                <div className="bp-game" key={game.key}>
                  <div className="bp-game-head">
                    <b>{game.start}</b>
                    <span>{game.opponent}</span>
                    <span className={`board-tag tone-${game.result === 'win' ? 'own' : 'foe'}`}>{game.result === 'win' ? '胜' : '负'}</span>
                    <small>{game.side === 'blue' ? '蓝方' : '红方'} · {fmtDuration(game.duration)}</small>
                  </div>
                  <div className="bp-game-row">
                    <span className="is-own">本队</span>
                    {game.picks.own.map((entry) => <span key={`own-${entry.name}`}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
                    <small>禁 {game.bans.own.map((entry) => entry.name).join(' · ') || '—'}</small>
                  </div>
                  <div className="bp-game-row">
                    <span className="is-foe">对手</span>
                    {game.picks.enemy.map((entry) => <span key={`foe-${entry.name}`}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
                    <small>禁 {game.bans.enemy.map((entry) => entry.name).join(' · ') || '—'}</small>
                  </div>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="当前筛选没有对局" />}
    </AnalysisSection>
  )
}

interface BreakRow {
  heroes: [string, string]
  formed: number
  wins: number
  decided: number
  banned: number
  stolen: number
  brokenWins: number
  brokenDecided: number
}

function BpComboBreakBlock() {
  const { query, games } = useFilteredBp()
  const stats = new Map<string, BreakRow>()
  for (const game of games) {
    const picks = game.picks.own.map((entry) => entry.name)
    for (let i = 0; i < picks.length; i += 1) {
      for (let j = i + 1; j < picks.length; j += 1) {
        const heroes: [string, string] = [picks[i], picks[j]]
        const key = heroes.join('|')
        const row = stats.get(key) || { heroes, formed: 0, wins: 0, decided: 0, banned: 0, stolen: 0, brokenWins: 0, brokenDecided: 0 }
        row.formed += 1
        if (game.result === 'win' || game.result === 'loss') {
          row.decided += 1
          if (game.result === 'win') row.wins += 1
        }
        stats.set(key, row)
      }
    }
  }
  const top = [...stats.values()].sort((a, b) => b.formed - a.formed).slice(0, 10)
  for (const row of top) {
    for (const game of games) {
      const ownPicks = game.picks.own.map((entry) => entry.name)
      if (ownPicks.includes(row.heroes[0]) && ownPicks.includes(row.heroes[1])) continue
      const enemyBans = game.bans.enemy.map((entry) => entry.name)
      const enemyPicks = game.picks.enemy.map((entry) => entry.name)
      const banned = enemyBans.includes(row.heroes[0]) || enemyBans.includes(row.heroes[1])
      const stolen = !banned && (enemyPicks.includes(row.heroes[0]) || enemyPicks.includes(row.heroes[1]))
      if (!banned && !stolen) continue
      if (banned) row.banned += 1
      else row.stolen += 1
      if (game.result === 'win' || game.result === 'loss') {
        row.brokenDecided += 1
        if (game.result === 'win') row.brokenWins += 1
      }
    }
  }
  return (
    <AnalysisSection title="组合拆解" note="块库 · 终局名单口径：对手 ban 掉或抢走组合内英雄即算拆；拆解率 = (被ban+被抢) / (成型+被ban+被抢)。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : top.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>组合</th><th>成型</th><th>成型胜率</th><th>被ban</th><th>被抢</th><th>拆解率</th><th>拆后胜率</th></tr></thead>
                <tbody>
                  {top.map((row) => {
                    const total = row.formed + row.banned + row.stolen
                    const brokenRate = total ? (row.banned + row.stolen) / total * 100 : null
                    const brokenWin = row.brokenDecided ? row.brokenWins / row.brokenDecided * 100 : null
                    return (
                      <tr key={row.heroes.join('|')}>
                        <td>{row.heroes.join(' + ')}</td>
                        <td className="is-num">{row.formed}</td>
                        <td className="is-num">{percent(row.decided ? row.wins / row.decided * 100 : null)}</td>
                        <td className="is-num">{row.banned}</td>
                        <td className="is-num">{row.stolen}</td>
                        <td className="is-num">{percent(brokenRate)}</td>
                        <td className="is-num">{percent(brokenWin)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选没有组合样本" />}
    </AnalysisSection>
  )
}

/* ── 逐局 BP 记录类（分析接口，保留空位）────────────────────────── */

export interface AnalysisBpEntry { name: string }

export interface AnalysisBpMatch {
  key: string
  date?: string
  opponent?: string
  result?: string
  pickOrderKnown?: boolean
  firstPick?: string | null
  ownSide?: string
  winnerSide?: string
  bans?: { left?: AnalysisBpEntry[]; right?: AnalysisBpEntry[] }
  picks?: { left?: AnalysisBpEntry[]; right?: AnalysisBpEntry[] }
  banSlots?: { left?: (AnalysisBpEntry | null)[]; right?: (AnalysisBpEntry | null)[] }
  pickSlots?: { left?: (AnalysisBpEntry | null)[]; right?: (AnalysisBpEntry | null)[] }
}

interface AnalysisBpPayload { matches?: AnalysisBpMatch[]; matchesWithBp?: number }

export function toDraftSource(match: AnalysisBpMatch): DraftSource {
  const names = (list?: AnalysisBpEntry[]) => (list || []).map((entry) => entry.name)
  const slots = (list?: (AnalysisBpEntry | null)[]) => (list || []).map((entry) => entry?.name || '')
  return {
    bans: { left: names(match.bans?.left), right: names(match.bans?.right) },
    picks: { left: names(match.picks?.left), right: names(match.picks?.right) },
    banSlots: { left: slots(match.banSlots?.left), right: slots(match.banSlots?.right) },
    pickSlots: { left: slots(match.pickSlots?.left), right: slots(match.pickSlots?.right) },
    pickOrderKnown: match.pickOrderKnown,
    firstPick: match.firstPick
  }
}

export function useAnalysisBp() {
  const { baseUrl } = useConnection()
  return useQuery({
    queryKey: ['analysis-bp', baseUrl],
    queryFn: () => api<AnalysisBpPayload>(baseUrl, '/api/analysis/bp', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    staleTime: 2 * 60_000,
    retry: 1,
    refetchOnWindowFocus: false
  })
}

export function ownDraftSide(match: AnalysisBpMatch): DraftSide | null {
  if (match.ownSide === 'left') return 'blue'
  if (match.ownSide === 'right') return 'red'
  return null
}

function BpPaperBlock() {
  const query = useAnalysisBp()
  const [selected, setSelected] = useState('')
  const matches = query.data?.matches || []
  const match = matches.find((item) => item.key === selected) || matches[0]
  const source = match ? toDraftSource(match) : null
  const paper = source ? buildDraftSegments(source) : null
  const complete = source ? isCompleteDraft(source) : false
  const ownSide = match ? ownDraftSide(match) : null
  return (
    <AnalysisSection
      title="BP 纸 · 征召模式"
      note={paper
        ? `${paper.template.label}：名单按该侧顺序填槽，空 ban 占位，不压缩后面的手序。`
        : '按征召模板排手序；模板按双方 ban 数量自动识别。'}
    >
      {query.isLoading ? <Loading label="正在读取 BP 记录…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : !match ? <BoardEmpty title="还没有 BP 记录">先在采集/校对里补 BP 名单。</BoardEmpty>
            : (
              <>
                <div className="board-toolbar">
                  <select value={match.key} onChange={(event) => setSelected(event.target.value)} aria-label="选择对局">
                    {matches.map((item) => (
                      <option value={item.key} key={item.key}>{item.date || item.key} · 对阵 {item.opponent || '未标注'}</option>
                    ))}
                  </select>
                  <span className="board-muted">
                    {paper ? `模板：${paper.template.label}` : ''}
                    {match.pickOrderKnown ? ' · 手序已录' : ' · 顺序按名单推导'}
                    {complete ? '' : ' · 名单不完整'}
                    {ownSide ? ` · 本队=${ownSide === 'blue' ? '蓝' : '红'}方` : ''}
                  </span>
                </div>
                <div className="draft-paper">
                  {paper?.segments.map((segment) => (
                    <div className="draft-segment" key={segment.label}>
                      <div className="draft-paper-label">{segment.label}</div>
                      <div
                        className="draft-paper-row"
                        style={{ gridTemplateColumns: `repeat(${Math.max(segment.slots.length, 1)}, minmax(0, 1fr))` }}
                      >
                        {segment.slots.map((slot) => (
                          <div
                            className={`draft-cell side-${slot.side}${slot.hero ? '' : ' is-empty'}${slot.side === ownSide ? ' is-own' : ''}`}
                            key={slot.order}
                          >
                            <span className="draft-cell-order">{slot.order}</span>
                            <b>{slot.hero || (slot.phase === 'ban' ? '空 BAN' : '—')}</b>
                            <small>{sideLabel(slot.side)}方</small>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
    </AnalysisSection>
  )
}

function BpFirstBanBlock() {
  const query = useAnalysisBp()
  const ordered = (query.data?.matches || []).filter((match) => (match.banSlots?.left || match.bans?.left || []).length > 0)
  const counts = new Map<string, { hero: string; bans: number; blueGames: number; blueWins: number }>()
  for (const match of ordered) {
    const hero = firstBanHero(toDraftSource(match))
    if (!hero) continue
    const row = counts.get(hero) || { hero, bans: 0, blueGames: 0, blueWins: 0 }
    row.bans += 1
    if (match.winnerSide === 'left' || match.winnerSide === 'right') {
      row.blueGames += 1
      if (match.winnerSide === 'left') row.blueWins += 1
    }
    counts.set(hero, row)
  }
  const rows = [...counts.values()].sort((a, b) => b.bans - a.bans).slice(0, 10)
  return (
    <AnalysisSection title="首 ban 位 · 蓝方第一 ban" note="块库 · 征召规则第一手是蓝方 ban；按槽位取第一个 ban，空 ban 保留位置。">
      {query.isLoading ? <Loading label="正在读取 BP 记录…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>英雄</th><th>首 ban 次数</th><th>蓝方胜率</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.hero}>
                      <td><span className="hero-line"><Portrait name={row.hero} size="sm" /><span>{row.hero}</span></span></td>
                      <td className="is-num">{row.bans}</td>
                      <td className="is-num">{percent(row.blueGames ? row.blueWins / row.blueGames * 100 : null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <BoardEmpty title="还没有可用的 BP 名单">
              训练赛 BP 名单同步到工作台后，这里自动按蓝方第一 ban 统计；空 ban 占位保留。
            </BoardEmpty>
          )}
    </AnalysisSection>
  )
}

export const BP_BLOCKS: RegisteredBlock[] = [
  { id: 'bp.profile', base: 'bp.profile', variant: '四组名单', domain: 'bp', title: '条件 BP 画像', question: '当前筛选下，本队和对手各自选/禁了哪些英雄？', filters: FULL_FILTERS, Component: BpProfileBlock },
  { id: 'bp.picks', base: 'bp.picks', variant: '表格', domain: 'bp', title: '本队选用榜', question: '本队当前最常选谁？拿到后胜率多少？', filters: FULL_FILTERS, Component: BpPicksBlock },
  { id: 'bp.bans', base: 'bp.bans', variant: '对照', domain: 'bp', title: '禁用资源', question: '本队与对手各自在禁谁？', filters: FULL_FILTERS, Component: BpBansBlock },
  { id: 'bp.lens', base: 'bp.lens', variant: '英雄透镜', domain: 'bp', title: '英雄透镜', question: '某个英雄在这些局里是被谁选/禁的？', filters: NO_HERO_FILTERS, Component: BpLensBlock },
  { id: 'bp.games', base: 'bp.games', variant: '名单', domain: 'bp', title: '逐局 BP 名单', question: '每一局的双方选禁名单长什么样？', filters: FULL_FILTERS, Component: BpGamesBlock },
  { id: 'bp.combo-break', base: 'bp.combo-break', variant: '拆解表', domain: 'bp', title: '组合拆解', question: '我们拿到的组合有多少被对手 ban/抢拆掉了？拆后胜率如何？', filters: ['range', 'opponent', 'player', 'hero'], Component: BpComboBreakBlock },
  { id: 'bp.paper', base: 'bp.paper', variant: 'BP 纸', domain: 'bp', title: 'BP 纸（征召模式）', question: '按真实手序排开 ban 和选人，一眼看双方阵容。', filters: [], Component: BpPaperBlock },
  { id: 'bp.first-ban', base: 'bp.first-ban', variant: '首 ban 位', domain: 'bp', title: '首 ban 位', question: '蓝方第一 ban 常给谁？ban 完之后蓝方胜率如何？', filters: [], Component: BpFirstBanBlock }
]
