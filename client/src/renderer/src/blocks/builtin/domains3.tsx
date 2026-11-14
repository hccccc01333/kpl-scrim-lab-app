/**
 * 上帝模式 · 第四批注册块（概览）
 */
import { useConnection } from '../../lib/app-context'
import { useOverview } from '../../lib/hooks'
import { number, percent, signed } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
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
  }
]
