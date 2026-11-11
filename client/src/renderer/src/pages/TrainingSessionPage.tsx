import { Link, useParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useTrainingSession } from '../lib/hooks'
import { api, assetUrl } from '../lib/api'
import { pushToast } from '../lib/toast'
import { duration as fmtDuration, number, percent } from '../lib/format'
import { matchPath } from '../lib/routes'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

const GOAL_LABEL: Record<string, string> = { pending: '未评估', achieved: '达成', partial: '部分达成', missed: '未达成' }

export function TrainingSessionPage() {
  const { baseUrl } = useConnection()
  const { id = '' } = useParams()
  const query = useTrainingSession(baseUrl, id)
  const session = query.data

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !session) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const schedule = session.schedule || {}
  const matches = session.matches || []
  const goals = parseList(schedule.goals)
  const attendance = parseList(schedule.attendance)
  const players = session.players || []
  const attendanceNames = players.filter((player) => attendance.includes(player.id)).map((player) => player.name)
  const resultOf = (match: (typeof matches)[number]) => match.own_side && match.winner
    ? (match.winner === match.own_side ? 'win' : 'loss')
    : null
  const wins = matches.filter((match) => resultOf(match) === 'win').length
  const losses = matches.filter((match) => resultOf(match) === 'loss').length
  const durations = matches.map((match) => Number(match.duration)).filter((value) => Number.isFinite(value) && value > 0)
  const avgDuration = durations.length ? durations.reduce((sum, value) => sum + value, 0) / durations.length : null
  const achieved = goals.filter((goal) => goal.status === 'achieved').length
  const teamName = session.team?.name || '未指定对手'
  const brief = session.opponentBrief
  const exportImage = async () => {
    try {
      const result = await api<{ url: string }>(baseUrl, '/api/studio/workspace/reports/screenshot', { method: 'POST', body: { path: `session/${id}` }, timeout: 180_000 })
      await window.kpl.openExternal(assetUrl(baseUrl, result.url))
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '图片导出失败', 'error')
    }
  }

  return (
    <div className="page board-page session-page">
      <PageHeader
        eyebrow="TRAINING SESSION"
        title={<>{schedule.date || '日期未定'} · 对阵 {teamName}<em>{[schedule.start_time, schedule.format, schedule.session].filter(Boolean).join(' · ')}</em></>}
        actions={<>
          <Link className="btn" to="/training">训练计划</Link>
          <button type="button" className="btn" onClick={() => void exportImage()}><Icon name="copy" />导出图片</button>
          <button type="button" className="btn" onClick={() => window.print()}><Icon name="printer" />打印</button>
        </>}
      />

      <StatGrid items={[
        { label: '训练局数', value: number(matches.length), note: `${wins} 胜 ${losses} 负`, tone: 'accent' },
        { label: '场均时长', value: fmtDuration(avgDuration), note: '关联对局' },
        { label: '训练目标', value: number(goals.length), note: `${achieved} 条达成` },
        { label: '复盘', value: schedule.review_status === 'done' ? '已复盘' : '待复盘', note: schedule.review ? '有文字复盘' : '无文字复盘' },
        { label: '出勤', value: attendanceNames.length ? `${attendanceNames.length} 人` : '未记录', note: '按名单' }
      ]} />

      <div className="board-grid-2">
        <AnalysisSection title="训练目标" note="目标状态来自工作台指标层；缺数据不按 0 计算。">
          {goals.length ? (
            <div className="goal-review-list">
              {goals.map((goal, index) => (
                <div className={`goal-review is-${goal.status || 'pending'}`} key={index}>
                  <span>{GOAL_LABEL[goal.status || 'pending'] || goal.status}</span>
                  <b>{goal.label || '未命名目标'}</b>
                  {goal.target || goal.actual !== null && goal.actual !== undefined ? (
                    <small>{[goal.target ? `目标 ${goal.target}` : '', goal.actual !== null && goal.actual !== undefined ? `实际 ${goal.actual}` : ''].filter(Boolean).join(' · ')}</small>
                  ) : null}
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="本场未填写训练目标" />}
        </AnalysisSection>

        <AnalysisSection title="赛后复盘" note="只读展示；复盘编辑仍在工作台。">
          {schedule.review ? <p className="session-review">{schedule.review}</p> : <BoardEmpty title="还没有填写赛后复盘" />}
          <div className="session-meta">
            <span><small>赛制</small><b>{schedule.format || '未定'}</b></span>
            <span><small>规则</small><b>{schedule.rules || '未定'}</b></span>
            <span><small>版本</small><b>{schedule.version || '未记录'}</b></span>
            <span><small>出勤</small><b>{attendanceNames.length ? attendanceNames.join(' · ') : '未记录'}</b></span>
          </div>
        </AnalysisSection>
      </div>

      <AnalysisSection title={`关联对局 · ${matches.length} 局`} note={`关联依据：${session.matchReason || '未知'}。点对局进入单局深度。`}>
        {matches.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>日期</th><th>对手</th><th>比分</th><th>结果</th><th>时长</th><th>对局</th></tr></thead>
              <tbody>
                {matches.map((match) => (
                  <tr key={match.key}>
                    <td>{match.date || '—'}</td>
                    <td>{match.enemyName || teamName}</td>
                    <td className="is-num">{scoreOf(match.score)}</td>
                    <td><span className={`board-tag tone-${resultOf(match) === 'win' ? 'own' : resultOf(match) === 'loss' ? 'foe' : 'muted'}`}>{resultOf(match) === 'win' ? '胜' : resultOf(match) === 'loss' ? '负' : '—'}</span></td>
                    <td className="is-num">{fmtDuration(match.duration)}</td>
                    <td><Link className="text-link" to={matchPath(match.key)}>复盘 →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="本场没有关联对局">工作台可按日期、对手或训练组关联。</BoardEmpty>}
      </AnalysisSection>

      <AnalysisSection title="对手简报" note="来自对手最近交手；只读。">
        {brief ? (
          <div className="brief-grid">
            <div className="brief-head"><b>{brief.name}</b><span>{number(brief.matches)} 局 · 胜率 {percent(brief.winRate)}</span></div>
            <div><small>常用英雄</small><span className="brief-heroes">{(brief.heroes || []).map((item) => <span key={item.hero}><Portrait name={item.hero} size="sm" />{item.hero} {number(item.games)}</span>) || '—'}</span></div>
            <div><small>禁用习惯</small><span className="brief-heroes">{(brief.bans || []).map((item) => <span key={item.hero}><Portrait name={item.hero} size="sm" />{item.hero} {number(item.games)}</span>) || '—'}</span></div>
            <div><small>关键选手</small><span className="brief-players">{(brief.players || []).slice(0, 5).map((player) => <span key={player.name}>{player.lane || '位置未知'} · {player.name}</span>)}</span></div>
          </div>
        ) : <BoardEmpty title="未指定对手或没有简报" />}
      </AnalysisSection>

      <div className="board-foot">训练课编辑、出勤与复盘写回仍在工作台；客户端只读展示。</div>
    </div>
  )
}

function parseList(raw: unknown): any[] {
  try {
    const parsed = JSON.parse(String(raw || '[]'))
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function scoreOf(score: unknown): string {
  try {
    const value = typeof score === 'string' ? JSON.parse(score) : score
    if (value && typeof value === 'object') {
      const row = value as Record<string, number>
      if (row.blue !== undefined && row.red !== undefined) return `${row.blue} : ${row.red}`
      if (row.left !== undefined) return `${row.left} : ${row.right}`
    }
  } catch { /* 非 JSON 分数 */ }
  return '—'
}
