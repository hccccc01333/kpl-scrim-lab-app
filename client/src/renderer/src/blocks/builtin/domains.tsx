/**
 * 上帝模式 · 英雄 / 选手 / 战队 / BP 对手习惯 注册块（第二批）
 * 这些块自带数据，可以加到任意页面。
 */
import { useConnection } from '../../lib/app-context'
import { useBpBoard, useCampCombos, usePlayersBoard, useTeams } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { laneOrder } from '../../lib/analysis/players'
import { teamAxes } from '../../lib/analysis/teams'
import { useBlockFilter } from '../filter-context'
import { dateInBlockRange } from '../filters'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 英雄组合：本队/对手双人 + 三人。 */
function HeroCombosBlock() {
  const { baseUrl } = useConnection()
  const query = useCampCombos(baseUrl, 3)
  const side = useBlockFilter().side === 'red' ? 'enemy' : 'own'
  const pairs = query.data?.pairs?.[side]?.combos || []
  const trios = query.data?.trios?.[side]?.combos || []
  return (
    <AnalysisSection title={`英雄组合 · ${side === 'own' ? '本队' : '对手'}`} note="块库 · 同一局同阵营共现的双人/三人组；按出现局数排。">
      {query.isLoading ? <Loading label="正在读取组合…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : (pairs.length || trios.length) ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>组合</th><th>人数</th><th>局数</th><th>胜率</th><th>协同</th></tr></thead>
                <tbody>
                  {pairs.slice(0, 10).map((combo) => (
                    <tr key={`p-${combo.heroes.join('|')}`}>
                      <td>{combo.heroes.join(' + ')}</td>
                      <td className="is-num">2</td>
                      <td className="is-num">{combo.games}</td>
                      <td className="is-num">{percent(combo.winRate)}</td>
                      <td className="is-num">{combo.synergy === null ? '—' : `${combo.synergy > 0 ? '+' : ''}${combo.synergy.toFixed(1)}`}</td>
                    </tr>
                  ))}
                  {trios.slice(0, 6).map((combo) => (
                    <tr key={`t-${combo.heroes.join('|')}`}>
                      <td>{combo.heroes.join(' + ')}</td>
                      <td className="is-num">3</td>
                      <td className="is-num">{combo.games}</td>
                      <td className="is-num">{percent(combo.winRate)}</td>
                      <td className="is-num">—</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有达到样本门槛的组合" />}
    </AnalysisSection>
  )
}

/** 分路强度：五路本队口径。 */
function PlayersLanesBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  const board = query.data
  if (query.isLoading) return <AnalysisSection title="分路强度"><Loading label="正在读取分路数据…" /></AnalysisSection>
  if (query.isError || !board) return <AnalysisSection title="分路强度"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const lanes = laneOrder(board.lanes)
  return (
    <AnalysisSection title="分路强度" note="块库 · 本队五路的局数、分均经济、分均输出与参团。">
      {lanes.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>分路</th><th>局数</th><th>分均经济</th><th>分均输出</th><th>参团</th><th>胜率</th></tr></thead>
            <tbody>
              {lanes.map((lane) => (
                <tr key={lane.lane}>
                  <td>{lane.lane}</td>
                  <td className="is-num">{lane.own.games}</td>
                  <td className="is-num">{number(lane.own.gpm)}</td>
                  <td className="is-num">{number(lane.own.dpm)}</td>
                  <td className="is-num">{percent(lane.own.participation)}</td>
                  <td className="is-num">{percent(lane.own.winRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有分路样本" />}
    </AnalysisSection>
  )
}

/** 战队风格：四轴分位。 */
function TeamsStyleBlock() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const teams = [...(query.data?.teams || [])].sort((a, b) => (b.matches || 0) - (a.matches || 0)).slice(0, 12)
  return (
    <AnalysisSection title="战队风格" note="块库 · 同池分位读节奏/团战/运营/后期；样本少只作观察。">
      {query.isLoading ? <Loading label="正在读取战队…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : teams.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>战队</th><th>局数</th><th>节奏</th><th>团战</th><th>运营</th><th>后期</th></tr></thead>
                <tbody>
                  {teams.map((team) => {
                    const axes = teamAxes(team.percentiles)
                    const value = (key: string) => Math.round(axes.find((axis) => axis.key === key)?.value || 0)
                    return (
                      <tr key={team.id}>
                        <td>{team.displayName || team.name}</td>
                        <td className="is-num">{team.matches}</td>
                        <td className="is-num">{value('pace')}</td>
                        <td className="is-num">{value('fight')}</td>
                        <td className="is-num">{value('macro')}</td>
                        <td className="is-num">{value('late')}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有战队样本" />}
    </AnalysisSection>
  )
}

/** 对手 BP 习惯：每个对手最常禁/选什么。 */
function BpOppHabitsBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const filters = useBlockFilter()
  const games = (query.data?.games || []).filter((game) => {
    if (filters.opponent && game.opponent !== filters.opponent) return false
    if (!dateInBlockRange(game.start, filters)) return false
    return true
  })
  const rows = new Map<string, { opponent: string; games: number; bans: Map<string, number>; picks: Map<string, number> }>()
  for (const game of games) {
    const row = rows.get(game.opponent) || { opponent: game.opponent, games: 0, bans: new Map(), picks: new Map() }
    row.games += 1
    for (const entry of game.bans.enemy) row.bans.set(entry.name, (row.bans.get(entry.name) || 0) + 1)
    for (const entry of game.picks.enemy) row.picks.set(entry.name, (row.picks.get(entry.name) || 0) + 1)
    rows.set(game.opponent, row)
  }
  const list = [...rows.values()].sort((a, b) => b.games - a.games).slice(0, 10)
  const top = (map: Map<string, number>) => [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)
  return (
    <AnalysisSection title="对手 BP 习惯" note="块库 · 按对手分组，列出交手局数、最常禁和最常选。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : list.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>交手局</th><th>最常禁</th><th>最常选</th></tr></thead>
                <tbody>
                  {list.map((row) => (
                    <tr key={row.opponent}>
                      <td>{row.opponent}</td>
                      <td className="is-num">{row.games}</td>
                      <td>{top(row.bans).map(([hero, count]) => `${hero} ${count}`).join(' · ') || '—'}</td>
                      <td>{top(row.picks).map(([hero, count]) => `${hero} ${count}`).join(' · ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选没有 BP 样本" />}
    </AnalysisSection>
  )
}

export const DOMAIN_BLOCKS: RegisteredBlock[] = [
  {
    id: 'hero.combos',
    base: 'hero.combos',
    variant: '表格',
    domain: 'hero',
    title: '英雄组合',
    question: '本队/对手最常一起拿的英雄组合是什么？胜率多少？',
    filters: ['side'],
    Component: HeroCombosBlock
  },
  {
    id: 'player.lanes',
    base: 'player.lanes',
    variant: '表格',
    domain: 'player',
    title: '分路强度',
    question: '本队五路的分均经济、输出与参团谁强谁弱？',
    filters: [],
    Component: PlayersLanesBlock
  },
  {
    id: 'team.style',
    base: 'team.style',
    variant: '四轴表',
    domain: 'team',
    title: '战队风格',
    question: '各对手的节奏、团战、运营、后期倾向如何？',
    filters: [],
    Component: TeamsStyleBlock
  },
  {
    id: 'bp.opp-habits',
    base: 'bp.opp-habits',
    variant: '习惯表',
    domain: 'bp',
    title: '对手 BP 习惯',
    question: '每个对手最常禁谁、最常选谁？',
    filters: ['range', 'opponent'],
    Component: BpOppHabitsBlock
  }
]
