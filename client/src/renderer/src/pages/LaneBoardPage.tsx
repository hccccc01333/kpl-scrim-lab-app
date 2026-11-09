import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { usePlayersBoard } from '../lib/hooks'
import { number, percent, signed } from '../lib/format'
import { playerPath } from '../lib/routes'
import {
  PLAYER_LANES,
  laneDepth,
  laneGoldDiffs,
  laneIndex,
  laneOrder,
  sideName
} from '../lib/analysis/players'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { BarList } from '../components/charts/BarList'
import { VersusBars } from '../components/charts/VersusBars'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'

export function LaneBoardPage() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  const board = query.data

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !board) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const lanes = laneOrder(board.lanes)
  const ownPlayers = board.players.filter((player) => player.side === 'own')
  const enemyPlayers = board.players.filter((player) => player.side === 'enemy')
  const depth = laneDepth(board).sort((a, b) => laneIndex(a.lane) - laneIndex(b.lane))
  const goldDiffs = laneGoldDiffs(board)
  const validDiffs = goldDiffs.filter((row) => row.avgDiff !== null)
  const strongest = [...validDiffs].sort((a, b) => (b.avgDiff || 0) - (a.avgDiff || 0))[0]
  const weakest = [...validDiffs].sort((a, b) => (a.avgDiff || 0) - (b.avgDiff || 0))[0]
  const avgGpmDiff = lanes.length
    ? lanes.reduce((sum, lane) => sum + ((lane.own.gpm || 0) - (lane.enemy.gpm || 0)), 0) / lanes.length
    : null
  const multiLane = ownPlayers.filter((player) => (player.laneMix || []).length > 1)

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="LANE BOARD"
        title="选手与位置"
        subtitle="五条分路的经济、输出与参团；位置内选手按表现分排序，同位置经济差只统计同路各有一人的局。"
        actions={<Link className="btn" to="/players/compare">选手对比</Link>}
      />

      <StatGrid items={[
        { label: '本队出场人次', value: number(ownPlayers.length), note: `${board.games.length} 局` },
        { label: '对手出场人次', value: number(enemyPlayers.length), note: '用于对位参照' },
        { label: '分均经济差', value: signed(avgGpmDiff), note: '五路本队减对手均值' },
        { label: '最强分路', value: strongest?.lane || '—', note: strongest?.avgDiff != null ? `${signed(strongest.avgDiff)} 金` : '无样本', tone: 'own' },
        { label: '最弱分路', value: weakest?.lane || '—', note: weakest?.avgDiff != null ? `${signed(weakest.avgDiff)} 金` : '无样本', tone: 'foe' },
        { label: '兼位选手', value: number(multiLane.length), note: `${board.summary.positions} 个分路` }
      ]} />

      <AnalysisSection title="位置强度" note="本队与对手同分路均值对照；胜率与参团按位置出场统计。">
        <div className="lane-strength-grid">
          {lanes.map((lane) => (
            <div className="lane-strength-card" key={lane.lane}>
              <div className="lane-strength-head"><b>{lane.lane}</b><span>{lane.own.games} 局</span></div>
              <VersusBars
                rows={[
                  { label: '分均经济', own: lane.own.gpm, foe: lane.enemy.gpm, digits: 0 },
                  { label: '分均输出', own: lane.own.dpm, foe: lane.enemy.dpm, digits: 0 },
                  { label: '胜率', own: lane.own.winRate, foe: lane.enemy.winRate, digits: 1, suffix: '%' },
                  { label: '参团', own: lane.own.participation, foe: lane.enemy.participation, digits: 1, suffix: '%' }
                ]}
                ownTitle="本队"
                foeTitle="对手"
              />
            </div>
          ))}
        </div>
      </AnalysisSection>

      <AnalysisSection title="位置内选手" note="每个分路本队表现分前 3；样本不足会标注局数。">
        <div className="lane-player-grid">
          {PLAYER_LANES.map((lane) => {
            const rows = ownPlayers
              .filter((player) => player.lane === lane)
              .sort((a, b) => (b.score || 0) - (a.score || 0))
              .slice(0, 3)
            return (
              <div className="lane-player-card" key={lane}>
                <div className="lane-player-head"><b>{lane}</b><span>{ownPlayers.filter((player) => player.lane === lane).length} 人</span></div>
                {rows.length ? rows.map((player) => (
                  <Link to={playerPath(player.name)} className="lane-player-row" key={player.name}>
                    <Portrait name={player.name} size="sm" />
                    <span><b>{player.name}</b><small>{player.games} 局 · {percent(player.winRate)}</small></span>
                    <strong>{number(player.score, 1)}</strong>
                  </Link>
                )) : <p className="board-muted">暂无记录</p>}
              </div>
            )
          })}
        </div>
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="位置深度" note="人次 / 局数 < 1 说明该路有轮换或空缺；只描述出场结构。">
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>分路</th><th>局数</th><th>人次</th><th>人次/局</th><th>状态</th></tr></thead>
              <tbody>
                {depth.map((row) => (
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

        <AnalysisSection title="同位置经济差" note="逐局同路终局经济差；正数表示本队该路领先。">
          <BarList
            items={goldDiffs.map((row) => ({
              label: row.lane,
              value: row.avgDiff === null ? null : Math.abs(row.avgDiff),
              note: row.games ? `${row.ahead}/${row.games} 局领先 · 均值 ${signed(row.avgDiff)}` : '无样本',
              tone: (row.avgDiff || 0) >= 0 ? 'own' : 'foe'
            }))}
            digits={0}
            suffix=" 金"
          />
        </AnalysisSection>
      </div>

      <AnalysisSection title="多位置选手" note="同一期内打过两个以上分路；兼位样本会影响分位解释。">
        {multiLane.length ? (
          <div className="multi-lane-list">
            {multiLane.slice(0, 12).map((player) => (
              <Link to={playerPath(player.name)} className="multi-lane-row" key={player.name}>
                <b>{player.name}</b>
                <span>{player.laneMix.map((mix) => `${mix.lane} ${mix.games} 局`).join(' · ')}</span>
                <span>{sideName(player.side)}</span>
              </Link>
            ))}
          </div>
        ) : <BoardEmpty title="本期没有兼位选手" />}
      </AnalysisSection>

      <div className="board-foot">位置强度使用全部营地样本；同名选手跨位置时不合并分位，只在个人页的兼位说明里标注。</div>
    </div>
  )
}
