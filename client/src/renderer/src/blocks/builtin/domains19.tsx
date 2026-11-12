/**
 * 上帝模式 · 第二十批注册块（决策台分析目录 / 回放覆盖 / 对手覆盖）
 */
import { useConnection } from '../../lib/app-context'
import { useDecisionCatalog } from '../../lib/decision'
import { number, percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 决策台分析目录。 */
function DecisionCatalogBlock() {
  const { baseUrl } = useConnection()
  const query = useDecisionCatalog(baseUrl)
  const catalog = query.data
  const analyses = (catalog?.analyses || []).slice(0, 20)
  return (
    <AnalysisSection title="分析目录" note="块库 · 当前数据能跑哪些决策分析、样本是否够。">
      {query.isLoading ? <Loading label="正在读取分析目录…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : !catalog ? <BoardEmpty title="暂无可用的分析目录" />
            : (
              <>
                <div className="league-grid is-four">
                  <div className="league-card"><span>分析项</span><b>{number(analyses.length)}</b><em>项</em></div>
                  <div className="league-card"><span>可用</span><b>{number(analyses.filter((item) => item.available).length)}</b><em>项</em></div>
                  <div className="league-card"><span>覆盖对局</span><b>{number(catalog.coverage?.games)}</b><em>局</em></div>
                  <div className="league-card"><span>覆盖对手</span><b>{number((catalog?.opponents || []).length)}</b><em>支</em></div>
                </div>
                {analyses.length ? (
                  <div className="data-table-wrap" style={{ marginTop: 10 }}>
                    <table className="data-table">
                      <thead><tr><th>分析</th><th>层</th><th>可用</th><th>样本局</th><th>说明</th></tr></thead>
                      <tbody>
                        {analyses.map((item) => (
                          <tr key={item.id}>
                            <td>{item.name}</td>
                            <td>{item.layer || item.level || '—'}</td>
                            <td>{item.available ? '是' : '否'}</td>
                            <td className="is-num">{number(item.games)}</td>
                            <td>{item.available ? (item.note || '—') : (item.emptyReason || item.note || '—')}</td>
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

/** 回放覆盖。 */
function DecisionReplayCoverageBlock() {
  const { baseUrl } = useConnection()
  const query = useDecisionCatalog(baseUrl)
  const games = query.data?.games || []
  const count = (key: 'hasReplay' | 'hasPositions' | 'hasFights' | 'hasEconomy') => games.filter((game) => Boolean(game[key])).length
  return (
    <AnalysisSection title="回放覆盖" note="块库 · 决策台分析依赖的回放/位置/团战/经济覆盖。">
      {query.isLoading ? <Loading label="正在读取回放覆盖…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : games.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>数据</th><th>覆盖局</th><th>覆盖率</th></tr></thead>
                <tbody>
                  {[
                    { label: '官方回放', key: 'hasReplay' as const },
                    { label: '逐秒位置', key: 'hasPositions' as const },
                    { label: '团战账本', key: 'hasFights' as const },
                    { label: '经济时间轴', key: 'hasEconomy' as const }
                  ].map((row) => {
                    const value = count(row.key)
                    return (
                      <tr key={row.key}>
                        <td>{row.label}</td>
                        <td className="is-num">{value} / {games.length}</td>
                        <td className="is-num">{percent(games.length ? value / games.length * 100 : null)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有可用的对局" />}
    </AnalysisSection>
  )
}

/** 对手覆盖。 */
function DecisionOpponentsBlock() {
  const { baseUrl } = useConnection()
  const query = useDecisionCatalog(baseUrl)
  const rows = [...(query.data?.opponents || [])].sort((a, b) => (b.games || 0) - (a.games || 0)).slice(0, 15)
  return (
    <AnalysisSection title="对手覆盖" note="块库 · 决策台对手维度的局数与回放覆盖。">
      {query.isLoading ? <Loading label="正在读取对手覆盖…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>对局</th><th>回放</th><th>样本充足</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.name || row.id}</td>
                      <td className="is-num">{number(row.games)}</td>
                      <td className="is-num">{number(row.replayGames)}</td>
                      <td>{row.enough ? '是' : '否'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有对手覆盖数据" />}
    </AnalysisSection>
  )
}

export const DECISION_CATALOG_BLOCKS: RegisteredBlock[] = [
  { id: 'decision.catalog', base: 'decision.catalog', variant: '目录', domain: 'match', title: '分析目录', question: '当前数据能跑哪些决策分析？', filters: [], Component: DecisionCatalogBlock },
  { id: 'decision.replay-coverage', base: 'decision.replay-coverage', variant: '覆盖', domain: 'match', title: '回放覆盖', question: '官方回放/位置/团战/经济覆盖多少局？', filters: [], Component: DecisionReplayCoverageBlock },
  { id: 'decision.opponents', base: 'decision.opponents', variant: '覆盖', domain: 'team', title: '对手覆盖', question: '每个对手的局数与回放覆盖？', filters: [], Component: DecisionOpponentsBlock }
]
