/**
 * 上帝模式 · 第十六批注册块（选手池概览 / 未认领账号 / 对手 BP 池 / 赛果分布）
 */
import { useConnection } from '../../lib/app-context'
import { useMatches, usePlayerBoard, useTeamBp } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 选手池概览。 */
function PlayerPoolSummaryBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayerBoard(baseUrl)
  const summary = query.data?.summary
  return (
    <AnalysisSection title="选手池概览" note="块库 · 名单、出场、替补与未认领账号。">
      {query.isLoading ? <Loading label="正在读取选手池…" />
        : query.isError || !summary ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : (
            <div className="league-grid is-four">
              <div className="league-card"><span>名单</span><b>{number(summary.roster)}</b><em>人</em></div>
              <div className="league-card"><span>有出场</span><b>{number(summary.played)}</b><em>人</em></div>
              <div className="league-card"><span>替补</span><b>{number(summary.bench)}</b><em>人</em></div>
              <div className="league-card"><span>未认领</span><b>{number(summary.unbound)}</b><em>账号</em></div>
              <div className="league-card"><span>状态上升</span><b>{number(summary.rising)}</b><em>人</em></div>
              <div className="league-card"><span>状态下降</span><b>{number(summary.falling)}</b><em>人</em></div>
              <div className="league-card"><span>样本局</span><b>{number(summary.matches)}</b><em>局</em></div>
              <div className="league-card"><span>可算状态</span><b>{number(summary.formReady)}</b><em>人</em></div>
            </div>
          )}
    </AnalysisSection>
  )
}

/** 未认领账号。 */
function PlayerUnboundBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayerBoard(baseUrl)
  const rows = [...(query.data?.unbound || [])].sort((a, b) => b.games - a.games).slice(0, 15)
  return (
    <AnalysisSection title="未认领账号" note="块库 · 有对局但还没绑定选手身份的账号；认领后才会进选手统计。">
      {query.isLoading ? <Loading label="正在读取未认领账号…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>账号</th><th>局数</th><th>最近对局</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td className="is-num">{row.games}</td>
                      <td>{row.lastDate || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="没有未认领账号" />}
    </AnalysisSection>
  )
}

/** 对手 BP 池：可用英雄与选禁覆盖。 */
function TeamBpPoolBlock() {
  const { baseUrl } = useConnection()
  const query = useTeamBp(baseUrl)
  const rows = [...(query.data || [])].sort((a, b) => b.games - a.games).slice(0, 12)
  const rate = (value: number, total: number) => (total ? percent(value / total * 100) : '—')
  return (
    <AnalysisSection title="对手 BP 池" note="块库 · 每支对手的可用局数、选用/禁用英雄覆盖。">
      {query.isLoading ? <Loading label="正在读取战队 BP…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>局数</th><th>可用</th><th>选用英雄</th><th>禁用英雄</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.name}</td>
                      <td className="is-num">{row.games}</td>
                      <td className="is-num">{row.available}</td>
                      <td className="is-num">{row.picks.length}（{rate(row.picks.length, row.available)}）</td>
                      <td className="is-num">{row.bans.length}（{rate(row.bans.length, row.available)}）</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有战队 BP 样本" />}
    </AnalysisSection>
  )
}

/** 赛果分布。 */
function ResultDistributionBlock() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const matches = query.data || []
  const buckets = [
    { label: '胜', test: (result: string) => result === 'win' },
    { label: '负', test: (result: string) => result === 'loss' },
    { label: '无胜负', test: (result: string) => result !== 'win' && result !== 'loss' }
  ]
  return (
    <AnalysisSection title="赛果分布" note="块库 · 当前样本的胜/负/无胜负占比。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : matches.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>结果</th><th>局数</th><th>占比</th></tr></thead>
                <tbody>
                  {buckets.map((bucket) => {
                    const count = matches.filter((match) => bucket.test(String(match.result || ''))).length
                    return (
                      <tr key={bucket.label}>
                        <td>{bucket.label}</td>
                        <td className="is-num">{count}</td>
                        <td className="is-num">{percent(matches.length ? count / matches.length * 100 : null)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有对局" />}
    </AnalysisSection>
  )
}

export const POOL_RESULT_BLOCKS: RegisteredBlock[] = [
  { id: 'player.pool-summary', base: 'player.pool-summary', variant: '概览', domain: 'player', title: '选手池概览', question: '名单里有多少人、多少有出场、多少没认领？', filters: [], Component: PlayerPoolSummaryBlock },
  { id: 'player.unbound', base: 'player.unbound', variant: '未认领', domain: 'player', title: '未认领账号', question: '还有哪些账号没绑定选手身份？', filters: [], Component: PlayerUnboundBlock },
  { id: 'bp.team-pool', base: 'bp.team-pool', variant: 'BP 池', domain: 'bp', title: '对手 BP 池', question: '每支对手的选用/禁用英雄覆盖有多宽？', filters: [], Component: TeamBpPoolBlock },
  { id: 'match.result-dist', base: 'match.result-dist', variant: '赛果', domain: 'match', title: '赛果分布', question: '胜/负/无胜负各占多少？', filters: [], Component: ResultDistributionBlock }
]
