import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useMatches, useTempo } from '../lib/hooks'
import { duration as fmtDuration, number, percent, signed } from '../lib/format'
import { matchPath } from '../lib/routes'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { Sparkline } from '../components/charts/Sparkline'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import type { MatchSummary, TempoMatch } from '../lib/types'

export function FeaturedPage() {
  const { baseUrl } = useConnection()
  const matchesQuery = useMatches(baseUrl)
  const tempoQuery = useTempo(baseUrl)

  const matches = matchesQuery.data || []
  const byKey = useMemo(() => new Map(matches.map((match) => [match.key, match])), [matches])
  const index = useMemo(() => {
    const ordered = [...matches].sort((a, b) => String(a.date).localeCompare(String(b.date)))
    return new Map(ordered.map((match, position) => [match.key, position + 1]))
  }, [matches])
  const games = useMemo(() => (tempoQuery.data?.process.matches || [])
    .filter((game) => byKey.has(game.key) && Array.isArray(game.points) && game.points.length >= 2), [tempoQuery.data, byKey])

  if (matchesQuery.isLoading || tempoQuery.isLoading) return <SkeletonPage cards={2} />
  if (matchesQuery.isError || tempoQuery.isError) {
    return <div className="page"><ErrorState error={matchesQuery.error || tempoQuery.error} onRetry={() => { void matchesQuery.refetch(); void tempoQuery.refetch() }} /></div>
  }

  const avgAbs = games.length
    ? games.reduce((sum, game) => sum + Math.abs(game.finalDiff || 0), 0) / games.length
    : 6000
  const valueOf = (game: TempoMatch) => (game.signFlips || 0) * 1.6
    + (typeof game.diffAt?.['600'] === 'number' && (game.diffAt['600'] as number) < 0 && byKey.get(game.key)?.result === 'win' ? 2.4 : 0)
    + Math.max(0, 1 - Math.abs(game.finalDiff || 0) / Math.max(2000, avgAbs * 1.6)) * 1.4
    + Math.min(1, Math.abs(game.finalDiff || 0) / 12000) * 0.8
    + Math.min(1, (game.duration || 0) / 1200) * 0.5
  const picked: { game: TempoMatch; reason: string }[] = []
  const taken = new Set<string>()
  const push = (game: TempoMatch | undefined, reason: string) => {
    if (!game || taken.has(game.key) || picked.length >= 4) return
    taken.add(game.key)
    picked.push({ game, reason })
  }
  const pickBy = (list: TempoMatch[], reason: (game: TempoMatch) => string) => {
    const game = list.find((item) => !taken.has(item.key))
    if (game && picked.length < 4) push(game, reason(game))
  }
  const rankOf = (get: (game: TempoMatch) => number, dir: 'max' | 'min', target: TempoMatch) =>
    1 + games.filter((game) => dir === 'max' ? get(game) > get(target) : get(game) < get(target)).length
  const nth = (rank: number, best: string, rest: string) => rank === 1 ? best : `第 ${rank} ${rest}`
  const total = games.length

  pickBy([...games].sort((a, b) => (b.signFlips || 0) - (a.signFlips || 0)),
    (game) => `经济差正负切换 ${number(game.signFlips || 0)} 次，${total} 局里${nth(rankOf((item) => item.signFlips || 0, 'max', game), '最多', '多')}`)
  pickBy([...games].sort((a, b) => Math.abs(a.finalDiff || 0) - Math.abs(b.finalDiff || 0)),
    (game) => `终局只差 ${signed(game.finalDiff)}，${total} 局里${nth(rankOf((item) => -Math.abs(item.finalDiff || 0), 'max', game), '最接近', '接近')}`)
  pickBy(games.filter((game) => typeof game.diffAt?.['600'] === 'number' && (game.diffAt['600'] as number) < 0 && byKey.get(game.key)?.result === 'win')
    .sort((a, b) => (a.diffAt?.['600'] as number) - (b.diffAt?.['600'] as number)),
    (game) => `10 分钟落后 ${signed(-(game.diffAt?.['600'] as number))}，最后翻了回来`)
  pickBy([...games].sort((a, b) => Math.abs(b.finalDiff || 0) - Math.abs(a.finalDiff || 0)),
    (game) => `终局经济差 ${signed(game.finalDiff)}，${total} 局里${nth(rankOf((item) => Math.abs(item.finalDiff || 0), 'max', game), '最悬殊', '大')}`)
  pickBy([...games].sort((a, b) => (b.duration || 0) - (a.duration || 0)),
    (game) => `打了 ${fmtDuration(game.duration)}，${total} 局里${nth(rankOf((item) => item.duration || 0, 'max', game), '最长', '长')}`)
  for (const game of [...games].sort((a, b) => valueOf(b) - valueOf(a))) push(game, '时间轴完整，可作为同类局的对照')

  const best = picked[0]
  const winCount = games.filter((game) => byKey.get(game.key)?.result === 'win').length
  const avgFlips = games.length ? games.reduce((sum, game) => sum + (game.signFlips || 0), 0) / games.length : null
  const avgFinal = games.length ? games.reduce((sum, game) => sum + (game.finalDiff || 0), 0) / games.length : null

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="FEATURED MATCHES"
        title="精选对局"
        subtitle="按复盘价值排一遍，先看最值得回看的那几局。"
        actions={<Link className="btn" to="/matches">对局档案</Link>}
      />

      <StatGrid items={[
        { label: '有完整时间轴', value: number(games.length), note: `全部 ${matches.length} 局` },
        { label: '其中最值得回看', value: best ? `第 ${index.get(best.game.key) || '—'} 局` : '—', note: best?.reason || '没有可用时间轴', tone: 'accent' },
        { label: '平均终局金差', value: signed(avgFinal), note: '本队减对手' },
        { label: '平均正负切换', value: avgFlips === null ? '—' : number(avgFlips, 1), note: '经济差穿越零线次数' },
        { label: '时间轴内胜场', value: `${winCount} / ${games.length}`, note: '仅统计有曲线的局' }
      ]} />

      <div className="featured-grid">
        {picked.length ? picked.map(({ game, reason }, position) => {
          const match = byKey.get(game.key)
          if (!match) return null
          const points = (game.points || []) as [number, number][]
          return (
            <article className={`featured-card tone-${match.result === 'win' ? 'own' : match.result === 'loss' ? 'foe' : 'muted'}`} key={game.key}>
              <div className="featured-head">
                <span className="featured-rank">{String(position + 1).padStart(2, '0')}</span>
                <span className="featured-meta">第 {index.get(match.key)} 局 · {match.date} · {match.opponent ? `对阵 ${match.opponent}` : '对手未标注'}</span>
                <span className={`board-tag tone-${match.result === 'win' ? 'own' : 'foe'}`}>{match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '—'}</span>
              </div>
              <h2>{reason}</h2>
              <p>{fmtDuration(game.duration)} 结束 · 10 分钟经济差 {signed(game.diffAt?.['600'])} · 终局 {signed(game.finalDiff)}</p>
              <Sparkline points={points} duration={game.duration} markAt={600} width={560} height={120} />
              <div className="featured-foot">
                <span>正负切换 {number(game.signFlips || 0)} 次 · 采样覆盖 {percent(game.coverage)}</span>
                <Link to={matchPath(match.key)}>查看复盘 →</Link>
              </div>
            </article>
          )
        }) : (
          <BoardEmpty title="当前范围没有可用的经济时间轴">
            精选对局需要至少两个经济采样点；先在单局详情确认时间轴，或到工作台补齐营地经济采样。
          </BoardEmpty>
        )}
      </div>

      <AnalysisSection title="为什么是这几局" note="按复盘价值排序：正负切换、落后翻盘、终局胶着、领先被缩、时长与时间轴完整度。">
        <div className="featured-method">
          <span><b>01</b> 正负切换最多：看经济差反复的原因</span>
          <span><b>02</b> 终局最接近：看最后一波决策</span>
          <span><b>03</b> 10 分钟落后但赢下：看翻盘窗口</span>
          <span><b>04</b> 终局差距最悬殊：看体系或对位崩点</span>
        </div>
      </AnalysisSection>

      <div className="board-foot">只从有经济时间轴的局里挑选；没有时间轴的局不会用终局读数硬编故事。</div>
    </div>
  )
}
