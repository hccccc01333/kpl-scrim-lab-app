import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useTeams } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { teamPath } from '../lib/routes'
import { TEAM_LANES, mean, rosterRotation, rosterStability } from '../lib/analysis/teams'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import type { StudioTeam, TeamRosterPlayer } from '../lib/types'

export function TeamRosterPage() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const data = query.data

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const rows = data.teams.map((team) => {
    const roster = team.roster
    const lanes = TEAM_LANES.map((lane) => {
      const laneRow = roster?.lanes?.find((item) => item.lane === lane)
      const players = [...(laneRow?.players || [])].sort((a, b) => b.games - a.games)
      return { lane, players, top: players[0] || null }
    })
    return {
      team,
      lanes,
      stability: rosterStability(roster),
      rotation: rosterRotation(roster),
      lineups: roster?.lineups || []
    }
  })
  const stabilityValues = rows.map((row) => row.stability).filter((value): value is number => typeof value === 'number')
  const avgStability = mean(stabilityValues)
  const rotationTeams = rows.filter((row) => row.lanes.some((lane) => lane.players.length > 1)).length
  const lineupCount = rows.reduce((sum, row) => sum + row.lineups.length, 0)
  const stableCount = rows.reduce((sum, row) => sum + row.lineups.filter((lineup) => lineup.games >= 2).length, 0)
  const laneCoverage = TEAM_LANES.map((lane) => ({
    lane,
    teams: rows.filter((row) => row.lanes.find((item) => item.lane === lane)?.players.length).length
  }))
  const pool = TEAM_LANES.map((lane) => ({
    lane,
    players: rows
      .flatMap((row) => (row.lanes.find((item) => item.lane === lane)?.players || []).map((player) => ({ player, team: row.team })))
      .sort((a, b) => b.player.games - a.player.games || (b.player.kda || 0) - (a.player.kda || 0))
      .slice(0, 8)
  }))

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TEAM ROSTER"
        title="战队阵容"
        subtitle="逐队五人组、位置池与轮换；同位置两人以上才算轮换，重复位置不计轮换。"
        actions={<Link className="btn" to="/teams">战队档案</Link>}
      />

      <StatGrid items={[
        { label: '战队数', value: number(data.teams.length), note: `${data.summary.games} 局样本` },
        { label: '五人组套数', value: number(lineupCount), note: `稳定 ≥2 局 ${stableCount}` },
        { label: '平均稳定度', value: avgStability === null ? '—' : `${Math.round(avgStability)}%`, note: '最大五人组 / 总局数' },
        { label: '有轮换', value: number(rotationTeams), note: '至少一路两人' },
        { label: '位置覆盖', value: `${laneCoverage.filter((row) => row.teams > 0).length} / ${TEAM_LANES.length}`, note: '有阵容记录的分路' }
      ]} />

      <AnalysisSection title="阵容矩阵" note="格内为出场最多的选手与局数；+N 表示同位置还有 N 人轮换。">
        <div className="data-table-wrap">
          <table className="data-table roster-matrix">
            <thead>
              <tr>
                <th>战队</th>
                {TEAM_LANES.map((lane) => <th key={lane}>{lane}</th>)}
                <th>稳定度</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ team, lanes, stability }) => (
                <tr key={team.id}>
                  <td><Link className="text-link" to={teamPath(team.id)}>{team.displayName}</Link><small className="board-muted"> · {team.matches} 局</small></td>
                  {lanes.map((lane) => (
                    <td key={lane.lane} className="roster-cell">
                      {lane.top ? (
                        <>
                          <b>{lane.top.name}</b>
                          <small>{lane.top.games} 局{lane.players.length > 1 ? ` · +${lane.players.length - 1}` : ''}</small>
                        </>
                      ) : <span className="board-muted">—</span>}
                    </td>
                  ))}
                  <td className="is-num">{stability === null ? '—' : `${Math.round(stability)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AnalysisSection>

      <AnalysisSection title="位置池" note="五个位置各自局数前 8；本队与对手战队都在池里，用来读位置深度。">
        <div className="lane-pool-grid">
          {pool.map((lane) => (
            <div className="lane-pool-card" key={lane.lane}>
              <div className="lane-player-head"><b>{lane.lane}</b><span>{lane.players.length} 人</span></div>
              {lane.players.length ? lane.players.map(({ player, team }) => (
                <div className="lane-pool-row" key={`${team.id}-${player.id}`}>
                  <span><b>{player.name}</b><small>{team.displayName}</small></span>
                  <span>{player.games} 局</span>
                  <span>{percent(player.winRate)}</span>
                </div>
              )) : <p className="board-muted">暂无记录</p>}
            </div>
          ))}
        </div>
      </AnalysisSection>

      <AnalysisSection title="轮换与五人组" note="稳定度 = 最大同组局数 / 总局数；五人组按共同出场统计。">
        {rows.some((row) => row.lineups.length) ? (
          <div className="lineup-team-list">
            {rows.map(({ team, lineups, stability, rotation }) => (
              <div className="lineup-team" key={team.id}>
                <div className="lineup-team-head">
                  <Link to={teamPath(team.id)}><b>{team.displayName}</b></Link>
                  <span>{team.matches} 局 · 稳定度 {stability === null ? '—' : `${Math.round(stability)}%`} · 轮换 {rotation === null ? '—' : `${Math.round(rotation)}%`}</span>
                </div>
                {lineups.slice(0, 3).map((lineup) => (
                  <div className="lineup-row" key={lineup.names.join('|')}>
                    <span>{lineup.names.join(' · ')}</span>
                    <b>{lineup.games} 局</b>
                    <span>{lineup.wins} 胜</span>
                  </div>
                ))}
                {!lineups.length ? <p className="board-muted">还没有重复五人组</p> : null}
              </div>
            ))}
          </div>
        ) : <BoardEmpty title="还没有可统计的五人组" />}
      </AnalysisSection>

      <div className="board-foot">轮换读法：同一分路出现两人以上才计入轮换；位置重复告警不在这里展开。本页使用全部营地样本。</div>
    </div>
  )
}
