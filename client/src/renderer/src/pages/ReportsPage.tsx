import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useResearchReports } from '../lib/hooks'
import { number } from '../lib/format'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'

export function ReportsPage() {
  const { baseUrl } = useConnection()
  const query = useResearchReports(baseUrl)
  const navigate = useNavigate()
  const [start, setStart] = useState(mondayOf(new Date()))
  const reports = query.data?.reports || []

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const latest = reports[0]?.createdAt?.slice(0, 10) || '—'
  const topicLabel = (topic?: string) => TOPIC_LABELS[topic || ''] || topic || '分析快照'

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="REPORT LIBRARY"
        title="复盘与报告"
        subtitle="训练效果与已保存的分析快照放在同一处；报告保留当时的数据范围和结果。"
        actions={<>
          <Link className="btn" to="/training">训练计划</Link>
          <Link className="btn" to="/training/effect">训练效果</Link>
        </>}
      />

      <StatGrid items={[
        { label: '已保存报告', value: number(reports.length), note: '分析快照' },
        { label: '最近保存', value: latest, note: reports[0]?.title || '还没有报告' },
        { label: '训练效果', value: '只读', note: '干预记录对照' },
        { label: '训练周报', value: '按周生成', note: '健康过程汇总' }
      ]} />

      <AnalysisSection title="生成训练周报" note="默认从本周一开始，汇总 7 天内的训练课、对局、目标和复盘；打开后可打印或保存 PDF。">
        <div className="board-toolbar">
          <label className="board-muted">周报起始日</label>
          <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
          <button type="button" className="btn btn-sm" onClick={() => navigate(`/training/weekly/${start}`)}>生成周报 →</button>
          <Link className="btn btn-sm" to="/training/effect">看训练效果</Link>
        </div>
      </AnalysisSection>

      <AnalysisSection title={`已保存报告 · ${reports.length} 份`} note="按保存时间倒序；报告是保存时的结果快照，源数据变化后仍按当时口径回看。">
        {reports.length ? (
          <div className="report-card-grid">
            {reports.map((report) => (
              <Link to={`/training/reports/${encodeURIComponent(report.id)}`} className="report-card" key={report.id}>
                <div><span>{topicLabel(report.topic)}</span><b>{report.createdAt?.slice(0, 10) || '—'}</b></div>
                <h3>{report.title || '未命名报告'}</h3>
                <p>{topicLabel(report.topic)} · 保存时的结果与口径</p>
                <em>查看报告 →</em>
              </Link>
            ))}
          </div>
        ) : (
          <BoardEmpty title="还没有保存报告">
            报告库当前为空。训练课报告与周报可以直接生成并打印；分析型快照仍在工作台保存。
          </BoardEmpty>
        )}
      </AnalysisSection>

      <div className="board-foot">报告库只读；分析快照与训练周报的生成入口仍按 V3 当前可见范围保留。隐藏的研究专题不进入客户端。</div>
    </div>
  )
}

const TOPIC_LABELS: Record<string, string> = {
  session_summary: '训练组汇总', player_form: '选手状态', hero_pool: '选手英雄池', hero_combos: '阵容组合',
  player_pairs: '双人搭档', tempo: '前期与优势转化', swing_windows: '经济转折窗口',
  hero_benchmark: '选手 × 英雄参照', resource_efficiency: '资源与产出'
}

function mondayOf(date: Date): string {
  const copy = new Date(date)
  copy.setDate(copy.getDate() - (copy.getDay() + 6) % 7)
  return `${copy.getFullYear()}-${String(copy.getMonth() + 1).padStart(2, '0')}-${String(copy.getDate()).padStart(2, '0')}`
}
