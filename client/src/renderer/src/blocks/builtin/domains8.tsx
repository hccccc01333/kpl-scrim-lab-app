/**
 * 上帝模式 · 第九批注册块（英雄成长/联盟对照/战队使用 + 对手英雄池/阵容/近况）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useHeroDetail, useTeams } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function usePageHero(): string {
  const location = useLocation()
  return pageContextFromPath(location.pathname).hero || ''
}

/** 英雄成长曲线关键点。 */
function HeroGrowthBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useHeroDetail(baseUrl, hero)
  const detail = query.data
  if (!hero) return <AnalysisSection title="成长曲线"><BoardEmpty title="这个块要放在英雄详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="成长曲线"><Loading label="正在读取成长曲线…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="成长曲线"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const growth = detail.growth || []
  if (!growth.length) return <AnalysisSection title="成长曲线"><BoardEmpty title="还没有成长曲线样本" /></AnalysisSection>
  const at = (seconds: number) => {
    const point = [...growth].sort((a, b) => Math.abs(a.t - seconds) - Math.abs(b.t - seconds))[0]
    return point ? { t: point.t, value: point.value } : null
  }
  const points = [at(0), at(600), at(1200)].filter((point): point is { t: number; value: number } => Boolean(point))
  return (
    <AnalysisSection title={`${detail.hero} · 成长曲线`} note={`块库 · 官方回放采样；${detail.curveGames} 局可算。`}>
      <div className="league-grid is-four">
        {points.map((point) => (
          <div className="league-card" key={point.t}>
            <span>{Math.round(point.t / 60)} 分钟</span><b>{number(point.value)}</b><em>经济</em>
          </div>
        ))}
        <div className="league-card"><span>采样点</span><b>{growth.length}</b><em>个</em></div>
      </div>
    </AnalysisSection>
  )
}

/** 英雄均值对照。 */
function HeroLeagueBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useHeroDetail(baseUrl, hero)
  const detail = query.data
  if (!hero) return <AnalysisSection title="均值对照"><BoardEmpty title="这个块要放在英雄详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="均值对照"><Loading label="正在读取均值…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="均值对照"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = Object.entries(detail.league || {})
  return (
    <AnalysisSection title={`${detail.hero} · 均值对照`} note="块库 · 该英雄与全英雄均值对照。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>指标</th><th>该英雄</th><th>全英雄均值</th></tr></thead>
            <tbody>
              {rows.map(([key, value]) => (
                <tr key={key}>
                  <td>{key}</td>
                  <td className="is-num">{value.hero === null ? '—' : number(value.hero, 1)}</td>
                  <td className="is-num">{value.all === null ? '—' : number(value.all, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有均值样本" />}
    </AnalysisSection>
  )
}

/** 各战队使用这个英雄。 */
function HeroTeamsBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useHeroDetail(baseUrl, hero)
  const detail = query.data
  if (!hero) return <AnalysisSection title="战队使用"><BoardEmpty title="这个块要放在英雄详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="战队使用"><Loading label="正在读取战队…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="战队使用"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = (detail.teams || []).slice(0, 12)
  return (
    <AnalysisSection title={`${detail.hero} · 战队使用`} note="块库 · 哪些战队在用这个英雄、胜率如何。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>战队</th><th>局数</th><th>胜率</th><th>KDA</th><th>分均经济</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name}>
                  <td>{row.name}</td>
                  <td className="is-num">{row.games}</td>
                  <td className="is-num">{percent(row.winRate)}</td>
                  <td className="is-num">{number(row.kda, 2)}</td>
                  <td className="is-num">{number(row.gpm)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有战队样本" />}
    </AnalysisSection>
  )
}

/** 对手英雄池：每队常用英雄。 */
function TeamHeroPoolsBlock() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const teams = [...(query.data?.teams || [])].sort((a, b) => (b.matches || 0) - (a.matches || 0)).slice(0, 12)
  return (
    <AnalysisSection title="对手英雄池" note="块库 · 每支对手常用英雄前 3（出场数与胜率）。">
      {query.isLoading ? <Loading label="正在读取战队…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : teams.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>战队</th><th>常用英雄</th></tr></thead>
                <tbody>
                  {teams.map((team) => (
                    <tr key={team.id}>
                      <td>{team.displayName || team.name}</td>
                      <td>{(team.heroes || []).slice(0, 3).map((item) => `${item.hero} ${item.games}`).join(' · ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有战队样本" />}
    </AnalysisSection>
  )
}

/** 对手阵容：每队选手与分路。 */
function TeamRostersBlock() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const teams = [...(query.data?.teams || [])].sort((a, b) => (b.matches || 0) - (a.matches || 0)).slice(0, 12)
  return (
    <AnalysisSection title="对手阵容" note="块库 · 每支对手的选手与分路（有记录才列）。">
      {query.isLoading ? <Loading label="正在读取战队…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : teams.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>战队</th><th>阵容</th></tr></thead>
                <tbody>
                  {teams.map((team) => (
                    <tr key={team.id}>
                      <td>{team.displayName || team.name}</td>
                      <td>{(team.players || []).slice(0, 6).map((player) => `${player.name}${player.lane ? `(${player.lane})` : ''}`).join(' · ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有战队样本" />}
    </AnalysisSection>
  )
}

/** 对手近况：最近几局战绩。 */
function TeamRecentFormBlock() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const teams = [...(query.data?.teams || [])].sort((a, b) => (b.matches || 0) - (a.matches || 0)).slice(0, 12)
  return (
    <AnalysisSection title="对手近况" note="块库 · 最近几局的对手战绩（对手视角）。">
      {query.isLoading ? <Loading label="正在读取战队…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : teams.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>战队</th><th>最近 5 局</th></tr></thead>
                <tbody>
                  {teams.map((team) => {
                    const games = (team.games || []).slice(-5)
                    const wins = games.filter((game) => game.win).length
                    return (
                      <tr key={team.id}>
                        <td>{team.displayName || team.name}</td>
                        <td>{games.length ? `${wins} 胜 / ${games.length} 局` : '—'}</td>
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

export const HERO_TEAM_BLOCKS: RegisteredBlock[] = [
  { id: 'hero.growth', base: 'hero.growth', variant: '关键点', domain: 'hero', title: '成长曲线', question: '这个英雄开局/10 分钟/20 分钟经济多少？（英雄详情页）', filters: [], Component: HeroGrowthBlock },
  { id: 'hero.league', base: 'hero.league', variant: '均值对照', domain: 'hero', title: '均值对照', question: '这个英雄与全英雄均值差多少？（英雄详情页）', filters: [], Component: HeroLeagueBlock },
  { id: 'hero.teams', base: 'hero.teams', variant: '战队使用', domain: 'hero', title: '战队使用', question: '哪些战队在用这个英雄、胜率多少？（英雄详情页）', filters: [], Component: HeroTeamsBlock },
  { id: 'team.hero-pools', base: 'team.hero-pools', variant: '常用英雄', domain: 'team', title: '对手英雄池', question: '每个对手最常用的英雄是什么？', filters: [], Component: TeamHeroPoolsBlock },
  { id: 'team.rosters', base: 'team.rosters', variant: '阵容', domain: 'team', title: '对手阵容', question: '每个对手的选手与分路是谁？', filters: [], Component: TeamRostersBlock },
  { id: 'team.recent-form', base: 'team.recent-form', variant: '近况', domain: 'team', title: '对手近况', question: '每个对手最近 5 局战绩如何？', filters: [], Component: TeamRecentFormBlock }
]
