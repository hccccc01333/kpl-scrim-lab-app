import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import {
  useCampCompare,
  useCampCombos,
  useCampPartners,
  useEquipImpact,
  useEquipMatrix,
  useHeroDetail,
  useLaneMatchup,
  useMatches
} from '../lib/hooks'
import { duration as fmtDuration, number, percent } from '../lib/format'
import { heroPath } from '../lib/routes'
import {
  comboRows,
  heroKey,
  heroMatchups,
  heroRecent,
  heroTier,
  heroTone,
  leagueDelta,
  leagueRows,
  partnerCards,
  timeBuckets
} from '../lib/analysis/heroes'
import { AnalysisSection, JumpNav } from '../components/analysis/AnalysisSection'
import { BoardEmpty, MiniLine, PercentBar, StatGrid, TierBadge } from '../components/analysis/BoardBits'
import { BarList } from '../components/charts/BarList'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import type { CampHeroRow } from '../lib/types'

const JUMP = [
  { id: 'hd-lanes', label: '各位置' },
  { id: 'hd-partners', label: '常用搭档' },
  { id: 'hd-trios', label: '三人组合' },
  { id: 'hd-equips', label: '常见出装' },
  { id: 'hd-builds', label: '选手出装' },
  { id: 'hd-impact', label: '出装表现' },
  { id: 'hd-players', label: '选手使用' },
  { id: 'hd-teams', label: '战队使用' },
  { id: 'hd-league', label: '均值对照' },
  { id: 'hd-growth', label: '成长曲线' },
  { id: 'hd-recent', label: '最近出场' },
  { id: 'hd-time', label: '时间表现' },
  { id: 'hd-matchup', label: '同位置对位' }
]

const METRIC_LABELS: Record<string, string> = {
  conversion: '伤害转化',
  gpm: '分均经济',
  takenPerDeath: '每死承伤'
}

export function HeroDetailPage() {
  const { baseUrl } = useConnection()
  const { hero = '' } = useParams()
  const detailQuery = useHeroDetail(baseUrl, hero)
  const compareQuery = useCampCompare(baseUrl)
  const partnersQuery = useCampPartners(baseUrl, hero)
  const combosQuery = useCampCombos(baseUrl, 3)
  const matchupQuery = useLaneMatchup(baseUrl)
  const matrixQuery = useEquipMatrix(baseUrl, hero)
  const impactQuery = useEquipImpact(baseUrl, hero)
  const matchesQuery = useMatches(baseUrl)
  const [timeMode, setTimeMode] = useState<'week' | 'month' | 'year'>('month')
  const detail = detailQuery.data
  const compare = compareQuery.data

  const heroRows = useMemo<CampHeroRow[]>(() => {
    if (!compare) return []
    return (compare.heroes.own || []).filter((row) => row.hero === hero)
  }, [compare, hero])

  if (detailQuery.isLoading || compareQuery.isLoading) return <SkeletonPage cards={3} />
  if (detailQuery.isError || compareQuery.isError || !detail || !compare) {
    return <div className="page"><ErrorState error={detailQuery.error || compareQuery.error} onRetry={() => { void detailQuery.refetch(); void compareQuery.refetch() }} /></div>
  }

  const totalGames = heroRows.reduce((sum, row) => sum + row.games, 0)
  const totalWins = heroRows.reduce((sum, row) => sum + row.wins, 0)
  const totalDecided = heroRows.reduce((sum, row) => sum + row.decided, 0)
  const weighted = (key: 'kda' | 'gpm' | 'dpmTotal' | 'participation') => {
    const values = heroRows.filter((row) => typeof row[key] === 'number')
    const games = values.reduce((sum, row) => sum + row.games, 0)
    return games ? values.reduce((sum, row) => sum + (row[key] as number) * row.games, 0) / games : null
  }
  const winRate = totalDecided ? totalWins / totalDecided * 100 : null
  const tier = heroTier(winRate)
  const lanes = [...heroRows].sort((a, b) => b.games - a.games)
  const partners = partnerCards(partnersQuery.data)
  const trios = (combosQuery.data?.trios?.own?.combos || [])
    .filter((combo) => combo.heroes.includes(hero))
    .slice(0, 6)
  const equipItems = (matrixQuery.data?.payload.items || []).slice(0, 12)
  const impactRows = (impactQuery.data?.payload.rows || []).slice(0, 8)
  const league = leagueRows(detail)
  const recentMatches = heroRecent(matchesQuery.data || [], hero)
  const buckets = timeBuckets(matchesQuery.data || [], hero, timeMode)
  const matchups = heroMatchups(matchupQuery.data?.payload, hero)

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="HERO"
        title={<>{hero}<em>{[totalGames ? `本队 ${totalGames} 局使用` : '本期无本队样本', percent(winRate), `${tier} 档`, lanes[0]?.lane || ''].filter(Boolean).join(' · ')}</em></>}
        actions={<>
          <Link className="btn" to="/heroes">英雄榜</Link>
          <Link className="btn" to={`/heroes/compare?a=${encodeURIComponent(heroKey({ hero, lane: lanes[0]?.lane || '' }))}`}>英雄对比</Link>
        </>}
      />

      <StatGrid items={[
        { label: '出场', value: number(totalGames), note: `${lanes.length} 个位置记录` },
        { label: '胜率', value: percent(winRate), note: `${totalWins} 胜 / ${totalDecided} 决出`, tone: 'own' },
        { label: '档位', value: <TierBadge tier={tier} />, note: '按本期胜率分档', tone: 'accent' },
        { label: 'KDA', value: number(weighted('kda'), 2), note: '按位置场次加权' },
        { label: '分均经济', value: number(weighted('gpm')), note: '按位置场次加权' },
        { label: '分均输出', value: number(weighted('dpmTotal')), note: `参团 ${percent(weighted('participation'))}` }
      ]} />

      {totalGames < 2 ? <div className="board-banner">本队样本只有 {totalGames} 局，下面的分位与对位只作观察，不下强弱结论。</div> : null}

      <JumpNav items={JUMP} />

      <AnalysisSection id="hd-lanes" title="各位置表现" note="同一个英雄在不同分路的样本分开统计；胜率只以决出胜负的局为分母。">
        {lanes.length ? (
          <div className="hero-lane-grid">
            {lanes.map((row) => (
              <div className="hero-lane-card" key={row.lane}>
                <div className="hero-lane-head"><b>{row.lane}</b><TierBadge tier={heroTier(row.winRate)} /><span>{row.games} 局</span></div>
                <div className="hero-lane-rate"><strong>{percent(row.winRate)}</strong><PercentBar value={row.winRate} /></div>
                <div className="hero-lane-metrics">
                  <span><small>KDA</small><b>{number(row.kda, 2)}</b></span>
                  <span><small>分均经济</small><b>{number(row.gpm)}</b></span>
                  <span><small>分均输出</small><b>{number(row.dpmTotal)}</b></span>
                  <span><small>参团</small><b>{percent(row.participation)}</b></span>
                </div>
              </div>
            ))}
          </div>
        ) : <BoardEmpty title="本队还没有使用记录" />}
      </AnalysisSection>

      <div className="board-grid-2" id="hd-partners">
        <AnalysisSection title="常用搭档" note={`与 ${hero} 同队出场最多的英雄；协同 = 组合胜率 − 成员单英雄基准。`}>
          {partners.length ? (
            <div className="partner-card-list">
              {partners.map((row) => (
                <Link to={heroPath(row.partner)} className="partner-card" key={row.partner}>
                  <Portrait name={row.partner} size="sm" />
                  <span><b>{row.partner}</b><small>{row.games} 局 · {percent(row.winRate)}</small></span>
                  <em className={`tone-${(row.synergy || 0) >= 0 ? 'own' : 'foe'}`}>{row.synergy === null ? '—' : `${row.synergy > 0 ? '+' : ''}${row.synergy.toFixed(1)} pp`}</em>
                </Link>
              ))}
            </div>
          ) : <BoardEmpty title="还没有搭档样本">需要与队友同场出场。</BoardEmpty>}
        </AnalysisSection>

        <AnalysisSection id="hd-trios" title="核心三人组合" note="包含该英雄的三人组；小样本只作观察。">
          {trios.length ? (
            <div className="combo-card-list">
              {trios.map((combo) => (
                <div className="combo-card" key={combo.heroes.join('|')}>
                  <span>{combo.heroes.map((name) => <b key={name}>{name}</b>)}</span>
                  <span>{combo.games} 局 · {percent(combo.winRate)}</span>
                  <em className={`tone-${(combo.synergy || 0) >= 0 ? 'own' : 'foe'}`}>{combo.synergy === null ? '—' : `${combo.synergy > 0 ? '+' : ''}${combo.synergy.toFixed(1)} pp`}</em>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有三人组合" />}
        </AnalysisSection>
      </div>

      <div className="board-grid-2" id="hd-equips">
        <AnalysisSection title="常见出装" note="终局六格携带率；看不出出装顺序。">
          <BarList items={equipItems.map((item) => ({ label: item.label, value: item.pct, note: `${item.count} 次`, tone: 'accent' }))} digits={1} suffix="%" />
          {matrixQuery.isError ? <p className="board-note">装备矩阵读取失败。</p> : null}
        </AnalysisSection>

        <AnalysisSection id="hd-impact" title="出装与表现" note="带 / 不带该装备的中位数差；样本未控制局势，只作对照读数。">
          {impactRows.length ? (
            <div className="impact-list">
              {impactRows.map((row) => (
                <div className="impact-row" key={row.label}>
                  <b>{row.label}</b>
                  <span>{row.withN} / {row.withoutN} 局</span>
                  {Object.entries(row.deltas).slice(0, 3).map(([key, delta]) => (
                    <span key={key} className={`tone-${(delta.delta || 0) >= 0 ? 'own' : 'foe'}`}>
                      <small>{METRIC_LABELS[key] || key}</small>
                      {delta.delta === null ? '—' : `${delta.delta > 0 ? '+' : ''}${number(delta.delta, 2)}`}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="没有可对照的装备样本">需要同一英雄带与不带该装备的局。</BoardEmpty>}
        </AnalysisSection>
      </div>

      <AnalysisSection id="hd-builds" title="选手出装" note="按选手汇总常用装备与首件；不展示装备图标。">
        {detail.playerBuilds.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>选手</th><th>局数</th><th>胜率</th><th>KDA</th><th>终局经济</th><th>常用装备</th><th>首件</th></tr></thead>
              <tbody>
                {detail.playerBuilds.slice(0, 8).map((build) => (
                  <tr key={build.name}>
                    <td>{build.name}</td>
                    <td className="is-num">{build.games}</td>
                    <td className="is-num">{percent(build.winRate)}</td>
                    <td className="is-num">{number(build.kda, 2)}</td>
                    <td className="is-num">{number(build.gold)}</td>
                    <td>{build.equips.slice(0, 6).map((item) => `${item.name} ×${item.count}`).join(' · ') || '—'}</td>
                    <td>{build.first.slice(0, 2).map((item) => `${item.name} ×${item.count}`).join(' · ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="还没有选手出装记录" />}
      </AnalysisSection>

      <div className="board-grid-2" id="hd-players">
        <AnalysisSection title="选手使用榜" note="本队使用该英雄的选手；按局数排序。">
          {detail.players.length ? (
            <div className="rank-table">
              {detail.players.slice(0, 8).map((row, index) => (
                <div className="rank-row" key={row.name}>
                  <span className="rank-index">{index + 1}</span>
                  <Link to={`/players/${encodeURIComponent(row.name)}`}>{row.name}</Link>
                  <span>{row.games} 局</span>
                  <span>{percent(row.winRate)}</span>
                  <b>{number(row.kda, 2)}</b>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有本队选手使用" />}
        </AnalysisSection>

        <AnalysisSection id="hd-teams" title="战队使用" note="按对手战队汇总；用于看谁更常拿这个英雄。">
          {detail.teams.length ? (
            <div className="rank-table">
              {detail.teams.slice(0, 8).map((row, index) => (
                <div className="rank-row" key={row.name}>
                  <span className="rank-index">{index + 1}</span>
                  <b>{row.name}</b>
                  <span>{row.games} 局</span>
                  <span>{percent(row.winRate)}</span>
                  <b>{number(row.kda, 2)}</b>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有战队样本" />}
        </AnalysisSection>
      </div>

      <AnalysisSection id="hd-league" title="本队均值对照" note="该英雄 vs 本队同位置整体；差值百分比按本队均值归一。">
        <div className="league-grid">
          {league.map((row) => {
            const delta = leagueDelta(row.hero, row.all)
            return (
              <div className="league-card" key={row.key}>
                <span>{row.label}</span>
                <b>{number(row.hero, row.digits)}{row.suffix || ''} <small>vs {number(row.all, row.digits)}{row.suffix || ''}</small></b>
                <em className={`tone-${(delta || 0) >= 0 ? 'own' : 'foe'}`}>{delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}%`}</em>
              </div>
            )
          })}
        </div>
      </AnalysisSection>

      <AnalysisSection id="hd-growth" title="成长曲线" note={`本队使用该英雄时的经济差曲线；${detail.curveGames || 0} 局有回放采样。`}>
        {detail.growth.length ? (
          <>
            <MiniLine values={detail.growth.map((point) => ({ x: point.t, y: point.value }))} width={760} height={190} label={`${hero} 经济差成长`} />
            <div className="mini-line-axis"><span>{fmtDuration(detail.growth[0]?.t || 0)}</span><span>分钟 · 我方减对手经济差</span><span>{fmtDuration(detail.growth[detail.growth.length - 1]?.t || 0)}</span></div>
          </>
        ) : <BoardEmpty title="没有可用的经济曲线">这一批对局缺少回放时间轴。</BoardEmpty>}
      </AnalysisSection>

      <div className="board-grid-2" id="hd-recent">
        <AnalysisSection title="最近出场" note="按日期倒序；点对局进入单局深度。">
          {recentMatches.length ? (
            <div className="recent-match-list">
              {recentMatches.map((match) => (
                <Link key={match.key} to={`/matches/${encodeURIComponent(match.key)}`} className="recent-match-row">
                  <span>{match.date}</span>
                  <b>{match.opponent || '对手未标注'}</b>
                  <span className={`board-tag tone-${match.result === 'win' ? 'own' : 'foe'}`}>{match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '未定'}</span>
                  <small>{match.duration ? `${Math.round(match.duration / 60)} 分` : '—'}</small>
                </Link>
              ))}
            </div>
          ) : <BoardEmpty title="还没有最近出场" />}
        </AnalysisSection>

        <AnalysisSection id="hd-time" title="时间表现" note="按周 / 月 / 年聚合；胜率只以有胜负的局为分母。">
          <div className="segmented">
            {(['week', 'month', 'year'] as const).map((mode) => (
              <button type="button" key={mode} className={timeMode === mode ? 'is-active' : ''} onClick={() => setTimeMode(mode)}>
                {mode === 'week' ? '周' : mode === 'month' ? '月' : '年'}
              </button>
            ))}
          </div>
          {buckets.length ? (
            <div className="time-buckets">
              {buckets.map((bucket) => (
                <div className="time-bucket" key={bucket.key}>
                  <span>{bucket.label}</span>
                  <i><em style={{ width: `${bucket.winRate ?? 0}%` }} /></i>
                  <b>{bucket.games} 局 · {percent(bucket.winRate)}</b>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="没有时间样本" />}
        </AnalysisSection>
      </div>

      <AnalysisSection id="hd-matchup" title="同位置对位" note={`该英雄作为${hero}一侧时的对手英雄；只统计同路各有一人的局。`}>
        {matchups.length ? (
          <div className="matchup-grid">
            {matchups.map((row) => (
              <div className="matchup-card" key={row.hero}>
                <Portrait name={row.hero} size="sm" />
                <span><b>{row.hero}</b><small>{row.n} 次对位</small></span>
                <span className="matchup-rate">{percent(row.aheadRate)} <small>领先率</small></span>
                <span className="matchup-gold">{row.avgGoldDiff === null ? '—' : `${row.avgGoldDiff > 0 ? '+' : ''}${number(row.avgGoldDiff)} 金`}</span>
              </div>
            ))}
          </div>
        ) : <BoardEmpty title="没有可判定的同位置对位" />}
      </AnalysisSection>

      <div className="board-foot">装备与对位只作对照读数，不推断因果；分位与均值为本期营地面板口径。</div>
    </div>
  )
}
