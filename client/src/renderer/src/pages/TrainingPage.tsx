import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useSchedules, useTeams, useTrainingDashboard } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { duration as fmtDuration } from '../lib/format'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid, WinRing } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import type { ScheduleRow, TrainingWeek } from '../lib/types'

const STATUS_LABEL: Record<string, string> = {
  planned: '已计划', confirmed: '已确认', completed: '已完成', cancelled: '已取消'
}

export function TrainingPage() {
  const { baseUrl } = useConnection()
  const query = useTrainingDashboard(baseUrl)
  const scheduleQuery = useSchedules(baseUrl)
  const teamsQuery = useTeams(baseUrl)
  const weeks = useMemo(() => (query.data?.weeks || []) as TrainingWeek[], [query.data?.weeks])
  const schedules = scheduleQuery.data?.schedules || []
  const goals = (query.data?.goals || {}) as Record<string, number>
  const current = query.data?.current || weeks[weeks.length - 1]
  const previous = weeks[weeks.length - 2]
  const totalGoals = Object.values(goals).reduce((sum, value) => sum + (Number(value) || 0), 0)
  const goalPct = current?.goalCompletion ?? (totalGoals ? (Number(goals.achieved) || 0) / totalGoals * 100 : null)
  const totalSessions = weeks.reduce((sum, week) => sum + (week.sessionCount || 0), 0)
  const totalGames = weeks.reduce((sum, week) => sum + (week.gameCount || 0), 0)
  const today = new Date().toISOString().slice(0, 10)
  const teamName = (id?: string | null) => (teamsQuery.data?.teams || []).find((team) => team.id === id)?.displayName || '未指定对手'
  const ordered = useMemo(() => [...schedules].sort((a, b) => String(b.date).localeCompare(String(a.date)) || String(b.start_time || '').localeCompare(String(a.start_time || ''))), [schedules])
  const upcoming = ordered.filter((schedule) => String(schedule.date) >= today && schedule.status !== 'cancelled')
  const next = [...upcoming].reverse()[0]
  const days = query.data?.days || []
  const recent = query.data?.recent || []
  const maxGames = Math.max(1, ...weeks.map((week) => week.gameCount || 0))

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !query.data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const trend = (now?: number | null, before?: number | null, suffix = '', digits = 0) => {
    if (now === null || now === undefined || before === null || before === undefined) return '—'
    if (Number(now) === Number(before)) return '持平'
    const delta = Number(now) - Number(before)
    return `${delta > 0 ? '↑' : '↓'} ${number(Math.abs(delta), digits)}${suffix}`
  }

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TRAINING PULSE"
        title="训练计划"
        subtitle="登记训练赛时间、对手与赛制；看板只看训练过程，不把对局胜率当训练成绩。"
        actions={<>
          <Link className="btn" to="/training/reports">复盘与报告</Link>
          <Link className="btn" to="/training/effect">训练效果</Link>
        </>}
      />

      <StatGrid items={[
        { label: '本周训练课', value: number(current?.sessionCount || 0), note: trend(current?.sessionCount, previous?.sessionCount, ' 场') },
        { label: '本周训练局', value: number(current?.gameCount || 0), note: trend(current?.gameCount, previous?.gameCount, ' 局') },
        { label: '目标达成率', value: percent(goalPct), note: trend(goalPct, previous?.goalCompletion, ' pp', 1), tone: 'accent' },
        { label: '复盘完成率', value: percent(current?.reviewCompletion), note: `${number(totalSessions)} 场累计` },
        { label: '近 8 周训练', value: `${number(totalSessions)} 场 / ${number(totalGames)} 局`, note: current?.label || '—' },
        { label: '已登记计划', value: number(schedules.length), note: upcoming.length ? `下一场 ${next?.date} ${next?.start_time || ''}` : '暂无未来计划' }
      ]} />

      <div className="board-grid-2">
        <AnalysisSection title="近 8 周训练负荷" note="按训练课挂接对局统计；柱长为相对值。">
          {totalSessions ? (
            <div className="week-bars">
              {weeks.map((week) => (
                <div className="week-bar" key={week.start}>
                  <span>{week.label}</span>
                  <div><i style={{ width: `${((week.gameCount || 0) / maxGames) * 100}%` }} /></div>
                  <b>{number(week.gameCount)} 局</b>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="近 8 周还没有训练课">先在工作台登记计划并关联对局，训练负荷会自动出现。</BoardEmpty>}
        </AnalysisSection>

        <AnalysisSection title="目标达成" note="工作台指标层判定；缺数据的目标显示待判定，不按 0 计算。">
          <div className="dash-goal-band">
            <WinRing value={goalPct} label="目标达成" size={104} />
            <div className="dash-goal-legend">
              {[['achieved', '达成'], ['partial', '部分'], ['missed', '未达成'], ['pending', '未评估']].map(([key, label]) => (
                <span key={key}><i className={`is-${key}`} />{label}<b>{number(goals[key] || 0)}</b></span>
              ))}
            </div>
          </div>
          <p className="board-note">目标来自训练课；客户端只读展示。</p>
        </AnalysisSection>
      </div>

      <div className="board-grid-2">
        <AnalysisSection title="训练节奏" note="近 8 周每天的训练课与对局；格越深表示训练量越大。">
          {days.length ? (
            <div className="dash-heat">
              <div className="dash-heat-head"><span />{['一', '二', '三', '四', '五', '六', '日'].map((day) => <i key={day}>{day}</i>)}</div>
              <div className="dash-heat-grid">
                {days.map((day) => {
                  const level = day.games ? Math.min(4, Math.max(1, Math.ceil(day.games / 2))) : (day.sessions ? 1 : 0)
                  return <i key={day.date} className={`dash-heat-cell is-${level}`} title={`${day.date} · ${day.sessions} 场 · ${day.games} 局`} />
                })}
              </div>
              <div className="dash-heat-foot"><span>少</span>{[0, 1, 2, 3, 4].map((level) => <i key={level} className={`dash-heat-cell is-${level}`} />)}<span>多</span></div>
            </div>
          ) : <BoardEmpty title="还没有训练节奏" />}
        </AnalysisSection>

        <AnalysisSection title="最近训练课" note="按日期倒序；点进训练课看目标、对局与复盘。">
          {recent.length ? (
            <div className="dash-recent">
              {recent.map((item) => (
                <Link to={`/training/sessions/${encodeURIComponent(item.id)}`} className="dash-session" key={item.id}>
                  <span>{item.date?.slice(5)}</span>
                  <span><b>{item.opponent || '未指定对手'}</b><small>{item.session || '训练组未定'} · {number(item.games)} 局</small></span>
                  <span>{number(item.achieved)} / {number(item.goals)}</span>
                  <i className={item.reviewed ? 'is-done' : ''} title={item.reviewed ? '已复盘' : '待复盘'} />
                </Link>
              ))}
            </div>
          ) : <BoardEmpty title="还没有训练课">计划与对局关联后会出现在这里。</BoardEmpty>}
        </AnalysisSection>
      </div>

      <AnalysisSection
        title={`训练计划 · ${schedules.length} 条`}
        note="只读排期；计划编辑仍在工作台。点一行进入训练课分析。"
      >
        {next ? (
          <div className="plan-next">
            <span>下一场</span>
            <b>{next.date} {next.start_time || ''}</b>
            <p>对阵 {teamName(next.opponent_team_id)} · {next.session || '训练组未定'} · {next.format || '赛制未定'}</p>
            <Link to={`/training/sessions/${encodeURIComponent(next.id)}`}>打开训练课 →</Link>
          </div>
        ) : null}
        {ordered.length ? (
          <div className="plan-list">
            {ordered.map((schedule) => (
              <PlanRow schedule={schedule} teamName={teamName(schedule.opponent_team_id)} key={schedule.id} />
            ))}
          </div>
        ) : <BoardEmpty title="还没有登记任何计划">工作台登记日期、对手与赛制后，训练课会自动归集对局。</BoardEmpty>}
      </AnalysisSection>

      <div className="board-foot">训练计划 / 训练课编辑、数据准备仍是工作台写操作；客户端只读展示看板、排期与分析。</div>
    </div>
  )
}

function PlanRow({ schedule, teamName }: { schedule: ScheduleRow; teamName: string }) {
  let goals: unknown[] = []
  try {
    const parsed = JSON.parse(schedule.goals || '[]')
    goals = Array.isArray(parsed) ? parsed : []
  } catch { goals = [] }
  return (
    <Link to={`/training/sessions/${encodeURIComponent(schedule.id)}`} className={`plan-row is-${schedule.status || 'planned'}`}>
      <span className="plan-date"><b>{schedule.date}</b><small>{schedule.start_time || '时间未定'}</small></span>
      <span className="plan-opponent"><b>{teamName}</b><small>{schedule.session || '训练组未定'}</small></span>
      <span>{schedule.format || '赛制未定'}</span>
      <span className={`board-tag tone-${schedule.status === 'completed' ? 'own' : schedule.status === 'cancelled' ? 'muted' : 'accent'}`}>{STATUS_LABEL[schedule.status || 'planned'] || schedule.status}</span>
      <span className="plan-goals">{goals.length} 目标 · {schedule.review_status === 'done' ? '已复盘' : '待复盘'}</span>
      <span className="plan-go">→</span>
    </Link>
  )
}
