import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useCampCompare } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { heroPath } from '../lib/routes'
import {
  HERO_COMPARE_METRICS,
  heroKey,
  heroMetric,
  heroRows,
  heroTier,
  metricText,
  parseHeroKey,
  quantile,
  rankOf
} from '../lib/analysis/heroes'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid, TierBadge, WinRing } from '../components/analysis/BoardBits'
import { VersusBars } from '../components/charts/VersusBars'
import { ScatterChart } from '../components/charts/ScatterChart'
import { BarList } from '../components/charts/BarList'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import type { CampHeroRow } from '../lib/types'

export function HeroComparePage() {
  const { baseUrl } = useConnection()
  const query = useCampCompare(baseUrl)
  const [searchParams] = useSearchParams()
  const [side, setSide] = useState<'own' | 'enemy'>('own')
  const [aKey, setAKey] = useState(searchParams.get('a') || '')
  const [bKey, setBKey] = useState(searchParams.get('b') || '')
  const compare = query.data

  const candidates = useMemo(() => (compare ? heroRows(compare, side) : []), [compare, side])
  const fallbackA = candidates[0] ? heroKey(candidates[0]) : ''
  const fallbackB = candidates[1] ? heroKey(candidates[1]) : fallbackA
  const a = candidates.find((row) => heroKey(row) === (aKey || fallbackA)) || candidates[0]
  const b = candidates.find((row) => heroKey(row) === (bKey || fallbackB)) || candidates[1] || candidates[0]

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !compare) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }
  if (!a || !b) {
    return (
      <div className="page">
        <PageHeader eyebrow="HERO COMPARE" title="英雄对比" actions={<Link className="btn" to="/heroes">英雄榜</Link>} />
        <BoardEmpty title="还没有可对比的英雄">这一侧没有足够的英雄样本。</BoardEmpty>
      </div>
    )
  }

  const metrics = HERO_COMPARE_METRICS.map((metric) => {
    const av = heroMetric(a, metric.key)
    const bv = heroMetric(b, metric.key)
    return { metric, a: av, b: bv, diff: av !== null && bv !== null ? av - bv : null }
  })
  const aLeads = metrics.filter((row) => row.diff !== null && row.diff > 0).length
  const bLeads = metrics.filter((row) => row.diff !== null && row.diff < 0).length
  const biggest = [...metrics].filter((row) => row.diff !== null).sort((x, y) => Math.abs(y.diff || 0) - Math.abs(x.diff || 0))[0]
  const winRates = candidates.map((row) => row.winRate).filter((value): value is number => typeof value === 'number')
  const rankA = rankOf(a.winRate, winRates)
  const rankB = rankOf(b.winRate, winRates)
  const p10 = quantile(winRates, 0.1)
  const p90 = quantile(winRates, 0.9)
  const p25 = quantile(winRates, 0.25)
  const p75 = quantile(winRates, 0.75)
  const scatter = candidates.map((row) => ({
    x: row.gpm,
    y: row.dpmTotal,
    label: heroKey(row),
    tone: heroKey(row) === heroKey(a) ? 'own' as const : heroKey(row) === heroKey(b) ? 'foe' as const : 'muted' as const,
    note: `${row.games} 局 · 胜率 ${percent(row.winRate)}`
  }))
  const bins = [
    { label: '1 局', min: 1, max: 1 },
    { label: '2–3 局', min: 2, max: 3 },
    { label: '4–6 局', min: 4, max: 6 },
    { label: '7–10 局', min: 7, max: 10 },
    { label: '11+ 局', min: 11, max: Infinity }
  ].map((bin) => {
    const rows = candidates.filter((row) => row.games >= bin.min && row.games <= bin.max)
    const rates = rows.map((row) => row.winRate).filter((value): value is number => typeof value === 'number')
    return { ...bin, heroes: rows.length, winRate: rates.length ? rates.reduce((sum, value) => sum + value, 0) / rates.length : null }
  })

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="HERO COMPARE"
        title="英雄对比"
        subtitle="两个英雄摆在一起，看谁更稳、强在哪、下一阶段练谁。"
        actions={<Link className="btn" to="/heroes">英雄榜</Link>}
      />

      <div className="board-toolbar">
        <div className="segmented">
          <button type="button" className={side === 'own' ? 'is-active' : ''} onClick={() => { setSide('own'); setAKey(''); setBKey('') }}>本队</button>
          <button type="button" className={side === 'enemy' ? 'is-active' : ''} onClick={() => { setSide('enemy'); setAKey(''); setBKey('') }}>对手</button>
        </div>
        <select value={heroKey(a)} onChange={(event) => setAKey(event.target.value)} aria-label="英雄 A">
          {candidates.map((row) => <option value={heroKey(row)} key={heroKey(row)}>{row.hero} · {row.lane}</option>)}
        </select>
        <select value={heroKey(b)} onChange={(event) => setBKey(event.target.value)} aria-label="英雄 B">
          {candidates.map((row) => <option value={heroKey(row)} key={heroKey(row)}>{row.hero} · {row.lane}</option>)}
        </select>
        <button type="button" className="btn btn-sm" onClick={() => { setAKey(heroKey(b)); setBKey(heroKey(a)) }}>交换</button>
      </div>

      <div className="compare-head">
        <HeroIdentity row={a} />
        <div className="compare-score">
          <span><b>{aLeads}</b><small>项领先</small></span>
          <i>:</i>
          <span><b>{bLeads}</b><small>项领先</small></span>
          <p>{biggest ? `最大差距：${biggest.metric.label}（${metricText(heroMetric(a, biggest.metric.key), biggest.metric)} vs ${metricText(heroMetric(b, biggest.metric.key), biggest.metric)}）` : '样本不足，暂不做差距结论。'}</p>
        </div>
        <HeroIdentity row={b} align="right" />
      </div>

      <AnalysisSection title="六项对位" note="出场、胜率、KDA、分均经济、分均输出、参团率；原始值并列。">
        <VersusBars
          rows={HERO_COMPARE_METRICS.map((metric) => ({
            label: metric.label,
            own: heroMetric(a, metric.key),
            foe: heroMetric(b, metric.key),
            digits: metric.digits,
            suffix: metric.suffix
          }))}
          ownTitle={`${a.hero} · ${a.lane}`}
          foeTitle={`${b.hero} · ${b.lane}`}
        />
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="胜率可信度" note="环内为胜率；分布带为同阵营英雄的 P10–P90，深色为 P25–P75。">
          <div className="hero-ring-row">
            <div><WinRing value={a.winRate} label={a.hero} /><span>全英雄第 {rankA ?? '—'} / {winRates.length}</span></div>
            <div><WinRing value={b.winRate} label={b.hero} /><span>全英雄第 {rankB ?? '—'} / {winRates.length}</span></div>
          </div>
          <div className="dist-compare">
            <div className="dist-band">
              <span>{percent(p10)}</span><i><em style={{ left: `${p10 ?? 0}%`, width: `${Math.max(0, (p75 ?? 0) - (p25 ?? 0))}%` }} /></i><span>{percent(p90)}</span>
            </div>
            <div className="dist-points">
              <span className="is-own" style={{ left: `${a.winRate ?? 0}%` }}>{a.hero}</span>
              <span className="is-foe" style={{ left: `${b.winRate ?? 0}%` }}>{b.hero}</span>
            </div>
            <p className="board-note">P25–P75 {percent(p25)}–{percent(p75)}；样本 {winRates.length} 个英雄。</p>
          </div>
        </AnalysisSection>

        <AnalysisSection title="分均产出" note="分均经济、输出与承伤；输出 ÷ 承伤 = 每点承伤换来的输出。">
          <VersusBars
            rows={[
              { label: '分均经济', own: a.gpm, foe: b.gpm, digits: 0 },
              { label: '分均输出', own: a.dpmTotal, foe: b.dpmTotal, digits: 0 },
              { label: '分均承伤', own: a.dtpm, foe: b.dtpm, digits: 0 },
              { label: '输出/承伤', own: a.dtpm ? (a.dpmTotal || 0) / a.dtpm : null, foe: b.dtpm ? (b.dpmTotal || 0) / b.dtpm : null, digits: 2 }
            ]}
            ownTitle={a.hero}
            foeTitle={b.hero}
          />
        </AnalysisSection>
      </div>

      <AnalysisSection title="全英雄坐标" note="横轴分均经济、纵轴分均输出；点选一个英雄替换 B。">
        <ScatterChart
          points={scatter}
          xLabel="分均经济"
          yLabel="分均输出"
          selected={heroKey(b)}
          onPick={(label) => setBKey(label)}
          height={300}
        />
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="出场与胜率" note="按出场局数分箱；组均胜率为简单平均，不按场次加权。">
          <BarList items={bins.map((bin) => ({ label: bin.label, value: bin.heroes, note: `${percent(bin.winRate)} 组均胜率` }))} digits={0} />
        </AnalysisSection>

        <AnalysisSection title="出场排行" note="同阵营出场最多的前 8 个英雄。">
          <BarList
            items={[...candidates].slice(0, 8).map((row) => ({ label: `${row.hero} · ${row.lane}`, value: row.games, note: percent(row.winRate), tone: heroKey(row) === heroKey(a) ? 'own' : heroKey(row) === heroKey(b) ? 'foe' : 'muted' }))}
            digits={0}
          />
        </AnalysisSection>
      </div>

      <div className="board-foot">分位与排名只在当前阵营的英雄池内计算；样本少的英雄不进入可信度结论。本页使用全部营地面板及关联回放。</div>
    </div>
  )
}

function HeroIdentity({ row, align = 'left' }: { row: CampHeroRow; align?: 'left' | 'right' }) {
  const tier = heroTier(row.winRate)
  return (
    <Link to={heroPath(row.hero)} className={`compare-identity${align === 'right' ? ' is-right' : ''}`}>
      <Portrait name={row.hero} size="lg" />
      <span><b>{row.hero}</b><small>{row.lane} · {row.games} 局 · {percent(row.winRate)}</small></span>
      <span className="compare-score-value"><TierBadge tier={tier} /></span>
    </Link>
  )
}
