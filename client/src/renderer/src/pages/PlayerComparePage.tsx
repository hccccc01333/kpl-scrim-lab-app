import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { usePlayersBoard } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { playerPath } from '../lib/routes'
import {
  COMPARE_METRICS,
  PERCENT_METRICS,
  heroPool,
  metricText,
  playerPercent,
  playerValue,
  scoreTier,
  sharedGames,
  sideName,
  stability
} from '../lib/analysis/players'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, MiniLine, PercentBar, StatGrid, TierBadge } from '../components/analysis/BoardBits'
import { PercentileRadar } from '../components/charts/PercentileRadar'
import { VersusBars } from '../components/charts/VersusBars'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import type { BoardPlayer } from '../lib/types'

export function PlayerComparePage() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  const [searchParams] = useSearchParams()
  const [aName, setAName] = useState(searchParams.get('a') || '')
  const [bName, setBName] = useState(searchParams.get('b') || '')
  const [side, setSide] = useState<'own' | 'enemy'>('own')
  const board = query.data

  const candidates = useMemo(() => {
    if (!board) return []
    return board.players
      .filter((player) => player.side === side && player.games >= 1)
      .sort((a, b) => (b.score || 0) - (a.score || 0))
  }, [board, side])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !board) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const preferred = candidates.filter((player) => player.games >= 2)
  const pool = preferred.length >= 2 ? preferred : candidates
  const fallback = pool[0]?.name || ''
  const fallbackB = pool[1]?.name || fallback
  const a = board.players.find((player) => player.name === (aName || fallback))
  const b = board.players.find((player) => player.name === (bName || fallbackB))
  if (!a || !b) {
    return (
      <div className="page">
        <PageHeader eyebrow="PLAYER COMPARE" title="选手对比" actions={<Link className="btn" to="/players/archive">选手档案</Link>} />
        <BoardEmpty title="还没有可对比的选手">先在档案页积累两局以上样本。</BoardEmpty>
      </div>
    )
  }

  const leads = COMPARE_METRICS.map((metric) => {
    const av = playerValue(a, metric.key)
    const bv = playerValue(b, metric.key)
    return { metric, a: av, b: bv, diff: av !== null && bv !== null ? av - bv : null }
  })
  const aLeads = leads.filter((row) => row.diff !== null && row.diff > 0).length
  const bLeads = leads.filter((row) => row.diff !== null && row.diff < 0).length
  const biggest = [...leads].filter((row) => row.diff !== null).sort((x, y) => Math.abs((y.diff || 0)) - Math.abs((x.diff || 0)))[0]
  const shared = sharedGames(board, a.name, b.name)
  const poolA = new Map(heroPool(a).map((row) => [row.hero, row.games]))
  const poolB = new Map(heroPool(b).map((row) => [row.hero, row.games]))
  const poolKeys = [...new Set([...poolA.keys(), ...poolB.keys()])].sort((x, y) => (poolB.get(y) || 0) - (poolB.get(x) || 0))
  const stabilityA = stability(a)
  const stabilityB = stability(b)
  const diffRows = PERCENT_METRICS.map((metric) => ({
    label: metric.label,
    a: playerPercent(a, metric.key),
    b: playerPercent(b, metric.key)
  })).sort((x, y) => Math.abs((y.a || 0) - (y.b || 0)) - Math.abs((x.a || 0) - (x.b || 0)))

  const swap = () => { setAName(b.name); setBName(a.name) }
  const setSideAndReset = (next: 'own' | 'enemy') => {
    setSide(next)
    setAName('')
    setBName('')
  }

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="PLAYER COMPARE"
        title="选手对比"
        subtitle="谁更强、强在哪、能不能互换。原始值并列，分位只在各自分路内计算。"
        actions={<Link className="btn" to="/players/lanes">选手与位置</Link>}
      />

      <div className="board-toolbar">
        <div className="segmented">
          <button type="button" className={side === 'own' ? 'is-active' : ''} onClick={() => setSideAndReset('own')}>本队</button>
          <button type="button" className={side === 'enemy' ? 'is-active' : ''} onClick={() => setSideAndReset('enemy')}>对手</button>
        </div>
        <select value={a.name} onChange={(event) => setAName(event.target.value)} aria-label="选手 A">
          {candidates.map((player) => <option value={player.name} key={player.name}>{player.name} · {player.lane}</option>)}
        </select>
        <select value={b.name} onChange={(event) => setBName(event.target.value)} aria-label="选手 B">
          {candidates.map((player) => <option value={player.name} key={player.name}>{player.name} · {player.lane}</option>)}
        </select>
        <button type="button" className="btn btn-sm" onClick={swap}>交换</button>
      </div>

      <div className="compare-head">
        <PlayerIdentity player={a} />
        <div className="compare-score">
          <span><b>{aLeads}</b><small>项领先</small></span>
          <i>:</i>
          <span><b>{bLeads}</b><small>项领先</small></span>
          <p>{biggest ? `最大差距：${biggest.metric.label}（${metricText(a, biggest.metric)} vs ${metricText(b, biggest.metric)}）` : '样本不足，暂不做差距结论。'}</p>
        </div>
        <PlayerIdentity player={b} align="right" />
      </div>

      <AnalysisSection title="指标对位" note="八项原始值并列；分均数据来自营地十人面板。">
        <VersusBars
          rows={COMPARE_METRICS.map((metric) => ({
            label: metric.label,
            own: playerValue(a, metric.key),
            foe: playerValue(b, metric.key),
            digits: metric.digits,
            suffix: metric.suffix
          }))}
          ownTitle={a.name}
          foeTitle={b.name}
        />
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="分位雷达" note="各自分路内的同池分位；形状差异比原始值更能说明风格。">
          <div className="pct-radar-wrap">
            <PercentileRadar
              axes={PERCENT_METRICS.slice(0, 6).map((metric) => metric.label)}
              series={[
                { label: a.name, tone: 'own', values: PERCENT_METRICS.slice(0, 6).map((metric) => playerPercent(a, metric.key)) },
                { label: b.name, tone: 'foe', values: PERCENT_METRICS.slice(0, 6).map((metric) => playerPercent(b, metric.key)) }
              ]}
              size={220}
            />
            <div className="pct-list">
              {diffRows.map((row) => (
                <div className="pct-row" key={row.label}>
                  <span>{row.label}</span>
                  <PercentBar value={row.a} />
                  <b className="is-foe">{row.b === null ? '—' : `${Math.round(row.b)}%`}</b>
                </div>
              ))}
            </div>
          </div>
        </AnalysisSection>

        <AnalysisSection title="英雄池" note="仅 A / 共用 / 仅 B；集中度 = 该英雄局数 / 本人总出场。">
          {poolKeys.length ? (
            <div className="hero-diff">
              {poolKeys.slice(0, 10).map((hero) => {
                const av = poolA.get(hero) || 0
                const bv = poolB.get(hero) || 0
                return (
                  <div className="hero-diff-row" key={hero}>
                    <b className={av ? 'is-own' : ''}>{av || '—'}</b>
                    <Link to={`/heroes/${encodeURIComponent(hero)}`}>{hero}</Link>
                    <b className={bv ? 'is-foe' : ''}>{bv || '—'}</b>
                  </div>
                )
              })}
            </div>
          ) : <BoardEmpty title="两人都没有英雄记录" />}
        </AnalysisSection>
      </div>

      <AnalysisSection title="同场记录" note={`同队 ${shared.sameTeam} 局 · 对位 ${shared.versus} 局；A 在同队局 ${shared.sameTeamWins} 胜，对位 ${shared.aWins} 胜。`}>
        {shared.rows.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>日期</th><th>对手</th><th>关系</th><th>结果</th><th>对局</th></tr></thead>
              <tbody>
                {shared.rows.map((row) => (
                  <tr key={row.game.id}>
                    <td>{row.game.day}</td>
                    <td>{row.game.opponent || '—'}</td>
                    <td>{row.mode === 'team' ? '同队' : '对位'}</td>
                    <td>{row.aWin ? `${a.name} 胜` : `${a.name} 负`}</td>
                    <td><Link className="text-link" to={`/matches/${encodeURIComponent(row.game.match)}`}>查看</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="两人还没有同场记录" />}
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="逐局评分" note="最近至多 12 局；曲线只示意波动，不插值。">
          <CompareTrend player={a} />
          <CompareTrend player={b} />
        </AnalysisSection>

        <AnalysisSection title="稳定性" note="评分均值、波动与区间；样本不足 2 局不给标准差。">
          <div className="stability-grid">
            {[{ player: a, stats: stabilityA }, { player: b, stats: stabilityB }].map(({ player, stats }) => (
              <div className="stability-card" key={player.name}>
                <b>{player.name}</b>
                <span><small>均值</small>{number(stats.mean, 2)}</span>
                <span><small>中位</small>{number(stats.median, 2)}</span>
                <span><small>标准差</small>{number(stats.sd, 2)}</span>
                <span><small>区间</small>{stats.min === null ? '—' : `${number(stats.min, 1)} – ${number(stats.max, 1)}`}</span>
              </div>
            ))}
          </div>
        </AnalysisSection>
      </div>

      <div className="board-foot">对比只做并列与描述，不推断因果；分位与表现分来自各自分路的同池样本。</div>
    </div>
  )
}

function PlayerIdentity({ player, align = 'left' }: { player: BoardPlayer; align?: 'left' | 'right' }) {
  return (
    <Link to={playerPath(player.name)} className={`compare-identity${align === 'right' ? ' is-right' : ''}`}>
      <Portrait name={player.name} size="lg" />
      <span><b>{player.name}</b><small>{player.lane} · {sideName(player.side)} · {player.games} 局</small></span>
      <span className="compare-score-value"><strong>{number(player.score, 1)}</strong><TierBadge tier={scoreTier(player.score)} /></span>
    </Link>
  )
}

function CompareTrend({ player }: { player: BoardPlayer }) {
  const values = (player.recent || []).slice(0, 12).reverse().map((game, index) => ({ x: index, y: game.rating ?? null }))
  return (
    <div className="compare-trend">
      <div className="compare-trend-head"><b>{player.name}</b><span>最近 {values.length} 局评分</span></div>
      <MiniLine values={values} width={480} height={116} label={`${player.name} 逐局评分`} />
    </div>
  )
}
