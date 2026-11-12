/**
 * 上帝模式 · 第十九批注册块（决策台团战/开局 + 对手阵营偏好）
 */
import { useConnection } from '../../lib/app-context'
import { useFights, useOpening } from '../../lib/decision'
import { useBpBoard } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 团战执行摘要。 */
function DecisionFightsBlock() {
  const { baseUrl } = useConnection()
  const query = useFights(baseUrl, {}, true)
  const report = query.data
  const summary = report?.summary
  return (
    <AnalysisSection title="团战执行" note="块库 · 决策台团战摘要；到达、参团、先手与团灭。">
      {query.isLoading ? <Loading label="正在读取团战…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : !report?.available ? <BoardEmpty title="当前范围没有可用团战样本">{report?.reason || ''}</BoardEmpty>
            : !summary ? <BoardEmpty title="暂无可算团战摘要" />
              : (
                <div className="league-grid is-four">
                  <div className="league-card"><span>团战次数</span><b>{number(summary.fights)}</b><em>次</em></div>
                  <div className="league-card"><span>平均到场延迟</span><b>{number(summary.avgArrivalLagSec, 1)}</b><em>秒</em></div>
                  <div className="league-card"><span>迟到参团率</span><b>{percent(summary.lateJoinRate)}</b><em>{number(summary.lateJoins)} 次</em></div>
                  <div className="league-card"><span>团战击杀</span><b>{number(summary.ownKills)} : {number(summary.enemyKills)}</b><em>本队 : 对手</em></div>
                  <div className="league-card"><span>团灭</span><b>{number(summary.wipes)}</b><em>我方 {number(summary.wipeSides?.own)} / 对手 {number(summary.wipeSides?.enemy)}</em></div>
                  <div className="league-card"><span>先手</span><b>{number(summary.beginner?.own)} : {number(summary.beginner?.enemy)}</b><em>本队 : 对手</em></div>
                  <div className="league-card"><span>先到</span><b>{number(summary.firstArrival?.own)} : {number(summary.firstArrival?.enemy)}</b><em>本队 : 对手</em></div>
                  <div className="league-card"><span>一血</span><b>{number(summary.firstKiller?.own)} : {number(summary.firstKiller?.enemy)}</b><em>本队 : 对手</em></div>
                </div>
              )}
    </AnalysisSection>
  )
}

/** 开局与路线摘要。 */
function DecisionOpeningBlock() {
  const { baseUrl } = useConnection()
  const query = useOpening(baseUrl, {}, true)
  const report = query.data
  const coverage = report?.coverage
  return (
    <AnalysisSection title="开局与路线" note="块库 · 决策台开局观察摘要；样本少时只作单局参考。">
      {query.isLoading ? <Loading label="正在读取开局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : !report?.available ? <BoardEmpty title="当前范围没有可用的开局观察">{report?.reason || '缺位置采样。'}</BoardEmpty>
            : !coverage ? <BoardEmpty title="暂无可算开局摘要" />
              : (
                <div className="league-grid is-four">
                  <div className="league-card"><span>本批对局</span><b>{number(coverage.games)}</b><em>局</em></div>
                  <div className="league-card"><span>有位置</span><b>{number(coverage.positionGames)}</b><em>局</em></div>
                  <div className="league-card"><span>路线簇</span><b>{number(coverage.clusters ?? coverage.routes)}</b><em>个</em></div>
                  <div className="league-card"><span>热区采样</span><b>{number(coverage.heatPoints)}</b><em>点</em></div>
                  <div className="league-card"><span>对手数</span><b>{number(coverage.opponents)}</b><em>支</em></div>
                  <div className="league-card"><span>采样窗口</span><b>{number(coverage.sampleUntilSec)}</b><em>秒</em></div>
                  <div className="league-card"><span>坐标</span><b>{coverage.calibrated ? '已定标' : '相对坐标'}</b><em>{coverage.relative ? '相对口径' : '绝对口径'}</em></div>
                  <div className="league-card"><span>路线数</span><b>{number((report?.routes || []).length)}</b><em>条</em></div>
                </div>
              )}
    </AnalysisSection>
  )
}

/** 对手阵营偏好。 */
function BpOpponentSidesBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const rows = new Map<string, { opponent: string; games: number; blue: number; red: number; blueWins: number; blueDecided: number; redWins: number; redDecided: number }>()
  for (const game of query.data?.games || []) {
    const key = game.opponent || '未标注'
    const row = rows.get(key) || { opponent: key, games: 0, blue: 0, red: 0, blueWins: 0, blueDecided: 0, redWins: 0, redDecided: 0 }
    row.games += 1
    const side = game.side === 'red' ? 'red' : 'blue'
    if (side === 'blue') row.blue += 1
    else row.red += 1
    if (game.result === 'win' || game.result === 'loss') {
      if (side === 'blue') { row.blueDecided += 1; if (game.result === 'win') row.blueWins += 1 }
      else { row.redDecided += 1; if (game.result === 'win') row.redWins += 1 }
    }
    rows.set(key, row)
  }
  const list = [...rows.values()].sort((a, b) => b.games - a.games).slice(0, 12)
  return (
    <AnalysisSection title="对手阵营偏好" note="块库 · 本队在对手局里的红蓝分布与各自胜率。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : list.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>局数</th><th>蓝方</th><th>蓝胜率</th><th>红方</th><th>红胜率</th></tr></thead>
                <tbody>
                  {list.map((row) => (
                    <tr key={row.opponent}>
                      <td>{row.opponent}</td>
                      <td className="is-num">{row.games}</td>
                      <td className="is-num">{row.blue}</td>
                      <td className="is-num">{percent(row.blueDecided ? row.blueWins / row.blueDecided * 100 : null)}</td>
                      <td className="is-num">{row.red}</td>
                      <td className="is-num">{percent(row.redDecided ? row.redWins / row.redDecided * 100 : null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有 BP 样本" />}
    </AnalysisSection>
  )
}

export const DECISION_FIGHT_OPENING_BLOCKS: RegisteredBlock[] = [
  { id: 'decision.fights', base: 'decision.fights', variant: '摘要', domain: 'match', title: '团战执行', question: '团战到场、参团、先手与团灭情况如何？', filters: [], Component: DecisionFightsBlock },
  { id: 'decision.opening', base: 'decision.opening', variant: '摘要', domain: 'match', title: '开局与路线', question: '开局路线簇与热区覆盖如何？', filters: [], Component: DecisionOpeningBlock },
  { id: 'bp.opponent-sides', base: 'bp.opponent-sides', variant: '红蓝', domain: 'bp', title: '对手阵营偏好', question: '对每个对手的红蓝分布与胜率？', filters: [], Component: BpOpponentSidesBlock }
]
