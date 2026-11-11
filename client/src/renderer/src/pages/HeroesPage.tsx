import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useCampCompare } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { heroPath } from '../lib/routes'
import { heroPool, heroRows, heroTier, heroTone } from '../lib/analysis/heroes'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid, TierBadge } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'

export function HeroesPage() {
  const { baseUrl } = useConnection()
  const query = useCampCompare(baseUrl)
  const [search, setSearch] = useState('')
  const [tier, setTier] = useState('')
  const compare = query.data

  const rows = useMemo(() => {
    if (!compare) return []
    const keyword = search.trim().toLowerCase()
    return heroRows(compare, 'own').filter((row) => {
      if (keyword && !row.hero.toLowerCase().includes(keyword)) return false
      if (tier && heroTier(row.winRate) !== tier) return false
      return true
    })
  }, [compare, search, tier])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !compare) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const all = heroRows(compare, 'own')
  const pool = heroPool(compare, 'own')
  const topWin = [...all].filter((row) => row.decided >= 2).sort((a, b) => (b.winRate || 0) - (a.winRate || 0))[0]
  const topPick = all[0]
  const sCount = all.filter((row) => row.decided >= 3 && heroTier(row.winRate) === 'S').length

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="HEROES"
        title="英雄榜"
        subtitle="从营地选用与结算面板观察英雄池。"
        actions={<>
          <Link className="btn" to="/heroes/compare">英雄对比</Link>
          <Link className="btn" to="/heroes/combos">英雄组合</Link>
        </>}
      />

      <StatGrid items={[
        { label: '本队英雄数', value: number(pool.heroes), note: `有效英雄 ${number(pool.effective, 1)}` },
        { label: '本队出场', value: number(pool.picks), note: `${compare.games} 局营地样本` },
        { label: 'S 档', value: number(sCount), note: '≥3 局且胜率 ≥55%' },
        { label: '最高胜率', value: topWin ? `${topWin.hero} ${percent(topWin.winRate)}` : '—', note: topWin ? `${topWin.games} 局` : '', tone: 'own' },
        { label: '出场最多', value: topPick ? `${topPick.hero} ${topPick.games} 局` : '—', note: topPick ? `${percent(topPick.winRate)} 胜率` : '' }
      ]} />

      <div className="board-banner">
        本页使用全部营地面板及关联回放，首页的日期 / 来源筛选不适用于此处；档位只按本期胜率分档，样本少时仅作观察。
      </div>

      <div className="board-toolbar">
        <input className="board-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索英雄" aria-label="搜索英雄" />
        <select value={tier} onChange={(event) => setTier(event.target.value)} aria-label="档位">
          <option value="">全部档位</option>
          {['S', 'A', 'B', 'C'].map((value) => <option value={value} key={value}>{value} 档</option>)}
        </select>
        <span className="board-muted">{rows.length} / {all.length} 个英雄</span>
      </div>

      <AnalysisSection title="英雄卡片" note="点卡片看各位置、搭档、三人组合、选手使用、均值对照与时间表现。">
        {rows.length ? (
          <div className="hero-card-grid">
            {rows.map((row) => {
              const tierValue = heroTier(row.winRate)
              return (
                <Link to={heroPath(row.hero)} className={`hero-card ${heroTone(tierValue)}`} key={`${row.hero}-${row.lane}`}>
                  <div className="hero-card-head">
                    <Portrait name={row.hero} size="lg" />
                    <span><b>{row.hero}</b><small>{row.lane} · {row.games} 局</small></span>
                    <TierBadge tier={tierValue} />
                  </div>
                  <div className="hero-card-rate">
                    <strong>{percent(row.winRate)}</strong>
                    <span><small>胜率</small><em>{row.decided} 局决出</em></span>
                  </div>
                  <div className="hero-card-metrics">
                    <span><small>KDA</small><b>{number(row.kda, 2)}</b></span>
                    <span><small>分均经济</small><b>{number(row.gpm)}</b></span>
                    <span><small>分均输出</small><b>{number(row.dpmTotal)}</b></span>
                  </div>
                </Link>
              )
            })}
          </div>
        ) : <BoardEmpty title="没有符合筛选的英雄">换搜索词或档位再试。</BoardEmpty>}
      </AnalysisSection>

      <div className="board-foot">档位：胜率 ≥55 S / ≥50 A / ≥45 B / 其余 C；使用率请到 BP 概览看选禁占比。</div>
    </div>
  )
}
