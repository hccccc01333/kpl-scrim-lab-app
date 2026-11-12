/**
 * 上帝模式 · 第二十二批注册块（单局位置摘要 / 报告摘要 / 战队风格文字版）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { usePositions, useResearchReport, useTeams } from '../../lib/hooks'
import { number } from '../../lib/format'
import { teamAxes } from '../../lib/analysis/teams'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 单局十人平均位置摘要（位置图的文字版）。 */
function MatchPositionAverageBlock() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const key = pageContextFromPath(location.pathname).matchKey || ''
  const query = usePositions(baseUrl, key)
  const data = query.data
  if (!key) return <AnalysisSection title="本局平均位置"><BoardEmpty title="这个块要放在单局页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="本局平均位置"><Loading label="正在读取位置…" /></AnalysisSection>
  if (query.isError || !data) return <AnalysisSection title="本局平均位置"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const players = (data.players || []).filter((player) => (player.points || []).length)
  const rows = players.map((player) => {
    const points = player.points || []
    const avgX = points.reduce((sum, point) => sum + point[0], 0) / points.length
    const avgY = points.reduce((sum, point) => sum + point[1], 0) / points.length
    return { label: player.hero || player.nickname || `位置${player.slot}`, camp: player.camp, avgX, avgY, n: points.length }
  })
  return (
    <AnalysisSection title="本局平均位置" note="块库 · 逐秒位置的平均坐标（相对坐标，未定标地图时只作相对比较）。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>英雄</th><th>阵营</th><th>平均 X</th><th>平均 Y</th><th>采样点</th></tr></thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.label}-${index}`}>
                  <td>{row.label}</td>
                  <td>{row.camp || '—'}</td>
                  <td className="is-num">{number(row.avgX, 0)}</td>
                  <td className="is-num">{number(row.avgY, 0)}</td>
                  <td className="is-num">{row.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="这一局没有位置采样" />}
    </AnalysisSection>
  )
}

/** 报告摘要：报告详情页上下文。 */
function ResearchReportBlock() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const reportId = pageContextFromPath(location.pathname).reportId || ''
  const query = useResearchReport(baseUrl, reportId)
  const detail = query.data
  if (!reportId) return <AnalysisSection title="报告摘要"><BoardEmpty title="这个块要放在报告详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="报告摘要"><Loading label="正在读取报告…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="报告摘要"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const summary = detail.result?.summary || {}
  const entries = Object.entries(summary).slice(0, 12)
  return (
    <AnalysisSection title={`${detail.title || '报告'} · 摘要`} note={detail.result?.note || '块库 · 报告详情页上下文。'}>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead><tr><th>指标</th><th>值</th></tr></thead>
          <tbody>
            <tr><td>主题</td><td>{detail.topic || '—'}</td></tr>
            <tr><td>创建</td><td>{detail.createdAt || '—'}</td></tr>
            {entries.map(([key, value]) => (
              <tr key={key}><td>{key}</td><td>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </AnalysisSection>
  )
}

/** 战队风格文字版：强项/弱项一句话。 */
function TeamStyleBriefBlock() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const teams = [...(query.data?.teams || [])].filter((team) => (team.matches || 0) >= 1).sort((a, b) => (b.matches || 0) - (a.matches || 0)).slice(0, 8)
  return (
    <AnalysisSection title="战队风格 · 文字版" note="块库 · 每支对手的最强/最弱轴一句话。">
      {query.isLoading ? <Loading label="正在读取战队…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : teams.length ? (
            <div className="style-notes">
              {teams.map((team) => {
                const axes = teamAxes(team.percentiles).filter((axis) => typeof axis.value === 'number')
                const strongest = [...axes].sort((a, b) => (b.value || 0) - (a.value || 0))[0]
                const weakest = [...axes].sort((a, b) => (a.value || 0) - (b.value || 0))[0]
                return (
                  <div key={team.id}>
                    <b>{team.displayName || team.name}</b>
                    <span>
                      {strongest ? `${strongest.label}偏强（${Math.round(strongest.value || 0)} 分位）` : '样本不足'}
                      {weakest ? `；${weakest.label}偏弱（${Math.round(weakest.value || 0)} 分位）` : ''}
                      {team.matches < 3 ? '；样本少只作观察' : ''}
                    </span>
                  </div>
                )
              })}
            </div>
          ) : <BoardEmpty title="还没有战队样本" />}
    </AnalysisSection>
  )
}

export const POSITION_REPORT_BLOCKS: RegisteredBlock[] = [
  { id: 'match.position-average', base: 'match.position-average', variant: '平均坐标', domain: 'match', title: '本局平均位置', question: '这一局十个人的平均位置在哪？（单局页）', filters: [], Component: MatchPositionAverageBlock },
  { id: 'research.report-summary', base: 'research.report-summary', variant: '摘要', domain: 'team', title: '报告摘要', question: '这份报告的摘要指标？（报告详情页）', filters: [], Component: ResearchReportBlock },
  { id: 'team.style-brief', base: 'team.style-brief', variant: '文字', domain: 'team', title: '战队风格 · 文字版', question: '每支对手最强/最弱轴一句话？', filters: [], Component: TeamStyleBriefBlock }
]
