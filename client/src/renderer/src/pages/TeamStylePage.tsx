import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useTeams } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { teamPath } from '../lib/routes'
import { axisTone, mean, teamAxes, teamScore, teamTier, type TeamAxis } from '../lib/analysis/teams'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid, TierBadge } from '../components/analysis/BoardBits'
import { ScatterChart } from '../components/charts/ScatterChart'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import type { StudioTeam } from '../lib/types'

const AXIS_KEYS = ['pace', 'fight', 'macro', 'late'] as const

export function TeamStylePage() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'pace' | 'fight' | 'macro' | 'late' | 'recent' | 'name'>('pace')
  const data = query.data

  const rows = useMemo(() => {
    if (!data) return []
    const keyword = search.trim().toLowerCase()
    return data.teams
      .filter((team) => !keyword || `${team.displayName} ${team.name}`.toLowerCase().includes(keyword))
      .map((team) => ({ team, axes: teamAxes(team.percentiles) }))
      .sort((a, b) => {
        if (sort === 'name') return a.team.displayName.localeCompare(b.team.displayName)
        if (sort === 'recent') return String(b.team.lastSeen || '').localeCompare(String(a.team.lastSeen || ''))
        return (b.axes.find((axis) => axis.key === sort)?.value || 0) - (a.axes.find((axis) => axis.key === sort)?.value || 0)
      })
  }, [data, search, sort])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const allAxes = data.teams.map((team) => teamAxes(team.percentiles))
  const averages = AXIS_KEYS.map((key) => ({
    key,
    label: allAxes[0]?.find((axis) => axis.key === key)?.label || key,
    value: mean(allAxes.map((axes) => axes.find((axis) => axis.key === key)?.value).filter((value): value is number => typeof value === 'number'))
  }))
  const fast = allAxes.filter((axes) => (axes.find((axis) => axis.key === 'pace')?.value || 0) >= 65).length
  const fight = allAxes.filter((axes) => (axes.find((axis) => axis.key === 'fight')?.value || 0) >= 65).length
  const lowSample = data.teams.filter((team) => team.matches < 3).length
  const avgDuration = mean(data.teams.map((team) => team.metrics.duration).filter((value): value is number => typeof value === 'number'))

  const scatter = rows.map(({ team, axes }) => ({
    x: axes.find((axis) => axis.key === 'pace')?.value ?? null,
    y: axes.find((axis) => axis.key === 'fight')?.value ?? null,
    label: team.displayName,
    tone: (team.matches || 0) < 3 ? 'muted' as const : 'accent' as const,
    note: `运营 ${Math.round(axes.find((axis) => axis.key === 'macro')?.value || 0)} · 后期 ${Math.round(axes.find((axis) => axis.key === 'late')?.value || 0)} · ${team.matches} 局`
  }))

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TEAM STYLE"
        title="战队风格"
        subtitle="同池分位读节奏、团战、运营与后期 · 营地终局面板口径。"
        actions={<Link className="btn" to="/teams">战队档案</Link>}
      />

      <StatGrid items={[
        { label: '战队数', value: number(data.teams.length), note: `${data.summary.named} 支持已命名` },
        { label: '平均时长', value: avgDuration === null ? '—' : `${Math.round(avgDuration / 60)} 分`, note: '对手样本均值' },
        { label: '快攻型', value: number(fast), note: '节奏分位 ≥ 65' },
        { label: '团战型', value: number(fight), note: '团战分位 ≥ 65' },
        { label: '样本不足', value: number(lowSample), note: '少于 3 局，只作观察' }
      ]} />

      {lowSample === data.teams.length ? <div className="board-banner">当前 {data.teams.length} 支对手都少于 3 局，四轴只作观察；继续积累交手后再看强弱。</div> : null}

      <AnalysisSection title="风格分布" note="四轴取同池分位均值；强项 ≥65、弱项 ≤35。">
        <div className="style-axis-summary">
          {averages.map((axis) => (
            <div className="axis-row" key={axis.key}>
              <span>{axis.label}</span>
              <i><em style={{ width: `${axis.value ?? 0}%` }} /></i>
              <b>{axis.value === null ? '—' : Math.round(axis.value)}</b>
            </div>
          ))}
        </div>
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="节奏 × 团战" note="右上快攻团战、左上慢节奏团战、右下快攻运营、左下慢节奏运营；点名字进档案。">
          <ScatterChart points={scatter} xLabel="节奏分位" yLabel="团战分位" height={280} />
        </AnalysisSection>

        <AnalysisSection title="四象限读法" note="只描述分位位置，不判断强弱。">
          <div className="quadrant-notes">
            <div><b>右上 · 快攻团战</b><span>节奏与团战都高，通常更愿意接团、推进快。</span></div>
            <div><b>左上 · 慢节奏团战</b><span>团战高、节奏低，偏向等关键资源和团战窗口。</span></div>
            <div><b>右下 · 快攻运营</b><span>节奏高、团战低，更依赖兵线与资源转换。</span></div>
            <div><b>左下 · 慢节奏运营</b><span>两项都低，样本常少，需结合具体对局看。</span></div>
          </div>
        </AnalysisSection>
      </div>

      <div className="board-toolbar">
        <input className="board-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索战队" aria-label="搜索战队" />
        <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} aria-label="排序">
          <option value="pace">按节奏</option>
          <option value="fight">按团战</option>
          <option value="macro">按运营</option>
          <option value="late">按后期</option>
          <option value="recent">按最近交手</option>
          <option value="name">按队名</option>
        </select>
      </div>

      <AnalysisSection title={`战队风格榜 · ${rows.length} 支`} note="每张卡四轴分数与强弱标签；样本不足会标注。">
        {rows.length ? (
          <div className="style-team-grid">
            {rows.map(({ team, axes }) => <StyleCard team={team} axes={axes} key={team.id} />)}
          </div>
        ) : <BoardEmpty title="没有符合搜索的战队" />}
      </AnalysisSection>

      <div className="board-foot">风格轴由同池分位合成：节奏 = 分均击杀 + 短时长；团战 = 助攻 + 击杀 + 控制；运营 = 分均经济 + 推塔 + 少死；后期 = 场均时长。本页使用全部营地样本。</div>
    </div>
  )
}

function StyleCard({ team, axes }: { team: StudioTeam; axes: TeamAxis[] }) {
  const score = teamScore(team.percentiles)
  return (
    <Link to={teamPath(team.id)} className="style-team-card">
      <div className="style-team-head">
        <b>{team.displayName}</b>
        <TierBadge tier={teamTier(score)} />
      </div>
      <div className="style-team-meta">
        <span>{team.matches} 局</span>
        <span>{percent(team.winRate)}</span>
        <span>{team.lastSeen || '—'}</span>
      </div>
      {axes.map((axis) => (
        <div className={`axis-row axis-tone-${axisTone(axis.value)}`} key={axis.key}>
          <span>{axis.label}</span>
          <i><em style={{ width: `${axis.value ?? 0}%` }} /></i>
          <b>{axis.value === null ? '—' : Math.round(axis.value)}</b>
        </div>
      ))}
      {team.matches < 3 ? <span className="board-tag tone-muted">样本不足</span> : null}
    </Link>
  )
}
