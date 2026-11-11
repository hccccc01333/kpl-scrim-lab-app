import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useMatches, useSchedules, useTeams, useTrainingEffect, useWeeklyMetrics } from '../lib/hooks'
import { api, assetUrl } from '../lib/api'
import { pushToast } from '../lib/toast'
import { duration as fmtDuration, number, percent } from '../lib/format'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

export function WeeklyReportPage() {
  const { baseUrl } = useConnection()
  const { start: param = '' } = useParams()
  const navigate = useNavigate()
  const start = /^\d{4}-\d{2}-\d{2}$/.test(param) ? param : mondayOf(new Date())
  const previousStart = shiftDate(start, -7)
  const currentQuery = useWeeklyMetrics(baseUrl, start)
  const previousQuery = useWeeklyMetrics(baseUrl, previousStart)
  const scheduleQuery = useSchedules(baseUrl)
  const effectQuery = useTrainingEffect(baseUrl)
  const matchesQuery = useMatches(baseUrl)
  const teamsQuery = useTeams(baseUrl)
  const [draft, setDraft] = useState(start)
  const exportImage = async () => {
    try {
      const result = await api<{ url: string }>(baseUrl, '/api/studio/workspace/reports/screenshot', { method: 'POST', body: { path: `weekly/${start}` }, timeout: 180_000 })
      await window.kpl.openExternal(assetUrl(baseUrl, result.url))
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '图片导出失败', 'error')
    }
  }

  useEffect(() => { setDraft(start) }, [start])

  const end = shiftDate(start, 6)
  const schedules = (scheduleQuery.data?.schedules || []).filter((schedule) => inRange(schedule.date, start, end))
  const matches = (matchesQuery.data || []).filter((match) => inRange(match.date, start, end))
  const effects = (effectQuery.data?.results || []).filter((effect) => inRange(effect.start_date, start, end))
  const metrics = currentQuery.data?.metrics || {}
  const previousMetrics = previousQuery.data?.metrics || {}
  const metric = (id: string, source = metrics) => source[id]?.value ?? null
  const teamName = (id?: string | null) => (teamsQuery.data?.teams || []).find((team) => team.id === id)?.displayName || '未指定对手'

  const goals = useMemo(() => {
    const list: string[] = []
    for (const schedule of schedules) {
      try {
        const items = JSON.parse(schedule.goals || '[]')
        for (const goal of Array.isArray(items) ? items : []) {
          const label = typeof goal === 'string' ? goal : String(goal?.label || '')
          if (label && !list.includes(label)) list.push(label)
        }
      } catch { /* 非 JSON 目标按空处理 */ }
    }
    return list
  }, [schedules])
  const reviews = schedules.filter((schedule) => schedule.review).map((schedule) => ({ date: schedule.date, review: schedule.review }))
  const wins = matches.filter((match) => match.result === 'win').length
  const losses = matches.filter((match) => match.result === 'loss').length
  const winRate = wins + losses ? wins / (wins + losses) * 100 : null
  const average = matches.map((match) => Number(match.duration)).filter((value) => Number.isFinite(value) && value > 0)
  const avgDuration = average.length ? average.reduce((sum, value) => sum + value, 0) / average.length : null
  const sessionCount = schedules.length
  const gameCount = matches.length
  const goalCompletion = goalCompletionOf(schedules)
  const reviewCompletion = schedules.length ? schedules.filter((schedule) => schedule.review_status === 'done').length / schedules.length * 100 : null
  const meanEffect = effects.filter((effect) => effect.effect?.available).length
    ? effects.filter((effect) => effect.effect?.available).reduce((sum, effect) => sum + (effect.effect?.effectSize || 0), 0) / effects.filter((effect) => effect.effect?.available).length
    : null
  const previous = {
    sessions: metric('training.week_session_count', previousMetrics) ?? 0,
    games: metric('training.week_game_count', previousMetrics) ?? (metric('week.match_count', previousMetrics) ?? 0),
    goals: metric('training.week_goal_completion', previousMetrics),
    reviews: metric('training.week_review_completion', previousMetrics)
  }
  const compare = [
    { label: '训练课', current: sessionCount, before: previous.sessions, unit: ' 场', rate: false },
    { label: '训练局数', current: gameCount, before: previous.games, unit: ' 局', rate: false },
    { label: '目标达成率', current: goalCompletion, before: previous.goals, unit: '%', rate: true },
    { label: '复盘完成率', current: reviewCompletion, before: previous.reviews, unit: '%', rate: true }
  ]

  if (currentQuery.isLoading || scheduleQuery.isLoading) return <SkeletonPage cards={2} />
  if (currentQuery.isError || scheduleQuery.isError) {
    return <div className="page"><ErrorState error={currentQuery.error || scheduleQuery.error} onRetry={() => { void currentQuery.refetch(); void scheduleQuery.refetch() }} /></div>
  }

  return (
    <div className="page board-page report-page">
      <PageHeader
        eyebrow="WEEKLY REPORT"
        title={<>训练周报<em>{start} — {end}</em></>}
        actions={<>
          <Link className="btn" to="/training/reports">报告库</Link>
          <button type="button" className="btn" onClick={() => void exportImage()}><Icon name="copy" />导出图片</button>
          <button type="button" className="btn" onClick={() => window.print()}><Icon name="printer" />打印 / PDF</button>
        </>}
      />

      <div className="board-toolbar">
        <label className="board-muted">周报起始日</label>
        <input type="date" value={draft} onChange={(event) => setDraft(event.target.value)} />
        <button type="button" className="btn btn-sm" onClick={() => navigate(`/training/weekly/${draft}`)}>生成周报</button>
        <Link className="btn btn-sm" to={`/training/weekly/${previousStart}`}>上一周</Link>
      </div>

      <article className="report-sheet">
        <header className="report-brand">
          <span className="report-mark"><Icon name="training" size={20} /></span>
          <div><b>赛训数据</b><small>TRAINING DATA</small></div>
          <span className="report-kind">训练周报</span>
        </header>
        <section className="report-title">
          <div><span className="report-eyebrow">WEEKLY REPORT</span><h1>{start} — {end}</h1><p>按训练课与对局汇总 · 共 {number(schedules.length)} 场训练、{number(matches.length)} 局</p></div>
          <div className="report-stamp"><span>生成日期</span><b>{new Date().toISOString().slice(0, 10)}</b></div>
        </section>
        <section className="report-kpis">
          {[['训练课', number(sessionCount), '场'], ['训练局数', number(gameCount), '局'], ['目标达成率', percent(goalCompletion), '本周'], ['复盘完成率', percent(reviewCompletion), '本周']].map(([label, value, note]) => (
            <div key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>
          ))}
        </section>
        <div className="report-context"><span>对局上下文</span>胜率 {percent(winRate)} · 场均 {fmtDuration(avgDuration)} · {wins} 胜 {losses} 负</div>
        <section className="report-compare">
          {compare.map((row) => {
            const display = (value: number | null) => value === null ? '—' : row.rate ? percent(value) : `${number(value)}${row.unit}`
            const delta = row.current === null || row.before === null ? null : Number(row.current) - Number(row.before)
            return <div key={row.label}><span>{row.label}</span><b>{display(row.current)}</b><small>上周 {display(row.before)}{delta === null ? '' : delta === 0 ? ' · 持平' : ` · ${delta > 0 ? '↑' : '↓'} ${row.rate ? `${number(Math.abs(delta), 1)} pp` : `${number(Math.abs(delta))}${row.unit}`}`}</small></div>
          })}
        </section>
        <section className="report-columns">
          <div className="report-main">
            <div className="report-section"><h2>本周训练课</h2>
              {schedules.length ? (
                <table className="report-table"><thead><tr><th>日期</th><th>对手</th><th>训练组</th><th>状态</th><th>复盘</th></tr></thead><tbody>
                  {schedules.map((schedule) => (
                    <tr key={schedule.id}><td>{schedule.date}</td><td>{teamName(schedule.opponent_team_id)}</td><td>{schedule.session || '—'}</td><td>{STATUS_LABEL[schedule.status || ''] || schedule.status || '—'}</td><td>{schedule.review_status === 'done' ? '已复盘' : '待复盘'}</td></tr>
                  ))}
                </tbody></table>
              ) : <p className="report-muted">本周没有登记训练课。</p>}
            </div>
            <div className="report-section"><h2>对局明细</h2>
              {matches.length ? (
                <table className="report-table"><thead><tr><th>日期</th><th>对手</th><th>结果</th><th>时长</th><th>对局</th></tr></thead><tbody>
                  {matches.slice(0, 12).map((match) => (
                    <tr key={match.key}><td>{match.date}</td><td>{match.opponent || '未标注'}</td><td>{match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '—'}</td><td>{fmtDuration(match.duration)}</td><td><Link to={`/matches/${encodeURIComponent(match.key)}`}>复盘 →</Link></td></tr>
                  ))}
                </tbody></table>
              ) : <p className="report-muted">本周没有对局记录。</p>}
            </div>
          </div>
          <aside className="report-side">
            <div className="report-section"><h2>本周训练目标</h2>{goals.length ? <ol className="report-goals">{goals.map((goal) => <li key={goal}>{goal}</li>)}</ol> : <p className="report-muted">本周还没有写训练目标。</p>}</div>
            <div className="report-section"><h2>教练复盘</h2>{reviews.length ? reviews.map((item) => <div className="report-review-item" key={item.date}><b>{item.date}</b><p>{item.review}</p></div>) : <p className="report-muted">本周还没有赛后复盘。</p>}</div>
            <div className="report-section"><h2>训练效果</h2>{effects.length ? <div className="report-effect"><b>{number(effects.length)} 条干预记录</b><span>可对比 {number(effects.filter((effect) => effect.effect?.available).length)} 条 · 平均效应量 {meanEffect === null ? '—' : number(meanEffect, 2)}</span></div> : <p className="report-muted">本周没有训练干预记录。</p>}</div>
          </aside>
        </section>
        <footer className="report-footer"><span>数据来源：训练计划、对局档案与训练效果</span><span>赛训数据 · {new Date().toISOString().slice(0, 10)} · 内部资料</span></footer>
      </article>

      <AnalysisSection title="这周怎么读" note="周报只汇总过程与结果，不把胜率当成训练质量。">
        <p className="board-note">训练课与目标来自训练计划；对局来自已确认的营地记录；训练效果只统计有完整年份、且两侧样本足够的干预记录。</p>
      </AnalysisSection>
    </div>
  )
}

const STATUS_LABEL: Record<string, string> = { planned: '已计划', confirmed: '已确认', completed: '已完成', cancelled: '已取消' }

function mondayOf(date: Date): string {
  const copy = new Date(date)
  copy.setDate(copy.getDate() - (copy.getDay() + 6) % 7)
  return local(copy)
}

function shiftDate(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00`)
  date.setDate(date.getDate() + days)
  return local(date)
}

function local(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function inRange(value: string | null | undefined, start: string, end: string): boolean {
  const text = String(value || '')
  return text >= start && text <= end
}

function goalCompletionOf(schedules: { goals?: string | null }[]): number | null {
  let total = 0
  let achieved = 0
  for (const schedule of schedules) {
    try {
      const items = JSON.parse(schedule.goals || '[]')
      for (const goal of Array.isArray(items) ? items : []) {
        if (typeof goal !== 'object' || !goal) continue
        total += 1
        if ((goal as { status?: string }).status === 'achieved') achieved += 1
      }
    } catch { /* 非 JSON 目标忽略 */ }
  }
  return total ? achieved / total * 100 : null
}
