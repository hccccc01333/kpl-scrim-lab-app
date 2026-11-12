/**
 * 上帝模式 · 第四批注册块（概览 / 决策台）
 */
import { Link } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useOverview } from '../../lib/hooks'
import { useBriefing, type DecisionBriefingItem } from '../../lib/decision'
import { number, percent, signed } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 总战绩卡：局数、胜率、场均金差、时间轴覆盖。 */
function OverviewRecordBlock() {
  const { baseUrl } = useConnection()
  const query = useOverview(baseUrl)
  const data = query.data
  if (query.isLoading) return <AnalysisSection title="总战绩"><Loading label="正在读取概览…" /></AnalysisSection>
  if (query.isError || !data) return <AnalysisSection title="总战绩"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const { summary, team } = data
  return (
    <AnalysisSection title="总战绩" note="块库 · 营地终局面板口径；样本随工作台数据实时更新。">
      <div className="league-grid is-four">
        <div className="league-card"><span>对局总数</span><b>{number(summary.matches)}</b><em>局</em></div>
        <div className="league-card"><span>有胜负胜率</span><b>{percent(summary.winRate)}</b><em>{number(summary.wins)} 胜 / {number(summary.decided)} 局</em></div>
        <div className="league-card"><span>场均金差</span><b>{signed(team.avgGoldDiff)}</b><em>本队减对手</em></div>
        <div className="league-card"><span>时间轴覆盖</span><b>{number(summary.coverage.timelineMatches)}</b><em>局</em></div>
      </div>
    </AnalysisSection>
  )
}

/** 今天先看：决策台自动挑出的问题清单。 */
function BriefingBlock() {
  const { baseUrl } = useConnection()
  const query = useBriefing(baseUrl, { limit: 6 })
  const items: DecisionBriefingItem[] = query.data?.items || []
  return (
    <AnalysisSection title="今天先看" note="块库 · 从完整回放里挑出的可行动问题；点进决策台看证据。">
      {query.isLoading ? <Loading label="正在挑问题…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : items.length ? (
            <div className="decision-overview-list">
              {items.slice(0, 6).map((item) => (
                <div className={`decision-overview-item tone-${['high', 'medium', 'low'].includes(String(item.severity)) ? String(item.severity) : 'low'}`} key={item.id}>
                  <div className="decision-overview-item-head"><b>{item.title}</b>{item.caveat ? <small>待复核</small> : null}</div>
                  <div className="decision-overview-item-foot">
                    {(item.evidence || []).slice(0, 2).map((evidence, index) => (
                      evidence.game ? <Link className="decision-chip" key={`${evidence.game}-${index}`} to={`/matches/${encodeURIComponent(evidence.game)}`}>{evidence.label || evidence.game}</Link> : null
                    ))}
                    <Link className="decision-overview-more" to="/decision">进入决策台 →</Link>
                  </div>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="暂时没有足够证据的问题" />}
    </AnalysisSection>
  )
}

export const HOME_BLOCKS: RegisteredBlock[] = [
  {
    id: 'overview.record',
    base: 'overview.record',
    variant: '总战绩',
    domain: 'match',
    title: '总战绩',
    question: '当前样本总共多少局、胜率多少、场均金差多少？',
    filters: [],
    Component: OverviewRecordBlock
  },
  {
    id: 'decision.briefing',
    base: 'decision.briefing',
    variant: '问题清单',
    domain: 'team',
    title: '今天先看',
    question: '这批数据里最值得先复盘的问题是什么？',
    filters: [],
    Component: BriefingBlock
  }
]
