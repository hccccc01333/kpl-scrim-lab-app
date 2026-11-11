import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useMatches, useTempo } from '../lib/hooks'
import { duration as fmtDuration, number, percent, signed } from '../lib/format'
import { matchPath } from '../lib/routes'
import { goldDiffOf } from '../lib/analysis/matches'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import type { MatchSummary } from '../lib/types'

interface RecordDef {
  label: string
  get: (match: MatchSummary, flips: Map<string, number | null>) => number | null
  show: (match: MatchSummary, flips: Map<string, number | null>) => string
  dir: 'max' | 'min'
  note: string
}

export function RecordsPage() {
  const { baseUrl } = useConnection()
  const matchesQuery = useMatches(baseUrl)
  const tempoQuery = useTempo(baseUrl)
  const matches = matchesQuery.data || []

  const flips = useMemo(() => new Map((tempoQuery.data?.process.matches || []).map((game) => [game.key, typeof game.signFlips === 'number' ? game.signFlips : null])), [tempoQuery.data])
  const index = useMemo(() => {
    const ordered = [...matches].sort((a, b) => String(a.date).localeCompare(String(b.date)))
    return new Map(ordered.map((match, position) => [match.key, position + 1]))
  }, [matches])

  if (matchesQuery.isLoading) return <SkeletonPage cards={2} />
  if (matchesQuery.isError) {
    return <div className="page"><ErrorState error={matchesQuery.error} onRetry={() => void matchesQuery.refetch()} /></div>
  }

  const duration = (match: MatchSummary) => typeof match.duration === 'number' && match.duration > 0 ? match.duration : null
  const gpm = (match: MatchSummary) => {
    const gold = match.own?.gold
    const seconds = duration(match)
    return typeof gold === 'number' && seconds ? gold / (seconds / 60) : null
  }
  const records: RecordDef[] = [
    { label: '最长对局', get: duration, show: (match) => fmtDuration(match.duration), dir: 'max', note: '按营地记录时长' },
    { label: '最短对局', get: duration, show: (match) => fmtDuration(match.duration), dir: 'min', note: '按营地记录时长' },
    { label: '最大终局金差', get: (match) => goldDiffOf(match), show: (match) => signed(goldDiffOf(match)), dir: 'max', note: '本队减对手' },
    { label: '最小终局金差', get: (match) => goldDiffOf(match), show: (match) => signed(goldDiffOf(match)), dir: 'min', note: '本队减对手' },
    { label: '最高击杀', get: (match) => match.own?.kills ?? null, show: (match) => number(match.own?.kills), dir: 'max', note: '本队五人击杀合计' },
    { label: '最高 KDA', get: (match) => match.own?.kda ?? null, show: (match) => number(match.own?.kda, 1), dir: 'max', note: '(击杀 + 助攻) / 死亡' },
    { label: '经济最反复', get: (_match, map) => map.get(_match.key) ?? null, show: (_match, map) => `${number(map.get(_match.key))} 次`, dir: 'max', note: '经济差正负切换次数' },
    { label: '最高分均经济', get: (match) => gpm(match), show: (match) => number(gpm(match)), dir: 'max', note: '本队五人经济 ÷ 时长（金 / 分钟）' }
  ]
  const meanOf = (fn: (match: MatchSummary, map: Map<string, number | null>) => number | null) => {
    const values = matches.map((match) => fn(match, flips)).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
  }
  const holderOf = (record: RecordDef) => {
    const values = matches
      .map((match) => ({ match, value: record.get(match, flips) }))
      .filter((item): item is { match: MatchSummary; value: number } => typeof item.value === 'number' && Number.isFinite(item.value))
    if (!values.length) return null
    return values.sort((a, b) => record.dir === 'max' ? b.value - a.value : a.value - b.value)[0]
  }
  const avgDuration = meanOf(duration)
  const avgGold = meanOf((match) => goldDiffOf(match))
  const avgKills = meanOf((match) => match.own?.kills ?? null)
  const cards = records.map((record) => {
    const holder = holderOf(record)
    if (!holder) return null
    const avg = meanOf(record.get)
    const gap = avg && avg !== 0 ? Math.round(Math.abs((holder.value - avg) / Math.abs(avg)) * 100) : null
    return (
      <article className="record-card" key={record.label}>
        <span>{record.label}</span>
        <strong>{record.show(holder.match, flips)}</strong>
        <p>{record.note}{gap !== null ? ` · ${holder.value >= avg! ? '高' : '低'}于均值 ${gap}%` : ''}</p>
        <Link to={matchPath(holder.match.key)}>
          <span>第 {index.get(holder.match.key)} 局 · {holder.match.opponent || '对手未标注'}</span>
          <b>查看 →</b>
        </Link>
      </article>
    )
  })

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TRAINING RECORDS"
        title="训练纪录"
        subtitle="这批局的极值在哪一场，和均值差多少。"
        actions={<Link className="btn" to="/matches/versions">版本对比</Link>}
      />

      <StatGrid items={[
        { label: '对局', value: number(matches.length), note: `${matches.filter((match) => match.result === 'win').length} 胜` },
        { label: '平均时长', value: fmtDuration(avgDuration), note: '按营地记录' },
        { label: '平均终局金差', value: signed(avgGold), note: '本队减对手' },
        { label: '平均击杀', value: number(avgKills, 1), note: '本队五人和' },
        { label: '有时间轴', value: number(flips.size), note: '可计算经济反复' }
      ]} />

      {cards.some(Boolean) ? <div className="record-grid">{cards}</div> : <BoardEmpty title="当前范围没有可计算的记录" />}

      <div className="board-foot">极值只描述这批样本，不代表长期水平；分均经济与平均金差都以营地记录为准。</div>
    </div>
  )
}
