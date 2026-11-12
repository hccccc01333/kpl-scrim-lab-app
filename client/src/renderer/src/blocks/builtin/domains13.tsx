/**
 * 上帝模式 · 第十四批注册块（单局十人面板 / 经济输出占比 / 战队交手与阵容）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useMatch, useTeams } from '../../lib/hooks'
import { duration as fmtDuration, number, percent } from '../../lib/format'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function useCurrentMatch() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const key = pageContextFromPath(location.pathname).matchKey || ''
  return { key, query: useMatch(baseUrl, key) }
}

function useCurrentTeam() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const id = pageContextFromPath(location.pathname).team || ''
  const query = useTeams(baseUrl)
  const team = (query.data?.teams || []).find((item) => item.id === id)
  return { id, query, team }
}

function campLabel(camp: string | undefined, ownCamp: string | undefined): string {
  if (!camp) return '—'
  if (camp === ownCamp) return '本队'
  const blue = camp === 'blue' || camp === 'left' || camp === '1'
  return blue ? '蓝方' : '红方'
}

/** 本局十人面板。 */
function MatchPlayerBoardBlock() {
  const { key, query } = useCurrentMatch()
  const detail = query.data
  if (!key) return <AnalysisSection title="本局十人面板"><BoardEmpty title="这个块要放在单局页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="本局十人面板"><Loading label="正在读取本局…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="本局十人面板"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const players = detail.players || []
  return (
    <AnalysisSection title="本局十人面板" note="块库 · 营地十人面板终局数据。">
      {players.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>阵营</th><th>选手</th><th>英雄</th><th>K/D/A</th><th>经济</th><th>输出</th><th>参团</th></tr></thead>
            <tbody>
              {players.map((player) => (
                <tr key={`${player.camp}-${player.slot}-${player.playerId}`}>
                  <td>{campLabel(player.camp, detail.ownCamp)}</td>
                  <td>{player.label || player.playerId}</td>
                  <td>{player.hero || '—'}</td>
                  <td className="is-num">{player.kills}/{player.deaths}/{player.assists}</td>
                  <td className="is-num">{number(player.gold)}</td>
                  <td className="is-num">{number(player.damage)}</td>
                  <td className="is-num">{percent(player.participation)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="这一局没有十人面板" />}
    </AnalysisSection>
  )
}

function shareTable(title: string, metric: 'damage' | 'gold') {
  return function ShareBlock() {
    const { key, query } = useCurrentMatch()
    const detail = query.data
    if (!key) return <AnalysisSection title={title}><BoardEmpty title="这个块要放在单局页" /></AnalysisSection>
    if (query.isLoading) return <AnalysisSection title={title}><Loading label="正在读取本局…" /></AnalysisSection>
    if (query.isError || !detail) return <AnalysisSection title={title}><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
    const players = detail.players || []
    if (!players.length) return <AnalysisSection title={title}><BoardEmpty title="这一局没有十人面板" /></AnalysisSection>
    const own = players.filter((player) => player.camp === detail.ownCamp)
    const total = own.reduce((sum, player) => sum + (metric === 'damage' ? player.damage : player.gold), 0)
    return (
      <AnalysisSection title={title} note={`块库 · 本队五人${metric === 'damage' ? '输出' : '经济'}占比。`}>
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>选手</th><th>英雄</th><th>{metric === 'damage' ? '输出' : '经济'}</th><th>队内占比</th></tr></thead>
            <tbody>
              {own.map((player) => {
                const value = metric === 'damage' ? player.damage : player.gold
                return (
                  <tr key={`${player.slot}-${player.playerId}`}>
                    <td>{player.label || player.playerId}</td>
                    <td>{player.hero || '—'}</td>
                    <td className="is-num">{number(value)}</td>
                    <td className="is-num">{percent(total ? value / total * 100 : null)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </AnalysisSection>
    )
  }
}

const MatchDamageShareBlock = shareTable('本局输出占比', 'damage')
const MatchGoldShareBlock = shareTable('本局经济占比', 'gold')

/** 战队交手走势。 */
function TeamHistoryBlock() {
  const { id, query, team } = useCurrentTeam()
  return (
    <AnalysisSection title="交手走势" note="块库 · 战队详情页上下文；最近 10 局（对手视角）。">
      {!id ? <BoardEmpty title="这个块要放在战队详情页" />
        : query.isLoading ? <Loading label="正在读取战队…" />
          : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
            : team?.games?.length ? (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>日期</th><th>地图</th><th>结果</th><th>时长</th></tr></thead>
                  <tbody>
                    {[...team.games].slice(-10).reverse().map((game) => (
                      <tr key={game.seq}>
                        <td>{game.start}</td>
                        <td>{game.map || '—'}</td>
                        <td><span className={`board-tag tone-${game.win ? 'foe' : 'own'}`}>{game.win ? '对手胜' : '本队胜'}</span></td>
                        <td className="is-num">{fmtDuration(game.duration)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <BoardEmpty title="没有交手明细" />}
    </AnalysisSection>
  )
}

/** 战队阵容。 */
function TeamPlayersBlock() {
  const { id, query, team } = useCurrentTeam()
  const players = [...(team?.players || [])].sort((a, b) => b.games - a.games)
  return (
    <AnalysisSection title="战队阵容" note="块库 · 战队详情页上下文；对手选手与分路。">
      {!id ? <BoardEmpty title="这个块要放在战队详情页" />
        : query.isLoading ? <Loading label="正在读取战队…" />
          : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
            : players.length ? (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>选手</th><th>分路</th><th>出场</th></tr></thead>
                  <tbody>
                    {players.map((player) => (
                      <tr key={player.id}>
                        <td>{player.name}</td>
                        <td>{player.lane || '—'}</td>
                        <td className="is-num">{player.games}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <BoardEmpty title="没有阵容记录" />}
    </AnalysisSection>
  )
}

export const MATCH_TEAM_DEEP_BLOCKS: RegisteredBlock[] = [
  { id: 'match.player-board', base: 'match.player-board', variant: '十人面板', domain: 'match', title: '本局十人面板', question: '这一局十个人的数据？（单局页）', filters: [], Component: MatchPlayerBoardBlock },
  { id: 'match.damage-share', base: 'match.damage-share', variant: '输出占比', domain: 'match', title: '本局输出占比', question: '这一局本队五人的输出占比？（单局页）', filters: [], Component: MatchDamageShareBlock },
  { id: 'match.gold-share', base: 'match.gold-share', variant: '经济占比', domain: 'match', title: '本局经济占比', question: '这一局本队五人的经济占比？（单局页）', filters: [], Component: MatchGoldShareBlock },
  { id: 'team.history', base: 'team.history', variant: '交手走势', domain: 'team', title: '交手走势', question: '这支战队最近 10 局打得怎么样？（战队详情页）', filters: [], Component: TeamHistoryBlock },
  { id: 'team.players', base: 'team.players', variant: '阵容', domain: 'team', title: '战队阵容', question: '这支战队的选手与分路？（战队详情页）', filters: [], Component: TeamPlayersBlock }
]
