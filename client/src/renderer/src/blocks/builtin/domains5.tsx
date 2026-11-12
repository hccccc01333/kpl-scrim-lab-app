/**
 * 上帝模式 · 第六批注册块（比赛走势 / 选手名册 / 分路深度 / BP 阵营日趋势）
 */
import { useConnection } from '../../lib/app-context'
import { useBpBoard, useCampCompare, useMatches, usePlayersBoard } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { heroPool } from '../../lib/analysis/heroes'
import { laneDepth } from '../../lib/analysis/players'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function useMatchList() {
  const { baseUrl } = useConnection()
  return useMatches(baseUrl)
}

/** 连胜/连败与最近走势。 */
function MatchStreakBlock() {
  const query = useMatchList()
  const matches = [...(query.data || [])].sort((a, b) => String(a.date).localeCompare(String(b.date)))
  const decided = matches.filter((match) => match.result === 'win' || match.result === 'loss')
  let best = 0, bestWin = 0, worst = 0, worstLoss = 0, cur = 0, curWin = true
  for (const match of decided) {
    const win = match.result === 'win'
    if (cur === 0 || win === curWin) { cur += 1; curWin = win } else { cur = 1; curWin = win }
    if (win) { bestWin = Math.max(bestWin, cur); best = Math.max(best, bestWin) } else { worstLoss = Math.max(worstLoss, cur); worst = Math.max(worst, worstLoss) }
  }
  const last = decided[decided.length - 1]
  const current = (() => {
    let n = 0, win = false
    for (let i = decided.length - 1; i >= 0; i -= 1) {
      const w = decided[i].result === 'win'
      if (i === decided.length - 1) { win = w; n = 1 } else if (w === win) n += 1; else break
    }
    return decided.length ? { n, win } : null
  })()
  return (
    <AnalysisSection title="连胜连败" note="块库 · 只统计有胜负的局；按日期排序。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : decided.length ? (
            <div className="league-grid is-four">
              <div className="league-card"><span>最长连胜</span><b>{bestWin}</b><em>局</em></div>
              <div className="league-card"><span>最长连败</span><b>{worstLoss}</b><em>局</em></div>
              <div className="league-card"><span>当前</span><b>{current ? `${current.n}` : '—'}</b><em>{current ? (current.win ? '连胜' : '连败') : '无'}</em></div>
              <div className="league-card"><span>最近一局</span><b>{last ? (last.result === 'win' ? '胜' : '负') : '—'}</b><em>{last?.date || ''}</em></div>
            </div>
          ) : <BoardEmpty title="还没有有胜负的对局" />}
    </AnalysisSection>
  )
}

/** 按月战绩。 */
function MatchMonthBlock() {
  const query = useMatchList()
  const rows = new Map<string, { month: string; games: number; decided: number; wins: number }>()
  for (const match of query.data || []) {
    const month = String(match.date || '').slice(0, 7) || '未记录'
    const row = rows.get(month) || { month, games: 0, decided: 0, wins: 0 }
    row.games += 1
    if (match.result === 'win' || match.result === 'loss') { row.decided += 1; if (match.result === 'win') row.wins += 1 }
    rows.set(month, row)
  }
  const list = [...rows.values()].sort((a, b) => b.month.localeCompare(a.month)).slice(0, 12)
  return (
    <AnalysisSection title="按月战绩" note="块库 · 按对局日期月份汇总局数与胜率。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : list.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>月份</th><th>局数</th><th>胜率</th></tr></thead>
                <tbody>
                  {list.map((row) => (
                    <tr key={row.month}><td>{row.month}</td><td className="is-num">{row.games}</td><td className="is-num">{percent(row.decided ? row.wins / row.decided * 100 : null)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有对局" />}
    </AnalysisSection>
  )
}

/** 红蓝方战绩。 */
function BpSideWinrateBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const rows = { blue: { games: 0, wins: 0, decided: 0 }, red: { games: 0, wins: 0, decided: 0 } }
  for (const game of query.data?.games || []) {
    const side = game.side === 'red' ? 'red' : 'blue'
    rows[side].games += 1
    if (game.result === 'win' || game.result === 'loss') { rows[side].decided += 1; if (game.result === 'win') rows[side].wins += 1 }
  }
  return (
    <AnalysisSection title="红蓝方战绩" note="块库 · 营地终局名单口径；按本队所在阵营统计。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>阵营</th><th>局数</th><th>胜率</th></tr></thead>
                <tbody>
                  {(['blue', 'red'] as const).map((side) => (
                    <tr key={side}>
                      <td>{side === 'blue' ? '蓝方' : '红方'}</td>
                      <td className="is-num">{rows[side].games}</td>
                      <td className="is-num">{percent(rows[side].decided ? rows[side].wins / rows[side].decided * 100 : null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
    </AnalysisSection>
  )
}

/** 本队英雄池覆盖。 */
function HeroPoolBlock() {
  const { baseUrl } = useConnection()
  const query = useCampCompare(baseUrl)
  if (query.isLoading) return <AnalysisSection title="英雄池覆盖"><Loading label="正在读取英雄…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="英雄池覆盖"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const pool = heroPool(query.data, 'own')
  return (
    <AnalysisSection title="英雄池覆盖" note="块库 · 本队本期英雄数与有效英雄（1/HHI 折算）。">
      <div className="league-grid is-four">
        <div className="league-card"><span>英雄数</span><b>{number(pool.heroes)}</b><em>个</em></div>
        <div className="league-card"><span>有效英雄</span><b>{number(pool.effective, 1)}</b><em>1/HHI</em></div>
        <div className="league-card"><span>出场</span><b>{number(pool.picks)}</b><em>人次</em></div>
        <div className="league-card"><span>样本局</span><b>{number(query.data.games)}</b><em>局</em></div>
      </div>
    </AnalysisSection>
  )
}

/** 选手名册（本队）。 */
function PlayerRosterBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  const players = (query.data?.players || []).filter((player) => player.side === 'own').slice(0, 20)
  return (
    <AnalysisSection title="选手名册" note="块库 · 本队出场选手、分路、局数与胜率。">
      {query.isLoading ? <Loading label="正在读取选手…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : players.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>选手</th><th>分路</th><th>局数</th><th>胜率</th></tr></thead>
                <tbody>
                  {players.map((player) => (
                    <tr key={player.name}>
                      <td>{player.name}</td>
                      <td>{player.lane || '—'}</td>
                      <td className="is-num">{player.games}</td>
                      <td className="is-num">{percent(player.winRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有选手样本" />}
    </AnalysisSection>
  )
}

/** 位置深度：每路轮换与空缺。 */
function PlayerLaneDepthBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  if (query.isLoading) return <AnalysisSection title="位置深度"><Loading label="正在读取分路…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="位置深度"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = laneDepth(query.data)
  return (
    <AnalysisSection title="位置深度" note="块库 · 人次/局 < 1 说明该路有轮换或空缺。">
      <div className="data-table-wrap">
        <table className="data-table">
          <thead><tr><th>分路</th><th>局数</th><th>人次</th><th>人次/局</th><th>状态</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.lane}>
                <td>{row.lane}</td>
                <td className="is-num">{row.games}</td>
                <td className="is-num">{row.players}</td>
                <td className="is-num">{number(row.perGame, 2)}</td>
                <td>{row.players >= 2 ? '有轮换' : row.players === 1 ? '单人固定' : '待观察'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AnalysisSection>
  )
}

export const SERIES_BLOCKS: RegisteredBlock[] = [
  { id: 'match.streak', base: 'match.streak', variant: '连胜连败', domain: 'match', title: '连胜连败', question: '现在几连胜/连败？最长记录多少？', filters: [], Component: MatchStreakBlock },
  { id: 'match.month', base: 'match.month', variant: '按月', domain: 'match', title: '按月战绩', question: '每个月打了多少局、胜率多少？', filters: [], Component: MatchMonthBlock },
  { id: 'bp.side', base: 'bp.side', variant: '红蓝', domain: 'bp', title: '红蓝方战绩', question: '蓝方和红方各自胜率多少？', filters: [], Component: BpSideWinrateBlock },
  { id: 'hero.pool', base: 'hero.pool', variant: '覆盖', domain: 'hero', title: '英雄池覆盖', question: '本队英雄池有多深？有效英雄多少？', filters: [], Component: HeroPoolBlock },
  { id: 'player.roster', base: 'player.roster', variant: '名册', domain: 'player', title: '选手名册', question: '本队选手的分路、局数与胜率？', filters: [], Component: PlayerRosterBlock },
  { id: 'player.lane-depth', base: 'player.lane-depth', variant: '深度', domain: 'player', title: '位置深度', question: '哪条路有轮换或空缺？', filters: [], Component: PlayerLaneDepthBlock }
]
