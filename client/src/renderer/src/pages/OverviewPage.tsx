import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useOverview } from '../lib/hooks'
import { dateRange, duration as fmtDuration, number, percent, signed, scoreText, resultLabel, resultTone, shortDate } from '../lib/format'
import type { Overview, ProcessMatch } from '../lib/types'
import { useAppMeta } from '../lib/meta-context'
import { EconomyChart } from '../components/EconomyChart'
import { MatchRow } from '../components/MatchRow'
import { ErrorState, Ledger, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

function averageCurve(process: Overview['process']): { points: [number, number][]; games: number; note: string } {
  const games = (process.matches || []).filter((game: ProcessMatch) => (game.points || []).length)
  if (!games.length) return { points: [], games: 0, note: '还没有可用的经济时间轴' }
  const buckets = new Map<number, { sum: number; count: number }>()
  for (const game of games) {
    for (const [time, value] of game.points || []) {
      if (!Number.isFinite(time) || !Number.isFinite(value)) continue
      const key = Math.round(time / 30) * 30
      const cell = buckets.get(key) || { sum: 0, count: 0 }
      cell.sum += value
      cell.count += 1
      buckets.set(key, cell)
    }
  }
  const grid = [...buckets.entries()].sort((a, b) => a[0] - b[0])
  const enough = Math.max(3, Math.round(games.length * 0.45))
  let last = grid.length - 1
  while (last >= 0 && grid[last][1].count < enough) last -= 1
  const points = last >= 1
    ? grid.slice(0, last + 1).map(([time, cell]) => [time, Math.round(cell.sum / cell.count)] as [number, number])
    : (games[0].points || []) as [number, number][]
  return {
    points,
    games: games.length,
    note: `近 ${games.length} 局平均 · 每 30 秒一个点 · 截到 ${fmtDuration(points[points.length - 1]?.[0] || 0)}（更长的局样本不足）`
  }
}

export function OverviewPage() {
  const { baseUrl } = useConnection()
  const { teamName } = useAppMeta()
  const query = useOverview(baseUrl)

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !query.data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const { summary, team, matches, process } = query.data
  const decided = summary.decided || 0
  const wins = summary.wins || 0
  const losses = Math.max(0, decided - wins)
  const record = decided >= 3
    ? `${number(decided)} 局 ${number(wins)} 胜 ${number(losses)} 负`
    : decided
      ? `${number(summary.matches)} 局 ${number(wins)} 胜${losses ? ` ${number(losses)} 负` : ''}`
      : `${number(summary.matches)} 局记录`
  const margin = team.avgGoldDiff === null || team.avgGoldDiff === undefined
    ? ''
    : `场均${team.avgGoldDiff >= 0 ? '领先' : '落后'} ${number(Math.abs(team.avgGoldDiff))} 金`
  const dates = matches.map((match) => match.date).filter(Boolean)
  const range = dateRange(dates)
  const latest = matches[0]
  const curve = averageCurve(process)
  const topHeroes = (summary.topHeroes || []).slice(0, 6)
  const latestMeta = latest ? [latest.date, latest.session || latest.mode, fmtDuration(latest.duration)].filter(Boolean) : []
  const durations = matches.map((match) => match.duration).filter((value): value is number => Number.isFinite(value) && (value || 0) > 0)
  const avgDuration = durations.length ? durations.reduce((sum, value) => sum + value, 0) / durations.length : null
  const [latestHome, latestAway] = scoreText(latest?.scores, latest?.ownCamp).split(' : ')

  return (
    <div className="page">
      <PageHeader
        eyebrow={`OVERVIEW · ${range}`}
        title={<>{record}{margin ? <em>{margin}</em> : null}</>}
        subtitle={`${range} · ${number(summary.matches)} 局 · 营地终局面板 + 回放时间轴`}
        meta={[
          `${number(summary.matches)} 局`,
          `${number(decided)} 局有胜负`,
          `${number(summary.coverage.timelineMatches)} 局有时间轴`,
          `${number(curve.games)} 局纳入曲线`
        ].map((text) => <span key={text}>{text}</span>)}
        actions={<><button type="button" className="btn" onClick={() => window.print()}><Icon name="printer" />打印</button><Link className="btn" to="/matches">全部比赛 <Icon name="arrow" /></Link></>}
      />

      <div className="overview-grid">
        <div className="overview-lead">
          {latest ? (
            <article className="ink-card latest-card">
              <div className="latest-top">
                <span className="ink-kicker">最近对局</span>
                <span className="ink-meta">{latestMeta.join(' / ')}</span>
              </div>
              <div className="latest-body">
                <div className="latest-side">
                  <small>本队</small>
                  <b>{teamName}</b>
                  <span>{latest.ownCamp === 'red' || latest.ownCamp === 'right' ? '红方' : '蓝方'}</span>
                </div>
                <div className="latest-score">
                  <b>{latestHome || '—'}<span>:</span>{latestAway || '—'}</b>
                  <small className={resultTone(latest.result) === 'loss' ? 'is-loss' : ''}>{resultLabel(latest.result)}</small>
                </div>
                <div className="latest-side is-away">
                  <small>对手</small>
                  <b>{latest.opponent || '未标注'}</b>
                  <span>对方战队</span>
                </div>
              </div>
              <div className="latest-bottom">
                <div className="latest-lineup">
                  <span>本队阵容</span>
                  {(latest.heroes || []).slice(0, 5).map((hero) => (
                    <span className="hero-slot" key={hero}><Portrait name={hero} /><small>{hero}</small></span>
                  ))}
                </div>
                <Link className="latest-link" to={`/matches/${encodeURIComponent(latest.key)}`}>打开复盘 <Icon name="arrow" /></Link>
              </div>
            </article>
          ) : (
            <article className="ink-card latest-card">
              <div className="latest-top"><span className="ink-kicker">最近对局</span></div>
              <div className="empty-state" style={{ color: 'var(--ink-muted)' }}><b style={{ color: 'var(--ink-text)' }}>还没有对局</b><p>工作台导入第一场对局后，这里会显示最近一局。</p></div>
            </article>
          )}

          <Ledger items={[
            { label: '对局总数', value: <>{number(summary.matches)}<small>局</small></>, note: `${number(summary.coverage.timelineMatches)} 局时间轴完整` },
            { label: '有胜负胜率', value: percent(summary.winRate), note: `${number(wins)} 胜 / ${number(decided)} 局` },
            { label: '平均时长', value: fmtDuration(avgDuration), note: '按有时长的对局' },
            { label: '场均经济差', value: signed(team.avgGoldDiff), note: '本队减对手' }
          ]} />
        </div>

        <div className="overview-side">
          {topHeroes[0] ? (
            <article className="ink-card hero-watch">
              <span className="hero-watch-glyph" aria-hidden="true">{topHeroes[0].hero.slice(0, 1)}</span>
              <div className="hero-watch-head"><span className="ink-kicker">英雄观察</span><span><Icon name="arrow" /></span></div>
              <div className="hero-watch-body">
                <small>本队出场最多</small>
                <h2>{topHeroes[0].hero}</h2>
                <div className="hero-watch-stats">
                  <span><b>{number(topHeroes[0].picks)}</b>次出场</span>
                  <span><b>{percent(topHeroes[0].winRate)}</b>胜率 / {number(topHeroes[0].decided)} 局</span>
                </div>
              </div>
            </article>
          ) : (
            <article className="ink-card hero-watch is-empty"><div className="hero-watch-body"><small>英雄观察</small><h2>暂无数据</h2></div></article>
          )}

          <section className="card">
            <div className="card-head"><div><h2 className="card-title">读法</h2><div className="card-sub">先看最近一局，再看这批的走势；每个数字都能回到具体比赛。</div></div></div>
            <div className="overview-note">
              <div className="overview-note-row"><b>01</b><span>最近一局</span><small>比分、阵容与复盘入口</small></div>
              <div className="overview-note-row"><b>02</b><span>经济走势</span><small>近 {number(curve.games)} 局平均，样本不足会截断</small></div>
              <div className="overview-note-row"><b>03</b><span>逐局对照</span><small>点进任意一局看时间线与对位</small></div>
            </div>
          </section>
        </div>
      </div>

      <div className="overview-analysis">
        <section className="card">
          <div className="card-head">
            <div><h2 className="card-title">经济走势</h2><div className="card-sub">{curve.note}</div></div>
            <Link className="card-link" to="/matches">逐局查看 <Icon name="arrow" /></Link>
          </div>
          <EconomyChart points={curve.points} label="本队经济差" note={`${curve.games} 局平均 · ${curve.points.length} 个时间点`} />
        </section>

        <section className="card">
          <div className="card-head"><div><h2 className="card-title">英雄出场</h2><div className="card-sub">本队当前样本</div></div><Link className="card-link" to="/heroes">全部英雄 <Icon name="arrow" /></Link></div>
          <div className="bar-list">
            {topHeroes.length ? topHeroes.map((hero) => (
              <div className="bar-row" key={hero.hero}>
                <span><Portrait name={hero.hero} size="sm" /> {hero.hero}</span>
                <div className="meter"><i style={{ width: `${Math.max(0, Math.min(100, hero.winRate || 0))}%` }} /></div>
                <b>{number(hero.picks)} 场 · {percent(hero.winRate)}</b>
              </div>
            )) : <div className="empty-state"><b>暂无英雄数据</b><p>当前范围里还没有本队英雄记录。</p></div>}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head"><div><h2 className="card-title">最近比赛</h2><div className="card-sub">比分、阵容与复盘详情</div></div><Link className="card-link" to="/matches">全部比赛 <Icon name="arrow" /></Link></div>
        <div className="match-ledger">
          {matches.slice(0, 6).map((match) => <MatchRow key={match.key} match={match} />)}
          {!matches.length ? <div className="empty-state"><b>还没有比赛</b><p>工作台导入数据后，这里会自动出现。</p></div> : null}
        </div>
      </section>

      <div className="overview-foot">
        <span>SOURCE · 营地终局面板 / 回放时间轴 / 表格导入</span>
        <span>数据只留在本机 · {shortDate(latest?.date) || '—'}</span>
      </div>
    </div>
  )
}
