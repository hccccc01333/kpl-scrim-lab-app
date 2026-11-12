/**
 * 上帝模式 · 第十八批注册块（决策台失利/资源 + 龙控/击杀）
 */
import { useConnection } from '../../lib/app-context'
import { useLoss, useResource, type ResourceAnomaly } from '../../lib/decision'
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

/** 失利链摘要。 */
function DecisionLossBlock() {
  const { baseUrl } = useConnection()
  const query = useLoss(baseUrl, {}, true)
  const report = query.data
  const summary = report?.summary
  const byType = Object.entries(summary?.byType || {}).sort((a, b) => b[1] - a[1]).slice(0, 8)
  return (
    <AnalysisSection title="失利链" note="块库 · 决策台失利关键链摘要；只做描述性归纳。">
      {query.isLoading ? <Loading label="正在读取失利链…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : !report?.available ? <BoardEmpty title="当前范围没有可用样本">{report?.reason || ''}</BoardEmpty>
            : !summary ? <BoardEmpty title="暂无可算摘要" />
              : (
                <>
                  <div className="league-grid is-four">
                    <div className="league-card"><span>局数</span><b>{number(summary.games)}</b><em>局</em></div>
                    <div className="league-card"><span>有窗口</span><b>{number(summary.gamesWithWindows)}</b><em>局</em></div>
                    <div className="league-card"><span>掉点窗口</span><b>{number(summary.windows)}</b><em>次</em></div>
                    <div className="league-card"><span>样本充分</span><b>{summary.enough ? '是' : '否'}</b><em>{summary.reason || '—'}</em></div>
                  </div>
                  {byType.length ? (
                    <div className="data-table-wrap" style={{ marginTop: 10 }}>
                      <table className="data-table">
                        <thead><tr><th>类型</th><th>次数</th></tr></thead>
                        <tbody>
                          {byType.map(([type, count]) => <tr key={type}><td>{type}</td><td className="is-num">{count}</td></tr>)}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </>
              )}
    </AnalysisSection>
  )
}

/** 资源异常摘要。 */
function DecisionResourceBlock() {
  const { baseUrl } = useConnection()
  const query = useResource(baseUrl, {}, true)
  const report = query.data
  const summary = report?.summary
  const anomalies = ((report?.anomalies || []) as ResourceAnomaly[]).slice(0, 10)
  return (
    <AnalysisSection title="资源异常" note="块库 · 决策台资源分配摘要；只用于发现待复核项，不评价选手。">
      {query.isLoading ? <Loading label="正在读取资源…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : !report?.available ? <BoardEmpty title="当前范围没有可用样本">{report?.reason || ''}</BoardEmpty>
            : !summary ? <BoardEmpty title="暂无可算摘要" />
              : (
                <>
                  <div className="league-grid is-four">
                    <div className="league-card"><span>局数</span><b>{number(summary.games)}</b><em>局</em></div>
                    <div className="league-card"><span>选手行</span><b>{number(summary.rows)}</b><em>条</em></div>
                    <div className="league-card"><span>异常条目</span><b>{number(summary.anomalyCount)}</b><em>条</em></div>
                    <div className="league-card"><span>象限异常</span><b>{number(summary.quadrantFlagCount)}</b><em>条</em></div>
                  </div>
                  {anomalies.length ? (
                    <div className="data-table-wrap" style={{ marginTop: 10 }}>
                      <table className="data-table">
                        <thead><tr><th>选手</th><th>分路</th><th>英雄</th><th>经济占比</th><th>输出占比</th><th>说明</th></tr></thead>
                        <tbody>
                          {anomalies.map((row, index) => (
                            <tr key={`${row.seq || index}-${index}`}>
                              <td>{row.name || '—'}</td>
                              <td>{row.lane || '—'}</td>
                              <td>{row.hero || '—'}</td>
                              <td className="is-num">{percent(row.goldShare)}</td>
                              <td className="is-num">{percent(row.heroDamageShare)}</td>
                              <td>{row.text || row.kind || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </>
              )}
    </AnalysisSection>
  )
}

/** 龙控：双方龙数（终局面板）。 */
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
  { id: 'decision.loss', base: 'decision.loss', variant: '摘要', domain: 'match', title: '失利链', question: '失利窗口多少、类型分布如何？', filters: [], Component: DecisionLossBlock },
  { id: 'decision.resource', base: 'decision.resource', variant: '摘要', domain: 'player', title: '资源异常', question: '哪些选手资源/输出错配值得复核？', filters: [], Component: DecisionResourceBlock },
  { id: 'bp.objectives', base: 'bp.objectives', variant: '龙控', domain: 'bp', title: '龙控', question: '本队和对手的龙控净差多少？', filters: [], Component: BpObjectivesBlock },
  { id: 'bp.kill-death', base: 'bp.kill-death', variant: '汇总', domain: 'bp', title: '击杀与死亡', question: '击杀/死亡/助攻的总量净差？', filters: [], Component: BpKillDeathBlock }
]
