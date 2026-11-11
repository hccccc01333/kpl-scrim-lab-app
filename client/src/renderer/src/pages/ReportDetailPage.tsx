import { Link, useParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useResearchReport } from '../lib/hooks'
import { number } from '../lib/format'
import { BoardEmpty } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

export function ReportDetailPage() {
  const { baseUrl } = useConnection()
  const { id = '' } = useParams()
  const query = useResearchReport(baseUrl, id)
  const report = query.data

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !report) {
    return (
      <div className="page">
        <PageHeader eyebrow="REPORT" title="报告详情" actions={<Link className="btn" to="/training/reports">报告库</Link>} />
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </div>
    )
  }

  const result = report.result || {}
  const columns = result.columns || []
  const rows = result.rows || []
  const summary = result.summary || {}
  const summaryEntries = Object.entries(summary).slice(0, 6)

  return (
    <div className="page board-page report-page">
      <PageHeader
        eyebrow="REPORT SNAPSHOT"
        title={report.title || '未命名报告'}
        subtitle={`保存于 ${report.createdAt || '—'} · ${topicLabel(report.topic)}`}
        actions={<>
          <Link className="btn" to="/training/reports">报告库</Link>
          <button type="button" className="btn" onClick={() => window.print()}><Icon name="printer" />打印 / PDF</button>
        </>}
      />

      <article className="report-sheet">
        <header className="report-brand">
          <span className="report-mark"><Icon name="training" size={20} /></span>
          <div><b>赛训数据</b><small>TRAINING DATA</small></div>
          <span className="report-kind">结果快照</span>
        </header>
        <section className="report-title">
          <div><span className="report-eyebrow">ANALYSIS SNAPSHOT</span><h1>{report.title || '未命名报告'}</h1><p>{topicLabel(report.topic)} · 保存时的数据范围与结果</p></div>
          <div className="report-stamp"><span>保存日期</span><b>{report.createdAt?.slice(0, 10) || '—'}</b></div>
        </section>

        {summaryEntries.length ? (
          <section className="report-kpis" style={{ gridTemplateColumns: `repeat(${Math.min(4, summaryEntries.length)}, minmax(0, 1fr))` }}>
            {summaryEntries.map(([key, value]) => (
              <div key={key}><span>{fieldLabel(key)}</span><strong>{formatValue(value)}</strong><small>快照</small></div>
            ))}
          </section>
        ) : null}

        <div className="report-context"><span>结果快照</span>以下内容为保存时的数据与口径，不会随源数据变化。{result.sourceRows !== undefined ? ` 本队输入 ${number(result.sourceRows)} 条。` : ''}</div>

        <section className="report-section">
          <h2>结果明细</h2>
          {rows.length ? (
            <div className="data-table-wrap">
              <table className="report-table">
                <thead><tr>{columns.map((column) => <th key={column}>{fieldLabel(column)}</th>)}</tr></thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={index}>
                      {columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="这份报告没有结果行">保存时可能没有命中样本。</BoardEmpty>}
        </section>

        <footer className="report-footer">
          <span>{result.note || '请结合样本量查看结果。'}</span>
          <span>赛训数据 · 结果快照 · 内部资料</span>
        </footer>
      </article>

      {result.warnings?.length ? <div className="board-banner">来源提示：{result.warnings.join('；')}</div> : null}
    </div>
  )
}

const FIELD_LABELS: Record<string, string> = {
  date: '日期', session: '训练组', opponent: '对手', games: '对局', decided: '有胜负', wins: '胜场', losses: '负场',
  winRate: '胜率', kda: 'KDA', gpm: '分均经济', dpm: '分均输出', dtpm: '分均承伤', participation: '参团率',
  hero: '英雄', label: '对象', name: '名称', n: '样本', value: '当前值', percentile: '分位', p50: '中位数',
  p75: 'P75', p90: 'P90', mean: '均值', recentMean: '最近均值', recentN: '近期样本', change: '变化',
  std: '标准差', p10: 'P10', iqr: '四分位距', heroes: '英雄数', topHero: '最常用英雄', topShare: '头部占比',
  hhi: '集中度', effectiveHeroes: '有效英雄数', entropy: '熵', result: '结果', matchKey: '对局',
  gold4: '4 分钟经济差', gold10: '10 分钟经济差', goldEnd: '末次经济差'
}

const TOPIC_LABELS: Record<string, string> = {
  session_summary: '训练组汇总', player_form: '选手状态', hero_pool: '选手英雄池', hero_combos: '阵容组合',
  player_pairs: '双人搭档', tempo: '前期与优势转化', swing_windows: '经济转折窗口',
  hero_benchmark: '选手 × 英雄参照', resource_efficiency: '资源与产出'
}

function topicLabel(topic?: string | null): string {
  return TOPIC_LABELS[topic || ''] || topic || '分析快照'
}

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] || key
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
