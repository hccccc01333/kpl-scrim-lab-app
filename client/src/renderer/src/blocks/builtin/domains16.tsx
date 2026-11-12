/**
 * 上帝模式 · 第十七批注册块（决策台优势保持 / 报告库 / 本队教练 / 选手位置）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useAdvantage } from '../../lib/decision'
import { useCoachBoard, usePlayer, useResearchReports } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 优势保持：领先局与回撤概况。 */
function DecisionAdvantageBlock() {
  const { baseUrl } = useConnection()
  const query = useAdvantage(baseUrl, {}, true)
  const report = query.data
  const summary = report?.summary
  return (
    <AnalysisSection title="优势保持" note="块库 · 决策台优势保持摘要；只做描述，不给因果。">
      {query.isLoading ? <Loading label="正在读取优势保持…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : !report?.available ? <BoardEmpty title="当前范围没有可用样本">{report?.reason || ''}</BoardEmpty>
            : !summary ? <BoardEmpty title="优势保持暂无可算摘要" />
              : (
                <div className="league-grid is-four">
                  <div className="league-card"><span>局数</span><b>{number(summary.games)}</b><em>局</em></div>
                  <div className="league-card"><span>领先局</span><b>{number(summary.ledGames)}</b><em>局</em></div>
                  <div className="league-card"><span>被翻盘</span><b>{number(summary.comebacks)}</b><em>局 · {percent(summary.comebackRate)}</em></div>
                  <div className="league-card"><span>场均最大领先</span><b>{number(summary.avgMaxLead)}</b><em>金</em></div>
                  <div className="league-card"><span>场均回撤</span><b>{number(summary.avgDrawdown)}</b><em>金</em></div>
                  <div className="league-card"><span>10 分钟领先</span><b>{number(summary.avgLeadAt10)}</b><em>金</em></div>
                  <div className="league-card"><span>最大回撤</span><b>{number(summary.maxDrawdown)}</b><em>{summary.maxDrawdownGame?.label || '—'}</em></div>
                  <div className="league-card"><span>样本充分</span><b>{summary.enough ? '是' : '否'}</b><em>{summary.reason || '—'}</em></div>
                </div>
              )}
    </AnalysisSection>
  )
}

/** 报告库。 */
function ResearchReportsBlock() {
  const { baseUrl } = useConnection()
  const query = useResearchReports(baseUrl)
  const rows = [...(query.data?.reports || [])].slice(0, 15)
  return (
    <AnalysisSection title="报告库" note="块库 · 工作台生成的赛研报告（只读）。">
      {query.isLoading ? <Loading label="正在读取报告…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>标题</th><th>主题</th><th>类型</th><th>创建</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.title}</td>
                      <td>{row.topic || '—'}</td>
                      <td>{row.type || '—'}</td>
                      <td>{row.createdAt || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有报告" />}
    </AnalysisSection>
  )
}

/** 本队教练。 */
function OwnCoachBlock() {
  const { baseUrl } = useConnection()
  const query = useCoachBoard(baseUrl)
  const coach = query.data?.own?.coach
  return (
    <AnalysisSection title="本队教练" note="块库 · 工作台录入的本队教练。">
      {query.isLoading ? <Loading label="正在读取教练…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : <div className="league-grid is-four">
            <div className="league-card"><span>本队教练</span><b>{coach || '未录入'}</b><em>工作台可改</em></div>
            <div className="league-card"><span>已建档对手</span><b>{number((query.data?.teams || []).filter((team) => team.named).length)}</b><em>支</em></div>
          </div>}
    </AnalysisSection>
  )
}

/** 选手位置与评分。 */
function PlayerPositionsBlock() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const player = pageContextFromPath(location.pathname).player || ''
  const query = usePlayer(baseUrl, player)
  const stats = query.data?.stats
  if (!player) return <AnalysisSection title="选手位置"><BoardEmpty title="这个块要放在选手详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="选手位置"><Loading label="正在读取选手…" /></AnalysisSection>
  if (query.isError) return <AnalysisSection title="选手位置"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const positions = stats?.positions || []
  return (
    <AnalysisSection title={`${stats?.label || player} · 位置与评分`} note="块库 · 选手详情页上下文；位置来自营地十人面板。">
      <div className="league-grid is-four">
        <div className="league-card"><span>评分</span><b>{stats?.rating === null || stats?.rating === undefined ? '—' : number(stats.rating, 1)}</b><em>营地评分</em></div>
        <div className="league-card"><span>位置</span><b>{positions.length ? positions.join(' / ') : '—'}</b><em>本期出场位置</em></div>
      </div>
    </AnalysisSection>
  )
}

export const DECISION_MISC_BLOCKS: RegisteredBlock[] = [
  { id: 'decision.advantage', base: 'decision.advantage', variant: '摘要', domain: 'match', title: '优势保持', question: '领先局有多少、被翻盘多少、回撤多大？', filters: [], Component: DecisionAdvantageBlock },
  { id: 'research.reports', base: 'research.reports', variant: '列表', domain: 'team', title: '报告库', question: '工作台里有哪些赛研报告？', filters: [], Component: ResearchReportsBlock },
  { id: 'coach.own', base: 'coach.own', variant: '本队', domain: 'team', title: '本队教练', question: '本队教练是谁？已建档多少对手？', filters: [], Component: OwnCoachBlock },
  { id: 'player.positions', base: 'player.positions', variant: '位置评分', domain: 'player', title: '选手位置与评分', question: '这名选手的位置与评分？（选手详情页）', filters: [], Component: PlayerPositionsBlock }
]
