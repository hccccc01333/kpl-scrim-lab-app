/**
 * 上帝模式 · 第十九批注册块（对手阵营偏好）
 */
import { useConnection } from '../../lib/app-context'
import { useBpBoard } from '../../lib/hooks'
import { percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
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
  { id: 'bp.opponent-sides', base: 'bp.opponent-sides', variant: '红蓝', domain: 'bp', title: '对手阵营偏好', question: '对每个对手的红蓝分布与胜率？', filters: [], Component: BpOpponentSidesBlock }
]
