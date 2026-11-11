import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useTeams } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { teamPath } from '../lib/routes'
import {
  axisTone,
  metricText,
  teamAxes,
  teamMetric,
  teamScore,
  teamTier,
  TEAM_METRICS
} from '../lib/analysis/teams'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid, TierBadge } from '../components/analysis/BoardBits'
import { PercentBar } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

const SORTS = [
  { key: 'score', label: '评分' },
  { key: 'lastSeen', label: '最近交手' },
  { key: 'matches', label: '交手最多' },
  { key: 'ownWinRate', label: '本队胜率' },
  { key: 'name', label: '队名' }
] as const
type SortKey = (typeof SORTS)[number]['key']

export function TeamsPage() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<'all' | 'named' | 'pending'>('all')
  const [sort, setSort] = useState<SortKey>('score')
  const data = query.data

  const rows = useMemo(() => {
    if (!data) return []
    const keyword = search.trim().toLowerCase()
    return [...data.teams]
      .filter((team) => {
        if (status === 'named' && !team.named) return false
        if (status === 'pending' && team.named) return false
        if (!keyword) return true
        return `${team.displayName} ${team.name} ${team.coach || ''}`.toLowerCase().includes(keyword)
          || (team.players || []).some((player) => player.name.toLowerCase().includes(keyword))
      })
      .sort((a, b) => {
        if (sort === 'name') return a.displayName.localeCompare(b.displayName)
        if (sort === 'lastSeen') return String(b.lastSeen || '').localeCompare(String(a.lastSeen || ''))
        if (sort === 'matches') return b.matches - a.matches
        if (sort === 'ownWinRate') {
          const aRate = a.matches ? (a.losses / a.matches) * 100 : 0
          const bRate = b.matches ? (b.losses / b.matches) * 100 : 0
          return bRate - aRate
        }
        return (teamScore(b.percentiles) || 0) - (teamScore(a.percentiles) || 0)
      })
  }, [data, search, status, sort])

  if (query.isLoading) return <SkeletonPage cards={3} />
  if (query.isError || !data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const ownScore = teamScore(data.own.percentiles)
  const allScores = data.teams.map((team) => teamScore(team.percentiles)).filter((score): score is number => score !== null)
  const avgScore = allScores.length ? allScores.reduce((sum, score) => sum + score, 0) / allScores.length : null
  const dates = data.teams.flatMap((team) => [team.firstSeen, team.lastSeen]).filter((value): value is string => Boolean(value)).sort()

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TEAMS"
        title="战队档案"
        subtitle={`${data.teams.length} 支对手 · ${data.summary.games} 局交手 · 评分与分位来自同池对手样本。`}
        actions={<>
          <Link className="btn" to="/teams/style">战队风格</Link>
          <Link className="btn" to="/teams/roster">战队阵容</Link>
        </>}
      />

      <StatGrid items={[
        { label: '识别对手', value: number(data.teams.length), note: `${data.summary.named} 支已命名 · ${data.summary.pending} 支待命名` },
        { label: '交手局数', value: number(data.summary.games), note: data.summary.unclustered ? `${data.summary.unclustered} 局未聚类` : '全部已归属' },
        { label: '本队胜率', value: percent(data.own.winRate), note: `${data.own.wins} 胜 / ${data.own.matches} 局` },
        { label: '本队评分', value: ownScore ?? '—', note: '同池权重分', tone: 'accent' },
        { label: '对手平均评分', value: avgScore === null ? '—' : Math.round(avgScore), note: `${allScores.length} 支有完整样本` },
        { label: '时间跨度', value: dates.length ? `${dates[0]} → ${dates[dates.length - 1]}` : '—', note: '首个与最近交手' }
      ]} />

      <AnalysisSection title="本队基准" note="本队不进对手榜；这里只展示同池分位与四轴，作为读对手的参照。">
        <div className="own-team-band">
          <div className="own-team-id">
            <TierBadge tier={teamTier(ownScore)} />
            <b>{data.own.name}</b>
            <span>{data.own.matches} 局 · {percent(data.own.winRate)}</span>
          </div>
          <div className="own-team-metrics">
            {TEAM_METRICS.slice(0, 5).map((metric) => (
              <span key={metric.key}><small>{metric.label}</small><b>{metricText(data.own.metrics[metric.key], metric)}</b></span>
            ))}
          </div>
          <div className="own-team-axes">
            {teamAxes(data.own.percentiles).map((axis) => (
              <div className="axis-row" key={axis.key}>
                <span>{axis.label}</span>
                <i><em style={{ width: `${axis.value ?? 0}%` }} /></i>
                <b>{axis.value === null ? '—' : Math.round(axis.value)}</b>
              </div>
            ))}
          </div>
        </div>
      </AnalysisSection>

      <div className="board-toolbar">
        <input className="board-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索队名、教练或选手" aria-label="搜索战队" />
        <div className="segmented">
          {(['all', 'named', 'pending'] as const).map((value) => (
            <button type="button" key={value} className={status === value ? 'is-active' : ''} onClick={() => setStatus(value)}>
              {value === 'all' ? '全部' : value === 'named' ? '已命名' : '待命名'}
            </button>
          ))}
        </div>
        <select value={sort} onChange={(event) => setSort(event.target.value as SortKey)} aria-label="排序">
          {SORTS.map((item) => <option value={item.key} key={item.key}>按{item.label}</option>)}
        </select>
        <span className="board-muted">{rows.length} 支</span>
      </div>

      <AnalysisSection title="对手战力榜" note="评分 = 胜率 30% + 分均经济 20% + KDA 20% + 分均输出 15% + 场均推塔 15%，按同池分位加权。">
        {rows.length ? (
          <div className="team-card-grid">
            {rows.map((team, index) => <TeamCard team={team} rank={index + 1} key={team.id} />)}
          </div>
        ) : <BoardEmpty title="没有符合筛选的战队">放宽状态或搜索条件再试。</BoardEmpty>}
      </AnalysisSection>

      <div className="board-foot">S ≥ 80 / A ≥ 60 / B ≥ 40；分位缺失项按剩余权重归一。本页使用全部营地面板及关联回放，首页的日期 / 来源筛选不适用；待命名战队可在工作台改名，客户端只读。</div>
    </div>
  )
}

function TeamCard({ team, rank }: { team: import('../lib/types').StudioTeam; rank: number }) {
  const score = teamScore(team.percentiles)
  const tier = teamTier(score)
  const axes = teamAxes(team.percentiles)
  return (
    <Link to={teamPath(team.id)} className="team-card">
      <div className="team-card-head">
        <span className="team-rank">{rank}</span>
        <span className="team-mark">{team.displayName.replace(/^待命名战队\s*/, '').slice(0, 2) || '?'}</span>
        <span className="team-name"><b>{team.displayName}</b><small>{team.named ? `教练 ${team.coach || '未录入'}` : '阵容聚类 · 待命名'}</small></span>
        <span className="team-tier"><TierBadge tier={tier} /><strong>{score ?? '—'}</strong></span>
      </div>
      <div className="team-card-meta">
        <span><small>交手</small><b>{team.matches}</b></span>
        <span><small>本队战绩</small><b>{team.losses} 胜 {team.wins} 负</b></span>
        <span><small>对手胜率</small><b>{percent(team.winRate)}</b></span>
        <span><small>最近</small><b>{team.lastSeen || '—'}</b></span>
      </div>
      <div className="team-card-axes">
        {axes.map((axis) => (
          <span key={axis.key} className={`axis-tone-${axisTone(axis.value)}`}>
            <small>{axis.label}</small><i><em style={{ width: `${axis.value ?? 0}%` }} /></i>
          </span>
        ))}
      </div>
      <div className="team-card-metrics">
        <span><small>分均经济</small><b>{number(teamMetric(team, 'gpm'))}</b></span>
        <span><small>KDA</small><b>{number(teamMetric(team, 'kda'), 2)}</b></span>
        <span><small>分均输出</small><b>{number(teamMetric(team, 'dpm'))}</b></span>
        <span><small>推塔</small><b>{number(teamMetric(team, 'towerPerGame'), 1)}</b></span>
      </div>
      <div className="team-card-roster">
        {(team.players || []).slice(0, 5).map((player) => <span key={player.id || player.name} title={player.name}>{player.name}</span>)}
      </div>
    </Link>
  )
}
