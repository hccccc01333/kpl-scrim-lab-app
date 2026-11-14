/**
 * 上帝模式 · 第十八批注册块（资源 + 龙控/击杀）
 */
import { useConnection } from '../../lib/app-context'
import { useBpBoard } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function stat(value: unknown): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : 0
}

function BpObjectivesBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const games = query.data?.games || []
  const sum = (key: string) => games.reduce((total, game) => total + stat(game.stats.own[key]) - stat(game.stats.enemy[key]), 0)
  const ownTotal = (key: string) => games.reduce((total, game) => total + stat(game.stats.own[key]), 0)
  const enemyTotal = (key: string) => games.reduce((total, game) => total + stat(game.stats.enemy[key]), 0)
  const rows = [
    { label: '小龙（ldragon1）', own: ownTotal('ldragon1'), enemy: enemyTotal('ldragon1') },
    { label: '小龙（ldragon2）', own: ownTotal('ldragon2'), enemy: enemyTotal('ldragon2') },
    { label: '暴君（bdragon1）', own: ownTotal('bdragon1'), enemy: enemyTotal('bdragon1') },
    { label: '主宰（bdragon2）', own: ownTotal('bdragon2'), enemy: enemyTotal('bdragon2') },
    { label: '风暴龙王（bdragon3）', own: ownTotal('bdragon3'), enemy: enemyTotal('bdragon3') }
  ]
  return (
    <AnalysisSection title="龙控" note={`块库 · 终局面板龙数；共 ${games.length} 局，数值为正表示本队净领先。`}>
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : games.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>资源</th><th>本队</th><th>对手</th><th>净差</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td className="is-num">{number(row.own)}</td>
                      <td className="is-num">{number(row.enemy)}</td>
                      <td className="is-num">{number(row.own - row.enemy)}</td>
                    </tr>
                  ))}
                  <tr><td>总净差</td><td /><td /><td className="is-num">{number(sum('ldragon1') + sum('ldragon2') + sum('bdragon1') + sum('bdragon2') + sum('bdragon3'))}</td></tr>
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有 BP 样本" />}
    </AnalysisSection>
  )
}

/** 击杀/死亡：终局面板汇总。 */
function BpKillDeathBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const games = query.data?.games || []
  const total = (side: 'own' | 'enemy', key: string) => games.reduce((sum, game) => sum + stat(game.stats[side][key]), 0)
  return (
    <AnalysisSection title="击杀与死亡" note="块库 · 终局面板汇总；击杀净差为正表示本队领先。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : games.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>项目</th><th>本队</th><th>对手</th><th>净差</th></tr></thead>
                <tbody>
                  {[
                    { label: '击杀', key: 'killCnt' },
                    { label: '死亡', key: 'deadCnt' },
                    { label: '助攻', key: 'assistCnt' }
                  ].map((row) => (
                    <tr key={row.key}>
                      <td>{row.label}</td>
                      <td className="is-num">{number(total('own', row.key))}</td>
                      <td className="is-num">{number(total('enemy', row.key))}</td>
                      <td className="is-num">{number(total('own', row.key) - total('enemy', row.key))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有 BP 样本" />}
    </AnalysisSection>
  )
}

export const DECISION_RESOURCE_OBJECTIVE_BLOCKS: RegisteredBlock[] = [
  { id: 'bp.objectives', base: 'bp.objectives', variant: '龙控', domain: 'bp', title: '龙控', question: '本队和对手的龙控净差多少？', filters: [], Component: BpObjectivesBlock },
  { id: 'bp.kill-death', base: 'bp.kill-death', variant: '汇总', domain: 'bp', title: '击杀与死亡', question: '击杀/死亡/助攻的总量净差？', filters: [], Component: BpKillDeathBlock }
]
