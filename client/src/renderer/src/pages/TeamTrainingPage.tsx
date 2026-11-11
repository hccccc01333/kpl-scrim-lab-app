import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useTeamTraining } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { teamPath } from '../lib/routes'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'

export function TeamTrainingPage() {
  const { baseUrl } = useConnection()
  const query = useTeamTraining(baseUrl)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState('')
  const data = query.data

  const teams = useMemo(() => {
    if (!data) return []
    const keyword = search.trim().toLowerCase()
    return [...data.teams]
      .filter((team) => !keyword || `${team.displayName} ${team.name}`.toLowerCase().includes(keyword))
      .sort((a, b) => b.sessionCount - a.sessionCount || String(b.lastSession || '').localeCompare(String(a.lastSession || '')))
  }, [data, search])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const current = teams.find((team) => team.id === selected) || teams[0]
  const sessions = current ? [...current.sessions].sort((a, b) => `${b.date} ${b.time || ''}`.localeCompare(`${a.date} ${a.time || ''}`)) : []
  const summary = data.summary

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TEAM TRAINING"
        title="战队训练"
        subtitle="按对手汇总训练课与交手日 · 计划来自训练计划，交手日自动归集。"
        actions={<Link className="btn" to="/teams">战队档案</Link>}
      />

      <StatGrid items={[
        { label: '训练课', value: number(summary.sessions), note: `${summary.withPlans} 支有训练计划` },
        { label: '训练目标', value: number(summary.goals), note: `已完成 ${summary.goalsDone}` },
        { label: '已复盘', value: number(summary.reviewed), note: '训练课复盘' },
        { label: '覆盖战队', value: number(summary.teams), note: '按对手归集' },
        { label: '未指定对手', value: number(summary.unassigned), note: '训练课待归属' }
      ]} />

      <div className="training-layout">
        <div className="training-sidebar">
          <input className="board-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索对手" aria-label="搜索对手" />
          <div className="training-team-list">
            {teams.map((team) => (
              <button
                type="button"
                key={team.id}
                className={`training-team${current?.id === team.id ? ' is-active' : ''}`}
                onClick={() => setSelected(team.id)}
              >
                <span><b>{team.displayName}</b><small>{team.lastSession || '暂无训练日'}</small></span>
                <span><b>{team.sessionCount}</b><small>训练课</small></span>
                <span><b>{percent(team.winRate)}</b><small>{team.matches} 局</small></span>
              </button>
            ))}
            {!teams.length ? <p className="board-muted">没有匹配的对手。</p> : null}
          </div>
        </div>

        <div className="training-main">
          {current ? (
            <>
              <div className="training-main-head">
                <div>
                  <Link to={teamPath(current.id)}><h2>{current.displayName}</h2></Link>
                  <p>{current.matches} 局 · {current.wins} 胜 {current.losses} 负 · 最近 {current.lastSeen || '—'}</p>
                </div>
                <div className="training-kpis">
                  <span><small>计划</small><b>{current.planCount}</b></span>
                  <span><small>目标达成</small><b>{current.goalCount ? `${current.goalsDone}/${current.goalCount}` : '—'}</b></span>
                  <span><small>已复盘</small><b>{current.reviewed}/{current.sessionCount}</b></span>
                </div>
              </div>

              <AnalysisSection title={`训练时间线 · ${sessions.length} 节`} note="计划训练课在前，营地交手日自动补在后面；只读展示。">
                {sessions.length ? (
                  <div className="session-timeline">
                    {sessions.map((session, index) => (
                      <div className={`session-card is-${session.source === 'plan' ? 'plan' : 'camp'}`} key={`${session.id || session.date}-${index}`}>
                        <div className="session-head">
                          <b>{session.date}{session.time ? ` ${session.time}` : ''}</b>
                          <span className={`board-tag tone-${session.source === 'plan' ? 'accent' : 'muted'}`}>{session.source === 'plan' ? '训练课' : '交手日'}</span>
                          <span>{session.matches} 局 · {session.wins} 胜 {session.losses} 负</span>
                          {session.duration ? <span>{Math.round(session.duration / 60)} 分</span> : null}
                        </div>
                        {session.session || session.notes ? <p className="session-note">{[session.session, session.format, session.notes].filter(Boolean).join(' · ')}</p> : null}
                        {session.goals.length ? (
                          <div className="session-goals">
                            {session.goals.map((goal, goalIndex) => (
                              <span key={goalIndex}><small>{goal.label}</small><b>{String(goal.target ?? '—')}</b><em className={`tone-${goal.status === 'done' ? 'own' : goal.status === 'partial' ? 'accent' : 'muted'}`}>{goal.status === 'done' ? '达成' : goal.status === 'partial' ? '部分' : goal.status || '未判定'}</em></span>
                            ))}
                          </div>
                        ) : null}
                        <div className="session-games">
                          {session.games.slice(0, 6).map((game) => {
                            const row = <><span>{game.start}</span><b>{game.win ? '胜' : '负'}</b><small>{game.map || ''}</small></>
                            return game.matchKey
                              ? <Link key={game.seq} to={`/matches/${encodeURIComponent(game.matchKey)}`} className={`session-game${game.win ? ' is-win' : ''}`}>{row}</Link>
                              : <span key={game.seq} className={`session-game${game.win ? ' is-win' : ''}`}>{row}</span>
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <BoardEmpty title="还没有训练记录">训练计划或营地交手日后会自动出现在这里。</BoardEmpty>}
              </AnalysisSection>
            </>
          ) : <BoardEmpty title="没有可展示的对手" />}
        </div>
      </div>

      <div className="board-foot">训练计划的编辑与训练课复盘仍在工作台完成；客户端只读汇总，不写回。本页使用全部营地与训练计划样本，不套用首页日期筛选。</div>
    </div>
  )
}
