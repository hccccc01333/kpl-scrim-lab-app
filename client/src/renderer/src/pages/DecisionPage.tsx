import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useConnection } from '../lib/app-context'
import { useTrainingEffect } from '../lib/hooks'
import {
  useAdvantage,
  useBriefing,
  useDecisionCatalog,
  useFights,
  useLoss,
  useOpening,
  useResource,
  type AdvantageBandPoint,
  type AdvantageCi,
  type AdvantageGameRow,
  type DecisionBriefing,
  type DecisionBriefingItem,
  type DecisionCandidate,
  type DecisionCatalog,
  type DecisionCoverage,
  type FightSelected,
  type LossRow,
  type LossSeries,
  type OpeningReport,
  type OpeningRoute,
  type OpeningRoutePoint,
  type ResourceAnomaly,
  type ResourcePlayer
} from '../lib/decision'
import { duration as fmtDuration, number, percent, signed } from '../lib/format'
import { matchPath } from '../lib/routes'
import { PLAYER_LANES } from '../lib/analysis/players'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'
import {
  ArrivalBars,
  BandChart,
  EconomyTimeline,
  OpeningHeat,
  QuadrantChart,
  type ArrivalBarItem,
  type BandPointValue,
  type BandSeries,
  type EconomyEvent,
  type EconomyEventKind,
  type EconomyPoint,
  type EconomyWindow,
  type OpeningHeatCell,
  type OpeningHeatRoute,
  type QuadrantPoint
} from '../components/charts/DecisionCharts'

/* ── 常量与纯函数 ───────────────────────────────────────────────── */

const TABS = [
  { id: 'review', label: '赛后复盘' },
  { id: 'prep', label: '赛前备战' },
  { id: 'player', label: '选手研究' },
  { id: 'training', label: '训练验证' }
] as const

type TabId = (typeof TABS)[number]['id']

const KIND_LABEL: Record<string, string> = {
  comeback_leak: '优势回撤',
  loss_pattern: '失利关键链',
  slow_conversion: '优势兑现',
  fight_arrival: '团战到位',
  resource_mismatch: '资源分配',
  opening_habit: '开局路线',
  coverage_gap: '采集覆盖',
  training_gap: '训练验证'
}

const ANALYSIS_TAB: Record<string, TabId> = {
  advantage_retention: 'review',
  loss_chain: 'review',
  fight_execution: 'review',
  resource_allocation: 'player',
  opening_routes: 'prep',
  training_verification: 'training'
}

const SEVERITY_LABEL: Record<string, string> = {
  high: '高优先',
  medium: '中优先',
  low: '低优先'
}

const CONFIDENCE_LABEL: Record<string, string> = {
  high: '证据相对充分',
  medium: '中等样本',
  low: '小样本'
}

interface FilterState {
  opponent: string
  result: string
  from: string
  to: string
}

const EMPTY_FILTERS: FilterState = { opponent: '', result: '', from: '', to: '' }

function isTabId(value: string | null): value is TabId {
  return value === 'review' || value === 'prep' || value === 'player' || value === 'training'
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function resultText(result?: string | null): string {
  if (result === 'win') return '胜'
  if (result === 'loss') return '负'
  return '结果未知'
}

function resultTagTone(result?: string | null): 'own' | 'foe' | 'muted' {
  if (result === 'win') return 'own'
  if (result === 'loss') return 'foe'
  return 'muted'
}

function formatCi(ci?: AdvantageCi | number[] | null, low?: number | null, high?: number | null): string {
  if (typeof low === 'number' && typeof high === 'number') return `${number(low, 1)}–${number(high, 1)}%`
  if (!ci) return '—'
  if (Array.isArray(ci)) return `${number(ci[0], 1)}–${number(ci[1], 1)}%`
  return `${number(ci.low, 1)}–${number(ci.high, 1)}%`
}

function linkQuery(link?: string): URLSearchParams {
  if (!link) return new URLSearchParams()
  const index = link.indexOf('?')
  return new URLSearchParams(index >= 0 ? link.slice(index + 1) : '')
}

function briefTab(item: DecisionBriefingItem): TabId {
  const tab = linkQuery(item.link).get('tab')
  if (isTabId(tab)) return tab
  return ANALYSIS_TAB[item.analysis || ''] || 'review'
}

function briefGame(item: DecisionBriefingItem): string {
  return linkQuery(item.link).get('game') || ''
}

function eventKindFromCandidate(kind?: string | null): EconomyEventKind {
  const text = (kind || '').toLowerCase()
  if (text.includes('death') || text.includes('kill') || text.includes('阵亡')) return 'death'
  if (text.includes('fight') || text.includes('battle') || text.includes('团')) return 'fight'
  if (text.includes('objective') || text.includes('resource') || text.includes('tower') || text.includes('buff')) return 'objective'
  return 'other'
}

function candidateText(candidate: DecisionCandidate): string {
  const time = num(candidate.timeSec) ?? num(candidate.t)
  const base = candidate.text || candidate.label || candidate.name || candidate.type || candidate.kind || '候选事件'
  return time === null ? base : `${base} · ≈${fmtDuration(time)}`
}

function buildTimelinePoints(series?: LossSeries | null): EconomyPoint[] {
  if (!series) return []
  const times = Array.isArray(series.times) ? series.times : []
  const own = Array.isArray(series.ownDiff) && series.ownDiff.length
    ? series.ownDiff
    : Array.isArray(series.rawDiff) ? series.rawDiff : []
  return times.map((time, index) => {
    const value = own[index]
    return { t: time, v: typeof value === 'number' && Number.isFinite(value) ? value : null }
  })
}

function buildTimelineWindows(chains: LossRow[]): EconomyWindow[] {
  return chains.flatMap((chain, index) => {
    const start = num(chain.start)
    if (start === null) return []
    const end = num(chain.end) ?? start
    return [{ id: `chain-${index}`, start, end, tone: 'loss' as const }]
  })
}

function buildTimelineEvents(chains: LossRow[]): EconomyEvent[] {
  const events: EconomyEvent[] = []
  chains.forEach((chain, index) => {
    const start = num(chain.start)
    if (start !== null) {
      events.push({
        id: `chain-${index}`,
        t: start,
        kind: 'other',
        label: chain.typeLabel || chain.type || '损失窗口',
        note: `窗口内经济差 ${signed(chain.delta)}`
      })
    }
    ;(chain.candidates || []).forEach((candidate, candidateIndex) => {
      const time = num(candidate.timeSec) ?? num(candidate.t)
      if (time === null) return
      events.push({
        id: `chain-${index}-c${candidateIndex}`,
        t: time,
        kind: eventKindFromCandidate(candidate.kind),
        label: candidate.label || candidate.text || candidate.kind || '候选事件',
        note: candidate.text || undefined
      })
    })
  })
  return events
}

function buildBandSeries(bands?: AdvantageBandPoint[]): BandSeries[] {
  if (!bands || !bands.length) return []
  const pick = (key: 'win' | 'loss' | 'all', label: string, tone: BandSeries['tone']): BandSeries => {
    const points: BandPointValue[] = []
    for (const band of bands) {
      const minute = num(band.minute) ?? (num(band.t) !== null ? (num(band.t) as number) / 60 : null)
      if (minute === null) continue
      const stat = band[key]
      const fallbackAll = key === 'all' && !stat ? { p25: band.p25, p50: band.p50, p75: band.p75 } : null
      const n = num(stat?.n)
        ?? num(key === 'win' ? band.nWin : key === 'loss' ? band.nLoss : band.nAll)
        ?? num(band.n)
        ?? 0
      points.push({
        minute,
        n,
        p25: num(stat?.p25) ?? num(fallbackAll?.p25),
        p50: num(stat?.p50) ?? num(fallbackAll?.p50),
        p75: num(stat?.p75) ?? num(fallbackAll?.p75)
      })
    }
    return { key, label, tone, points }
  }
  return [pick('win', '胜局', 'own'), pick('loss', '负局', 'foe'), pick('all', '全部', 'accent')]
    .filter((series) => series.points.some((point) => point.n > 0))
}

function playerPointId(index: number): string {
  return `decision-player-${index}`
}

function buildQuadrantPoints(players: ResourcePlayer[]): QuadrantPoint[] {
  const points: QuadrantPoint[] = []
  players.forEach((player, index) => {
    const x = num(player.goldShare)
    const y = num(player.heroDamageShare)
    if (x === null || y === null) return
    const opponent = player.opponentName || player.opponentId || ''
    points.push({
      id: playerPointId(index),
      x,
      y,
      lane: player.lane,
      label: player.name || player.playerId || `选手 ${index + 1}`,
      hero: player.hero,
      gpm: num(player.gpm),
      deaths: num(player.deaths),
      towerDamage: num(player.towerDamage),
      source: [player.date, opponent ? `对阵 ${opponent}` : '', player.result ? resultText(player.result) : '结果未知']
        .filter(Boolean)
        .join(' · '),
      note: player.quadrant || undefined
    })
  })
  return points
}

function playerIndexOf(pointId: string | null): number | null {
  if (!pointId) return null
  const index = Number(pointId.replace('decision-player-', ''))
  return Number.isInteger(index) ? index : null
}

function routePoints(route: OpeningRoute): [number, number][] {
  const source = route.representative?.points
  const raw: OpeningRoutePoint[] = Array.isArray(source) && source.length
    ? source
    : Array.isArray(route.points) && route.points.length
      ? route.points
      : Array.isArray(route.route) ? route.route : []
  const out: [number, number][] = []
  for (const point of raw) {
    if (Array.isArray(point)) {
      if (point.length >= 3) {
        const x = num(point[1])
        const y = num(point[2])
        if (x !== null && y !== null) out.push([x, y])
      } else {
        const x = num(point[0])
        const y = num(point[1])
        if (x !== null && y !== null) out.push([x, y])
      }
    } else if (point && typeof point === 'object') {
      const x = num(point.x)
      const y = num(point.y)
      if (x !== null && y !== null) out.push([x, y])
    }
  }
  return out
}

function buildHeatCells(report?: OpeningReport): OpeningHeatCell[] {
  return (report?.heat?.cells || []).flatMap((cell) => {
    const x = num(cell.x)
    const y = num(cell.y)
    const n = num(cell.n)
    if (x === null || y === null || n === null || n <= 0) return []
    return [{ x, y, n }]
  })
}

function buildHeatRoutes(report?: OpeningReport): OpeningHeatRoute[] {
  return (report?.routes || []).flatMap((route, index) => {
    const points = routePoints(route)
    if (points.length < 2) return []
    const count = num(route.count) ?? 0
    return [{
      id: `route-${index}`,
      label: `${route.lane || '分路未知'} · ${count} 次`,
      lane: route.lane,
      tone: 'foe' as const,
      points
    }]
  })
}

function buildArrivalItems(selected?: FightSelected | null): ArrivalBarItem[] {
  if (!selected) return []
  const labelOf = (hero?: string | null, lane?: string | null, fallback?: string | null) => {
    if (hero) return lane ? `${hero} · ${lane}` : hero
    return lane || fallback || '参战成员'
  }
  const bars = selected.arrivalBars || []
  if (bars.length) {
    return bars.flatMap((bar, index) => {
      const lag = num(bar.to) ?? num(bar.from) ?? 0
      return [{
        id: `${bar.player || index}-${index}`,
        name: labelOf(bar.hero, bar.lane, bar.player),
        hero: bar.hero,
        lane: bar.lane,
        camp: bar.camp === 'enemy' ? 'enemy' : 'own',
        lagSec: lag
      }]
    })
  }
  return (selected.members || []).map((member, index) => ({
    id: member.objId || `${member.player || index}`,
    name: labelOf(member.hero, member.lane, member.player || member.objId),
    hero: member.hero,
    lane: member.lane,
    camp: member.camp === 'enemy' ? 'enemy' : 'own',
    lagSec: num(member.arrivalLagSec) ?? 0
  }))
}

/* ── 页面 ───────────────────────────────────────────────────────── */

export function DecisionPage() {
  const { baseUrl } = useConnection()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab: TabId = isTabId(params.get('tab')) ? (params.get('tab') as TabId) : 'review'
  const urlGame = params.get('game') || ''

  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [selectedChain, setSelectedChain] = useState<number | null>(null)
  const [fightId, setFightId] = useState('')
  const [showAllFights, setShowAllFights] = useState(false)
  const [prepOpponent, setPrepOpponent] = useState('')
  const [prepLane, setPrepLane] = useState('')
  const [prepRoute, setPrepRoute] = useState<string | null>(null)
  const [playerLane, setPlayerLane] = useState('')
  const [selectedPoint, setSelectedPoint] = useState<string | null>(null)
  const prepInitRef = useRef(false)

  const catalogQuery = useDecisionCatalog(baseUrl)
  const catalog = catalogQuery.data
  const games = catalog?.games || []
  const latestGameId = games.length ? games[games.length - 1].id : ''
  const reviewGame = useMemo(() => {
    if (urlGame && games.some((game) => game.id === urlGame)) return urlGame
    return latestGameId
  }, [urlGame, games, latestGameId])
  const reviewGameInfo = games.find((game) => game.id === reviewGame) || null

  const rangeParams = useMemo<FilterState>(() => ({
    opponent: filters.opponent,
    from: filters.from,
    to: filters.to,
    result: filters.result
  }), [filters.opponent, filters.from, filters.to, filters.result])

  const briefingQuery = useBriefing(baseUrl, { ...rangeParams, limit: 5 })
  const lossQuery = useLoss(baseUrl, { ...rangeParams, game: reviewGame }, tab === 'review' && Boolean(reviewGame))
  const advantageQuery = useAdvantage(baseUrl, rangeParams, tab === 'review')
  const fightsQuery = useFights(
    baseUrl,
    { ...rangeParams, game: fightId ? `${reviewGame}::${fightId}` : reviewGame },
    tab === 'review' && Boolean(reviewGame)
  )
  const openingQuery = useOpening(
    baseUrl,
    { ...rangeParams, opponent: prepOpponent, lane: prepLane, side: 'enemy' },
    tab === 'prep'
  )
  const resourceQuery = useResource(
    baseUrl,
    { ...rangeParams, lane: playerLane, side: 'own' },
    tab === 'player'
  )
  const trainingQuery = useTrainingEffect(tab === 'training' ? baseUrl : '')

  useEffect(() => {
    if (prepInitRef.current) return
    const opponents = catalogQuery.data?.opponents || []
    const first = opponents.find((item) => (item.replayGames || 0) > 0) || opponents[0]
    if (first) {
      prepInitRef.current = true
      setPrepOpponent(first.id)
    }
  }, [catalogQuery.data])

  useEffect(() => {
    setSelectedChain(null)
    setFightId('')
  }, [reviewGame])

  useEffect(() => {
    setPrepRoute(null)
  }, [prepOpponent, prepLane])

  useEffect(() => {
    setSelectedPoint(null)
  }, [playerLane])

  useEffect(() => {
    const workspace = document.querySelector('.workspace')
    if (workspace) workspace.scrollTop = 0
  }, [tab])

  const patchParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setParams(next)
  }

  const selectTab = (next: TabId) => patchParams({ tab: next })

  const selectGame = (id: string) => patchParams({ tab: 'review', game: id })

  const openBriefingItem = (item: DecisionBriefingItem) => {
    const targetTab = briefTab(item)
    const game = briefGame(item)
    patchParams({ tab: targetTab, game: game || (targetTab === 'review' ? reviewGame : '') })
  }

  const pickTimelineEvent = (id: string) => {
    const match = /^chain-(\d+)/.exec(id)
    if (!match) return
    const index = Number(match[1])
    setSelectedChain(index)
    window.setTimeout(() => {
      document.getElementById(`decision-chain-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 10)
  }

  const refresh = () => {
    void queryClient.invalidateQueries({
      predicate: (query) => String(query.queryKey[0] || '').startsWith('decision-')
    })
  }

  if (catalogQuery.isLoading) return <SkeletonPage cards={4} />
  if (catalogQuery.isError || !catalog) {
    return (
      <div className="page">
        <ErrorState error={catalogQuery.error} onRetry={() => void catalogQuery.refetch()} />
      </div>
    )
  }

  const coverage = catalog.coverage || {}
  const opponents = catalog.opponents || []
  const loss = lossQuery.data
  const lossGame = loss?.game || null
  const lossChains = lossGame?.chains?.length ? lossGame.chains : (loss?.rows || [])
  const timelinePoints = buildTimelinePoints(lossGame?.series)
  const timelineEvents = buildTimelineEvents(lossChains)
  const timelineWindows = buildTimelineWindows(lossChains)
  const advantage = advantageQuery.data
  const advantageGame = (advantage?.games || []).find((game) => (game.id || game.game) === reviewGame) || null
  const bandSeries = buildBandSeries(advantage?.bands)
  const drawdownRows = [...(advantage?.games || [])]
    .filter((game) => num(game.drawdown) !== null)
    .sort((a, b) => (num(b.drawdown) || 0) - (num(a.drawdown) || 0))
    .slice(0, 10)
  const fights = fightsQuery.data
  const fightSummary = fights?.summary || null
  const fightRowsAll = fights?.rows || []
  const fightRows = fightRowsAll.slice(0, showAllFights ? 12 : 6)
  const fightArrivalItems = buildArrivalItems(fights?.selected)
  /* 开局人数差不再铺 11 行，按「落后 / 持平 / 领先」三组汇总，够教练判断且不占屏。 */
  const openingGroups = [
    { label: '落后（≤ -1 人）', match: (value: number) => value <= -1 },
    { label: '持平（0 人）', match: (value: number) => value === 0 },
    { label: '领先（≥ +1 人）', match: (value: number) => value >= 1 }
  ].map((group) => {
    const rows = (fightSummary?.openingBuckets || []).filter((bucket) => {
      const value = num(bucket.advStart)
      return value !== null && group.match(value)
    })
    const n = rows.reduce((sum, bucket) => sum + (num(bucket.n) || 0), 0)
    const wins = rows.reduce((sum, bucket) => sum + (num(bucket.wins) || 0), 0)
    return { label: group.label, n, wins, winRate: n ? (wins / n) * 100 : null, enough: n >= 8 }
  })
  const opening = openingQuery.data
  const heatCells = buildHeatCells(opening)
  const heatRoutes = buildHeatRoutes(opening)
  const openingCalibrated = opening?.heat?.calibrated ?? opening?.coverage?.calibrated ?? true
  const selectedOpponent = opponents.find((opponent) => opponent.id === prepOpponent) || null
  const openingRoutes = opening?.routes || []
  const resource = resourceQuery.data
  const resourcePlayers = resource?.players || []
  const quadrantPoints = buildQuadrantPoints(resourcePlayers)
  const selectedPlayerIndex = playerIndexOf(selectedPoint)
  const selectedPlayer = selectedPlayerIndex !== null ? resourcePlayers[selectedPlayerIndex] || null : null
  const anomalies: ResourceAnomaly[] = resource?.anomalies || []
  const trainingResults = trainingQuery.data?.results || []
  const trainingUsable = trainingResults.filter((result) => result.effect?.available)
  const trainingMeanEffect = trainingUsable.length
    ? trainingUsable.reduce((sum, result) => sum + (result.effect?.effectSize || 0), 0) / trainingUsable.length
    : null

  return (
    <div className="page board-page decision-page">
      <PageHeader
        eyebrow="DECISION DESK"
        title="赛训决策台"
        subtitle="先把值得复盘的问题挑出来，再回到对局证据。所有「为什么输」都是候选事件，不宣称因果。"
        actions={<>
          <button type="button" className="btn" onClick={refresh}><Icon name="refresh" />刷新</button>
          <button type="button" className="btn" onClick={() => void window.kpl.openExternal(baseUrl)}>打开工作台 <Icon name="external" /></button>
        </>}
      />

      <CoverageBar coverage={coverage} />

      <FilterBar
        catalog={catalog}
        filters={filters}
        onChange={(patch) => setFilters((current) => ({ ...current, ...patch }))}
        onReset={() => setFilters(EMPTY_FILTERS)}
      />

      <BriefingBoard
        data={briefingQuery.data}
        loading={briefingQuery.isLoading}
        error={briefingQuery.isError ? briefingQuery.error : null}
        onRetry={() => void briefingQuery.refetch()}
        onOpen={openBriefingItem}
      />

      <DecisionTabBar tab={tab} onChange={selectTab} />

      {tab === 'review' ? (
        <>
          <section className="card decision-toolbar-card">
            <div className="decision-toolbar-body">
              <label className="decision-field">
                <span>对局</span>
                <select value={reviewGame} onChange={(event) => selectGame(event.target.value)} aria-label="选择复盘对局">
                  {games.map((game) => (
                    <option value={game.id} key={game.id}>
                      {game.label || game.id} · {resultText(game.result)}
                    </option>
                  ))}
                </select>
              </label>
              {reviewGameInfo ? (
                <span className="decision-toolbar-meta">
                  {reviewGameInfo.date || '日期未知'} · {reviewGameInfo.opponent || '对手待命名'} · {fmtDuration(reviewGameInfo.duration)} · 回放{reviewGameInfo.hasEconomy ? '含经济点' : '缺经济点'}
                </span>
              ) : null}
              <Link className="btn btn-sm" to={matchPath(reviewGame)}>打开单局复盘 <Icon name="arrow" /></Link>
              <span className="board-muted">时间轴与关键链联动：点事件标记跳到对应链卡。</span>
            </div>
          </section>

          <AnalysisSection
            title="经济差时间轴"
            note={reviewGameInfo ? `${reviewGameInfo.label || reviewGame} · 我方视角；阴影为候选损失窗口，可点标记跳到链卡。` : '我方视角经济差'}
          >
            {lossQuery.isLoading ? <LoadingBlock label="读取经济曲线与候选事件" />
              : lossQuery.isError ? <ErrorState error={lossQuery.error} onRetry={() => void lossQuery.refetch()} />
                : !loss?.available ? <BoardEmpty title="这一局没有可用的经济时间轴">{loss?.reason || '缺官方回放或经济采样。'}</BoardEmpty>
                  : (
                    <EconomyTimeline
                      points={timelinePoints}
                      duration={lossGame?.duration ?? reviewGameInfo?.duration}
                      approx
                      events={timelineEvents}
                      windows={timelineWindows}
                      selectedId={selectedChain !== null ? `chain-${selectedChain}` : null}
                      onPickEvent={pickTimelineEvent}
                      note={loss?.note}
                      empty="这一局的经济采样点不足 2 个，暂不画曲线。"
                    />
                  )}
          </AnalysisSection>

          <AnalysisSection
            title={`关键链候选 · ${lossChains.length} 段`}
            note="按经济损失窗口挑出的候选事件：只说明同期发生了什么，不证明因果。"
          >
            {lossQuery.isLoading ? <LoadingBlock label="整理候选事件" />
              : lossQuery.isError ? <ErrorState error={lossQuery.error} onRetry={() => void lossQuery.refetch()} />
                : !loss?.available ? <BoardEmpty title="当前范围没有失利链">{loss?.reason || '缺经济点或没有达到阈值的负向窗口。'}</BoardEmpty>
                  : lossChains.length ? (
                    <div className="decision-chain-grid">
                      {lossChains.map((chain, index) => (
                        <ChainCard
                          key={`chain-${index}`}
                          chain={chain}
                          index={index}
                          game={chain.game || reviewGame}
                          active={selectedChain === index}
                          onSelect={() => setSelectedChain(index)}
                        />
                      ))}
                    </div>
                  ) : <BoardEmpty title="这一局没有达到阈值的损失窗口">经济差没有出现显著下滑，或者缺经济采样。</BoardEmpty>}
          </AnalysisSection>

          <AnalysisSection
            title="优势保持与回撤"
            note="最大领先、峰值后回撤、领先时长与首次兑现时间；不足 10 局只做观察，不给稳定预测。"
          >
            {advantageQuery.isLoading ? <LoadingBlock label="计算优势保持指标" />
              : advantageQuery.isError ? <ErrorState error={advantageQuery.error} onRetry={() => void advantageQuery.refetch()} />
                : !advantage?.available ? <BoardEmpty title="当前范围没有可用的优势分析">{advantage?.reason || '缺胜负面板或经济点。'}</BoardEmpty>
                  : (
                    <>
                      <StatGrid items={[
                        { label: '最大领先', value: signed(advantageGame?.maxLead), note: num(advantageGame?.maxLeadAt) !== null ? `首次见顶 ≈${fmtDuration(advantageGame?.maxLeadAt)}` : '本队视角最高经济差', tone: 'own' },
                        { label: '峰值后回撤', value: number(advantageGame?.drawdown), note: '从最高点回落到最低点（幅度，不带正负）', tone: 'foe' },
                        { label: '领先时长', value: fmtDuration(advantageGame?.leadDurationSec), note: '经济差 ≥ +500 的累计时长' },
                        { label: '首次兑现', value: num(advantageGame?.conversionSec) === null ? '—' : fmtDuration(advantageGame?.conversionSec), note: '领先≥1000 到下一个我方资源/塔' },
                        { label: '10 分钟经济差', value: signed(advantageGame?.leadAt10), note: '不足 10 分钟的局不给该指标' },
                        { label: '结局', value: advantageGame?.comeback ? '被翻盘' : resultText(advantageGame?.result), note: advantageGame?.comeback ? '曾领先 ≥1000 且最终告负' : '描述性结果，不评价指挥' }
                      ]} />
                      <div className="decision-summary-line">
                        <span>曾领先 ≥1000：{number(advantage.summary?.ledGames)} 局</span>
                        <span>
                          其中翻盘：{number(advantage.summary?.comebacks)} 局 · 翻盘率 {percent(advantage.summary?.comebackRate)}
                          {num(advantage.summary?.comebackCiLow) !== null || num(advantage.summary?.comebackCiHigh) !== null || advantage.summary?.comebackCi
                            ? `（Wilson ${formatCi(advantage.summary?.comebackCi, advantage.summary?.comebackCiLow, advantage.summary?.comebackCiHigh)}）`
                            : ''}
                        </span>
                        <span>平均最大回撤：{number(advantage.summary?.avgDrawdown)}</span>
                        <span>平均兑现：{fmtDuration(advantage.summary?.avgConversionSec)}</span>
                        {advantage.summary?.enough === false ? <span className="decision-sample-badge is-warn">样本不足（n={number(advantage.summary?.ledGames)}）</span> : null}
                      </div>
                      <div className="board-grid-2 decision-split">
                        <div>
                          <h3 className="decision-subtitle">10 分钟分桶</h3>
                          {(advantage.buckets || []).length ? (
                            <div className="decision-table-wrap">
                              <table className="decision-table">
                                <thead>
                                  <tr><th>分桶</th><th>n</th><th>胜</th><th>胜率</th><th>样本</th></tr>
                                </thead>
                                <tbody>
                                  {(advantage.buckets || []).map((bucket, index) => (
                                    <tr key={`${bucket.bucket || bucket.label || index}`}>
                                      <td>{bucket.bucket || bucket.label || `${number(bucket.low)} ~ ${number(bucket.high)}`}</td>
                                      <td>{number(bucket.n)}</td>
                                      <td>{number(bucket.wins)}</td>
                                      <td>{percent(bucket.winRate)}</td>
                                      <td>{bucket.enough === false ? <span className="decision-sample-badge is-warn">样本不足</span> : '可用'}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : <p className="board-muted">当前范围没有 10 分钟分桶样本。</p>}
                        </div>
                        <div>
                          <h3 className="decision-subtitle">回撤排行</h3>
                          {drawdownRows.length ? (
                            <div className="decision-table-wrap">
                              <table className="decision-table">
                                <thead>
                                  <tr><th>对局</th><th>结果</th><th>最大领先</th><th>回撤</th><th>翻盘</th></tr>
                                </thead>
                                <tbody>
                                  {drawdownRows.map((game, index) => {
                                    const id = game.id || game.game || ''
                                    return (
                                      <tr
                                        key={`${id}-${index}`}
                                        className={id === reviewGame ? 'is-active' : ''}
                                        tabIndex={0}
                                        onClick={() => id && selectGame(id)}
                                        onKeyDown={(event) => { if (event.key === 'Enter' && id) selectGame(id) }}
                                      >
                                        <td>{game.label || id || '—'}</td>
                                        <td><span className={`board-tag tone-${resultTagTone(game.result)}`}>{resultText(game.result)}</span></td>
                                        <td>{signed(game.maxLead)}</td>
                                        <td>{number(game.drawdown)}</td>
                                        <td>{game.comeback ? <span className="board-tag tone-warn">被翻盘</span> : '—'}</td>
                                      </tr>
                                    )
                                  })}
                                </tbody>
                              </table>
                            </div>
                          ) : <p className="board-muted">当前范围没有可算回撤的对局。</p>}
                        </div>
                      </div>
                      <p className="decision-chart-note">{advantage.note || '经济点约 30 秒一个；回撤与兑现时间为近似值。'}</p>
                    </>
                  )}
          </AnalysisSection>

          <AnalysisSection
            title="经济分位带（胜 / 负 / 全部）"
            note="按分钟插值我方经济差的分位；n=0 的档不画，样本数在图例里。"
          >
            {advantageQuery.isLoading ? <LoadingBlock label="汇总分位带" />
              : advantageQuery.isError ? <ErrorState error={advantageQuery.error} onRetry={() => void advantageQuery.refetch()} />
                : !advantage?.available ? <BoardEmpty title="当前范围没有可用的分位带">{advantage?.reason || '缺胜负面板或经济点。'}</BoardEmpty>
                  : (
                    <BandChart
                      series={bandSeries}
                      note={advantage.note}
                      empty="当前范围的胜局/负局样本还不足以画分位带。"
                    />
                  )}
          </AnalysisSection>

          <AnalysisSection
            title="团战执行与到位"
            note="按我方视角：开局 3 秒内到达人数差、击杀交换与成员到位延迟；只做复盘描述。"
          >
            {fightsQuery.isLoading ? <LoadingBlock label="读取团战明细" />
              : fightsQuery.isError ? <ErrorState error={fightsQuery.error} onRetry={() => void fightsQuery.refetch()} />
                : !fights?.available ? <BoardEmpty title="这一局没有可复盘的团战">{fights?.reason || '缺团战段或参战时间。'}</BoardEmpty>
                  : (
                    <>
                      <div className="decision-summary-line">
                        <span>分析团战：{number(fightSummary?.fights)} 场</span>
                        <span>平均到位延迟：{num(fightSummary?.avgArrivalLagSec) === null ? '—' : `${number(fightSummary?.avgArrivalLagSec, 1)} 秒`}</span>
                        <span>迟到率：{percent(fightSummary?.lateJoinRate)}</span>
                        <span>先手击杀：我方 {number(fightSummary?.firstKiller?.own)} / 对手 {number(fightSummary?.firstKiller?.enemy)}</span>
                        <span>beginner 标记：我方 {number(fightSummary?.beginner?.own)} / 对手 {number(fightSummary?.beginner?.enemy)}</span>
                        {fightSummary?.wipeSides ? <span>团灭：我方 {number(fightSummary.wipeSides.own)} 次 / 对手 {number(fightSummary.wipeSides.enemy)} 次</span> : null}
                      </div>
                      {fightSummary?.firstArrivalNote ? (
                        <p className="decision-chart-note">先到/先手口径：{fightSummary.firstArrivalNote}</p>
                      ) : null}
                      <div className="decision-fight-layout">
                        <div className="decision-fight-list">
                          <h3 className="decision-subtitle">损失优先团战</h3>
                          {fightRows.length ? (
                            <>
                              <div className="decision-table-wrap">
                                <table className="decision-table decision-fight-table">
                                  <thead>
                                    <tr><th>时间</th><th>参战 / 人数差</th><th>击杀差</th><th>结果</th></tr>
                                  </thead>
                                  <tbody>
                                    {fightRows.map((row, index) => {
                                      const id = String(row.fightId ?? index)
                                      const selected = fights?.selected?.fightId !== undefined && String(fights.selected.fightId) === String(row.fightId)
                                      const advance = num(row.advStart)
                                      const killDiff = num(row.killDiff)
                                      return (
                                        <tr
                                          key={`${id}-${index}`}
                                          className={selected ? 'is-active' : ''}
                                          tabIndex={0}
                                          onClick={() => setFightId(id)}
                                          onKeyDown={(event) => { if (event.key === 'Enter') setFightId(id) }}
                                        >
                                          <td className="decision-time">{row.timeLabel || fmtDuration(row.startSec)}</td>
                                          <td>
                                            <span>我方 {number(row.ownParticipants)} × 对手 {number(row.enemyParticipants)}</span>
                                            {advance === null ? null : (
                                              <small className={`decision-adv ${advance < 0 ? 'is-foe' : advance > 0 ? 'is-own' : ''}`}>{signed(advance)} 人</small>
                                            )}
                                          </td>
                                          <td>
                                            {killDiff === null
                                              ? '0 击杀'
                                              : <><span>{number(row.ownKills)} : {number(row.enemyKills)}</span><small className={killDiff > 0 ? 'is-own' : killDiff < 0 ? 'is-foe' : ''}>{signed(killDiff)}</small></>}
                                          </td>
                                          <td>{row.won === null || row.won === undefined ? '—' : row.won ? '胜' : '负'}</td>
                                        </tr>
                                      )
                                    })}
                                  </tbody>
                                </table>
                              </div>
                              {fightRowsAll.length > 6 ? (
                                <button type="button" className="btn btn-sm decision-more" onClick={() => setShowAllFights((value) => !value)}>
                                  {showAllFights ? `收起，只看最伤 6 场` : `显示全部 ${Math.min(12, fightRowsAll.length)} 场`}
                                </button>
                              ) : null}
                            </>
                          ) : <p className="board-muted">当前范围没有可列出的团战。</p>}
                        </div>
                        <div className="decision-fight-arrival">
                          <h3 className="decision-subtitle">本场到位（损失最优先）</h3>
                          <ArrivalBars items={fightArrivalItems} empty="没有可展示的成员到位明细。" />
                          {(fights?.selected?.missingParticipants || 0) > 0 ? (
                            <p className="decision-chart-note is-warn">有 {number(fights?.selected?.missingParticipants)} 名参战者缺少参战时间，未补成 0。</p>
                          ) : null}
                        </div>
                        {openingGroups.length ? (
                          <div className="decision-fight-buckets">
                            <h3 className="decision-subtitle">开局人数差 → 团战结果</h3>
                            <div className="decision-table-wrap">
                              <table className="decision-table">
                                <thead>
                                  <tr><th>场景</th><th>场次</th><th>胜</th><th>胜率</th><th>样本</th></tr>
                                </thead>
                                <tbody>
                                  {openingGroups.map((group) => (
                                    <tr key={group.label}>
                                      <td>{group.label}</td>
                                      <td>{number(group.n)}</td>
                                      <td>{number(group.wins)}</td>
                                      <td>{percent(group.winRate)}</td>
                                      <td>{group.enough ? '可用' : <span className="decision-sample-badge is-warn">样本不足</span>}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        ) : null}
                      </div>
                      <p className="decision-chart-note">{fights.note || '团战人数差为开始 3 秒内的到达人数；迟到指开始 5 秒后才到。'}</p>
                    </>
                  )}
          </AnalysisSection>
        </>
      ) : null}

      {tab === 'prep' ? (
        <>
          <div className="decision-filter-bar">
            <label className="decision-field">
              <span>对手</span>
              <select value={prepOpponent} onChange={(event) => setPrepOpponent(event.target.value)} aria-label="选择对手">
                <option value="">全部对手</option>
                {opponents.map((opponent) => (
                  <option value={opponent.id} key={opponent.id}>
                    {opponent.name || opponent.id}（回放 {number(opponent.replayGames)} 局）
                  </option>
                ))}
              </select>
            </label>
            <label className="decision-field">
              <span>分路</span>
              <select value={prepLane} onChange={(event) => setPrepLane(event.target.value)} aria-label="选择分路">
                <option value="">全部分路</option>
                {PLAYER_LANES.map((lane) => <option value={lane} key={lane}>{lane}</option>)}
              </select>
            </label>
            {selectedOpponent ? (
              <span className={`decision-sample-badge${(selectedOpponent.replayGames || 0) < 3 ? ' is-warn' : ''}`}>
                该对手回放 {number(selectedOpponent.replayGames)} 局
              </span>
            ) : null}
            <span className="board-muted">只统计平台收录的回放，不能推断对手全部习惯。</span>
          </div>

          {openingQuery.isLoading ? <LoadingBlock label="读取开局位置与路线" />
            : openingQuery.isError ? <ErrorState error={openingQuery.error} onRetry={() => void openingQuery.refetch()} />
              : !opening?.available ? <BoardEmpty title="当前范围没有可用的开局观察">{opening?.reason || '缺位置采样（positions.json）。'}</BoardEmpty>
                : (
                  <>
                    {(opening.selected?.enough === false || (selectedOpponent && (selectedOpponent.replayGames || 0) < 3)) ? (
                      <div className="board-banner">
                        该对手目前只有 {number(opening.selected?.games ?? selectedOpponent?.replayGames)} 局回放：下面是单局路线观察，不输出固定开局套路。
                      </div>
                    ) : null}
                    <div className="decision-summary-line">
                      <span>路线簇：{number(opening.routes?.length)} 个</span>
                      <span>本批对局：{number(opening.coverage?.games)} 局 · 有位置 {number(opening.coverage?.positionGames)} 局</span>
                      <span>热区采样：{number(opening.heat?.total)} 点 · {number(opening.heat?.games)} 局</span>
                      <span>坐标：{openingCalibrated ? '已定标' : '未定标（相对坐标）'}</span>
                      {opening.selected?.games !== undefined && opening.selected.games < 3
                        ? <span className="decision-sample-badge is-warn">样本不足，仅单局观察</span>
                        : null}
                    </div>
                    <AnalysisSection
                      title={`开局热区（0–4 分钟 · ${opening.filters?.side === 'enemy' ? '对手' : '我方'}视角）`}
                      note="底图为 20×20 位置计数，折线为路线簇的代表路线；点路线卡可在地图上高亮。"
                    >
                      <div className="decision-heat-layout">
                        <OpeningHeat
                          cells={heatCells}
                          max={num(opening.heat?.max) ?? undefined}
                          routes={heatRoutes}
                          highlightId={prepRoute}
                          calibrated={openingCalibrated}
                          caption={!openingCalibrated
                            ? '坐标未定标：位置为回放相对坐标并归一化到 0–1，只用于同批对局之间的相对比较。'
                            : '坐标按本批位置分位定标；九宫格只是方位描述，不代表草丛或视野。'}
                          empty="这一批对局缺少可用的位置采样，暂不画热区。"
                        />
                        <div className="decision-route-list">
                          {openingRoutes.length ? openingRoutes.map((route, index) => {
                            const routeId = `route-${index}`
                            const active = prepRoute === routeId
                            const count = num(route.count) ?? 0
                            const points = routePoints(route)
                            return (
                              <button
                                type="button"
                                key={routeId}
                                className={`decision-route-card${active ? ' is-active' : ''}`}
                                onClick={() => setPrepRoute(active ? null : routeId)}
                              >
                                <span className="decision-route-head">
                                  <b>{route.lane || '分路未知'}</b>
                                  <span className="board-tag tone-foe">{count} 次</span>
                                  {route.enough === false || count < 3 ? <span className="decision-sample-badge is-warn">样本不足</span> : null}
                                </span>
                                <span className="decision-route-zone">
                                  {route.zoneSequence?.length ? route.zoneSequence.join(' → ') : '路线分区未提供'}
                                </span>
                                {route.representative ? (
                                  <span className="decision-route-meta">
                                    代表路线：{route.representative.name || route.representative.player || '选手'} · {route.representative.hero || '英雄未标注'}
                                    {route.representative.label ? ` · ${route.representative.label}` : ''}
                                  </span>
                                ) : null}
                                <span className="decision-route-meta">
                                  后续首个资源：{route.nextObjective?.name || '—'}
                                  {num(route.nextObjective?.minutes) !== null ? ` · ${number(route.nextObjective?.minutes, 1)} 分` : ''}
                                  {route.nextObjective?.count ? `（${route.nextObjective.count} 局）` : ''}
                                </span>
                                <span className="decision-route-foot">
                                  {points.length ? `路线点 ${points.length} 个` : '无路线折线'} · {active ? '点击取消高亮' : '点击在地图上高亮'}
                                </span>
                              </button>
                            )
                          }) : <BoardEmpty title="没有可展示的路线样本">当前筛选下还没有成簇的路线。</BoardEmpty>}
                        </div>
                      </div>
                      <p className="decision-chart-note">
                        {(opening.notes || []).join(' ') || '仅收录本批回放；每名对手样本不足时只做单局观察。'}
                      </p>
                    </AnalysisSection>
                  </>
                )}
        </>
      ) : null}

      {tab === 'player' ? (
        <>
          <div className="decision-filter-bar">
            <label className="decision-field">
              <span>分路</span>
              <select value={playerLane} onChange={(event) => setPlayerLane(event.target.value)} aria-label="选择分路">
                <option value="">全部分路</option>
                {PLAYER_LANES.map((lane) => <option value={lane} key={lane}>{lane}</option>)}
              </select>
            </label>
            <span className="board-muted">
              经济占比 = 个人 / 本队 5 人合计；伤害占比同理。只用于发现待复核的资源分配，不评价选手。
            </span>
            {resourcePlayers.length > 0 && resourcePlayers.length < 10 ? <span className="decision-sample-badge is-warn">样本不足</span> : null}
          </div>

          {resourceQuery.isLoading ? <LoadingBlock label="读取终局面板资源分配" />
            : resourceQuery.isError ? <ErrorState error={resourceQuery.error} onRetry={() => void resourceQuery.refetch()} />
              : !resource?.available ? <BoardEmpty title="当前范围没有可用的资源分配样本">{resource?.reason || '终局面板缺金币字段。'}</BoardEmpty>
                : (
                  <>
                    <div className="decision-summary-line">
                      <span>选手行：{number(resourcePlayers.length)} 条</span>
                      <span>涉及对局：{number(resource.summary?.games)} 局</span>
                      <span>异常条目：{number(anomalies.length)} 条</span>
                      <span>象限分界：{resource.quadrantBasis === 'fixed' ? '20/20 固定分界' : `中位数（${number(resource.quadrant?.xSplit, 1)} / ${number(resource.quadrant?.ySplit, 1)}）`}</span>
                      {resource.summary?.smallSample ? <span className="decision-sample-badge is-warn">样本不足，仅供观察</span> : null}
                    </div>
                    <AnalysisSection
                      title="经济占比 × 英雄伤害占比"
                      note="中位线按当前样本计算；n<10 时用 20/20 固定分界。悬浮看英雄、GPM、死亡与来源，点击选中。"
                    >
                      <QuadrantChart
                        points={quadrantPoints}
                        xMid={num(resource.quadrant?.xSplit)}
                        yMid={num(resource.quadrant?.ySplit)}
                        selected={selectedPoint}
                        onPick={(id) => setSelectedPoint((current) => current === id ? null : id)}
                        note={resource.note || '只用于发现待复核的资源分配，不评价选手。'}
                        empty="当前筛选没有同时具备经济占比与伤害占比的样本。"
                      />
                      {selectedPlayer ? (
                        <div className="decision-player-detail">
                          <div>
                            <b>{selectedPlayer.name || selectedPlayer.playerId || '选手'}</b>
                            <span>{selectedPlayer.lane || '分路未标注'} · {selectedPlayer.hero || '英雄未标注'} · {selectedPlayer.result ? resultText(selectedPlayer.result) : '结果未知'}</span>
                          </div>
                          <div>
                            <span>经济占比 {percent(selectedPlayer.goldShare)}</span>
                            <span>伤害占比 {percent(selectedPlayer.heroDamageShare)}</span>
                            <span>GPM {number(selectedPlayer.gpm, 1)}</span>
                            <span>死亡 {number(selectedPlayer.deaths)}</span>
                            <span>推塔 {number(selectedPlayer.towerDamage)}</span>
                            <span>象限 {selectedPlayer.quadrant || '—'}</span>
                          </div>
                          {selectedPlayer.seq ? <Link className="btn btn-sm" to={matchPath(selectedPlayer.seq)}>打开这一局 <Icon name="arrow" /></Link> : null}
                        </div>
                      ) : null}
                    </AnalysisSection>

                    <AnalysisSection
                      title={`异常清单 · ${anomalies.length} 条`}
                      note="只列「高经济低输出」或「发育路死亡偏多」的条目；不排名、不评价选手。"
                    >
                      {anomalies.length ? (
                        <div className="decision-anomaly-list">
                          {anomalies.map((anomaly, index) => (
                            <div className="decision-anomaly" key={`${anomaly.seq || '-'}-${anomaly.playerId || anomaly.name || index}`}>
                              <div className="decision-anomaly-head">
                                <b>{anomaly.name || anomaly.playerId || '选手'}</b>
                                <span>{anomaly.lane || '分路未标注'} · {anomaly.hero || '英雄未标注'}</span>
                                <span className="board-tag tone-warn">{anomaly.kind?.includes('death') ? '发育路死亡' : '高经济低输出'}</span>
                              </div>
                              <p>{anomaly.text || '—'}</p>
                              <div className="decision-anomaly-foot">
                                <span>{anomaly.date || '日期未知'} · {anomaly.opponentName || '对手待命名'} · {anomaly.result ? resultText(anomaly.result) : '结果未知'}</span>
                                {anomaly.seq ? <Link className="card-link" to={matchPath(anomaly.seq)}>回到对局 <Icon name="arrow" /></Link> : null}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : <BoardEmpty title="当前范围没有达到复核线的条目">高经济低输出与发育路死亡都未触发复核线。</BoardEmpty>}
                    </AnalysisSection>

                    <AnalysisSection
                      title="分路均值与效率"
                      note="分路均值只看当前筛选；经济→输出 = 英雄伤害占比 / 经济占比，用于横向看分路职责差异。"
                    >
                      <div className="decision-table-wrap">
                        <table className="decision-table">
                          <thead>
                            <tr>
                              <th>分路</th><th>n</th><th>经济占比</th><th>伤害占比</th><th>推塔占比</th>
                              <th>控制占比</th><th>治疗占比</th><th>死亡</th><th>GPM</th><th>经济→输出</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(resource.byLane || []).map((row) => {
                              const efficiency = (resource.efficiency || []).find((item) => item.lane === row.lane)
                              return (
                                <tr key={row.lane || '未知'}>
                                  <td>{row.lane || '分路未标注'}</td>
                                  <td>{number(row.n)}</td>
                                  <td>{percent(row.goldShare)}</td>
                                  <td>{percent(row.heroDamageShare)}</td>
                                  <td>{percent(row.towerShare)}</td>
                                  <td>{percent(row.controlShare)}</td>
                                  <td>{percent(row.healShare)}</td>
                                  <td>{number(row.deaths, 1)}</td>
                                  <td>{number(row.gpm, 1)}</td>
                                  <td>{number(efficiency?.ratio, 2)}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                      <p className="decision-chart-note">
                        口径：经济=营地 battleStats.money；英雄伤害=battleStats.totalHeroHurtCnt；推塔=buildingDamage；
                        总伤害与英雄伤害分开保留，不混用。{resource.efficiencyNote || ''}
                      </p>
                    </AnalysisSection>
                  </>
                )}
        </>
      ) : null}

      {tab === 'training' ? (
        <>
          <div className="board-banner">
            C 级：训练目标绑定与复盘问题联动尚未打通；这里只做干预前后的描述，不宣称因果。
          </div>
          {trainingQuery.isLoading ? <LoadingBlock label="读取训练效果" />
            : trainingQuery.isError ? <ErrorState error={trainingQuery.error} onRetry={() => void trainingQuery.refetch()} />
              : (
                <>
                  <StatGrid items={[
                    { label: '干预记录', value: number(trainingResults.length), note: '训练目标' },
                    { label: '可对比', value: number(trainingUsable.length), note: '两侧样本 ≥ 5 人次' },
                    { label: '平均效应量', value: trainingMeanEffect === null ? '—' : number(trainingMeanEffect, 2), note: 'Cohen’s d · 描述性对比', tone: 'accent' },
                    { label: '最近一条', value: trainingResults[0]?.start_date || '—', note: trainingResults[0]?.goal || '' }
                  ]} />
                  <AnalysisSection
                    title="干预前后对照"
                    note="每侧至少 5 条有效人次才计算效应量；样本不足会写明原因。"
                    action={<Link className="card-link" to="/training/effect">训练效果页 <Icon name="arrow" /></Link>}
                  >
                    {trainingResults.length ? (
                      <div className="decision-effect-list">
                        {trainingResults.map((result) => {
                          const effect = result.effect
                          return (
                            <article className="decision-effect-card" key={result.id}>
                              <div className="decision-effect-head">
                                <span>{result.start_date || '日期未知'}</span>
                                <small>{effect?.label || result.metric || '观察指标'}</small>
                                <b className={`board-tag tone-${effect?.available ? 'own' : 'muted'}`}>{effect?.available ? '可对比' : '样本不足'}</b>
                              </div>
                              <h3>{result.goal}</h3>
                              {result.intervention ? <p className="decision-effect-method">{result.intervention}</p> : null}
                              {effect?.available ? (
                                <div className="decision-effect-values">
                                  <span><small>干预前</small><b>{number(effect.preMean, 2)}</b><em>{number(effect.nPre)} 人次</em></span>
                                  <i>→</i>
                                  <span><small>干预后</small><b>{number(effect.postMean, 2)}</b><em>{number(effect.nPost)} 人次</em></span>
                                  <span><small>效应量 d</small><b>{number(effect.effectSize, 2)}</b><em>描述性对比</em></span>
                                </div>
                              ) : <p className="board-muted">{effect?.reason || '样本不足，暂不计算。'}</p>}
                              {result.review ? <p className="decision-effect-review">{result.review}</p> : null}
                            </article>
                          )
                        })}
                      </div>
                    ) : (
                      <BoardEmpty title="还没有训练干预记录">
                        工作台登记训练目标后，系统会把干预前后各至少 5 条本队营地记录放在一起比较。
                      </BoardEmpty>
                    )}
                    <p className="decision-chart-note">{trainingQuery.data?.dateNote || '只有来源包含完整年份的营地记录才参与前后对比；缺年份不会自行补全。'}</p>
                  </AnalysisSection>
                </>
              )}
        </>
      ) : null}

      <div className="board-foot">
        口径：{catalog.notes?.join(' ')} 所有「为什么输」都是候选事件，不宣称因果；n 永远可见，小样本只做观察。
      </div>
    </div>
  )
}

/* ── 页面组件 ───────────────────────────────────────────────────── */

function CoverageBar({ coverage }: { coverage: DecisionCoverage }) {
  const dateRange = coverage.dateRange || []
  const items = [
    { label: '完整回放', value: `${number(coverage.pairedGames ?? coverage.games)} 局`, note: `回放文件 ${number(coverage.replayGames)} 局` },
    { label: '终局面板', value: `${number(coverage.panelGames)} 局`, note: `${number(coverage.panelRows)} 行 · 逐人终局` },
    { label: '坐标', value: coverage.calibrated ? '已定标' : '未定标', note: coverage.calibrationNote || '位置按回放相对单位' },
    { label: '胜负', value: `${number(coverage.wins)} 胜 ${number(coverage.losses)} 负`, note: `可判胜负 ${number(coverage.withResult)} 局` },
    { label: '数据范围', value: dateRange.length ? `${dateRange[0]} → ${dateRange[dateRange.length - 1]}` : '—', note: `团战 ${number(coverage.fights)} 场 · 死亡 ${number(coverage.deaths)} 次` },
    { label: '位置采样', value: `${number(coverage.positionGames)} 局`, note: `对手 ${number(coverage.opponents?.total)} 个 · 3 局以上 ${number(coverage.opponents?.with3Games)} 个` }
  ]
  return (
    <section className="decision-coverage" aria-label="数据覆盖">
      {items.map((item) => (
        <div className="decision-cover-item" key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          <small>{item.note}</small>
        </div>
      ))}
    </section>
  )
}

function FilterBar({
  catalog,
  filters,
  onChange,
  onReset
}: {
  catalog: DecisionCatalog
  filters: FilterState
  onChange: (patch: Partial<FilterState>) => void
  onReset: () => void
}) {
  const opponents = catalog.opponents || []
  const dates = catalog.coverage?.dateRange || []
  const active = Boolean(filters.opponent || filters.result || filters.from || filters.to)
  return (
    <div className="decision-filter-bar">
      <label className="decision-field">
        <span>对手</span>
        <select value={filters.opponent} onChange={(event) => onChange({ opponent: event.target.value })} aria-label="对手筛选">
          <option value="">全部对手</option>
          {opponents.map((opponent) => (
            <option value={opponent.id} key={opponent.id}>
              {opponent.name || opponent.id}{typeof opponent.replayGames === 'number' ? ` · ${opponent.replayGames} 局回放` : ''}
            </option>
          ))}
        </select>
      </label>
      <label className="decision-field">
        <span>结果</span>
        <select value={filters.result} onChange={(event) => onChange({ result: event.target.value })} aria-label="结果筛选">
          <option value="">全部结果</option>
          <option value="win">胜</option>
          <option value="loss">负</option>
        </select>
      </label>
      <label className="decision-field">
        <span>从</span>
        <input
          type="date"
          value={filters.from}
          min={dates[0] || undefined}
          max={dates[1] || undefined}
          onChange={(event) => onChange({ from: event.target.value })}
          aria-label="开始日期"
        />
      </label>
      <label className="decision-field">
        <span>到</span>
        <input
          type="date"
          value={filters.to}
          min={dates[0] || undefined}
          max={dates[1] || undefined}
          onChange={(event) => onChange({ to: event.target.value })}
          aria-label="结束日期"
        />
      </label>
      {active ? <button type="button" className="btn btn-sm" onClick={onReset}>清除筛选</button> : null}
      <span className="board-muted">筛选同时作用于问题卡与各分析页签；数据来自终局面板与官方回放。</span>
    </div>
  )
}

function BriefingBoard({
  data,
  loading,
  error,
  onRetry,
  onOpen
}: {
  data?: DecisionBriefing
  loading: boolean
  error: unknown
  onRetry: () => void
  onOpen: (item: DecisionBriefingItem) => void
}) {
  const items = data?.items || []
  return (
    <section className="decision-briefing" aria-label="今天先看这几件事">
      <div className="decision-briefing-head">
        <div>
          <span className="eyebrow">TODAY</span>
          <h2 className="decision-section-title">今天先看这几件事</h2>
        </div>
        <span className="board-muted">按严重程度排序 · 最多 5 条 · 小样本自动降级并写明限制</span>
      </div>
      {loading ? <LoadingBlock label="正在挑选值得复盘的问题" />
        : error ? <ErrorState error={error} onRetry={onRetry} />
          : !data?.available ? (
            <BoardEmpty title="当前没有可分析的完整回放">
              {data?.reason || '先在采集里关联官方回放与终局面板，这里才会产生问题卡。'}
            </BoardEmpty>
          ) : items.length ? (
            <div className="decision-brief-grid">
              {items.map((item) => (
                <BriefCard key={item.id} item={item} onOpen={() => onOpen(item)} />
              ))}
            </div>
          ) : (
            <div className="decision-brief-empty">
              <b>暂时没有足够证据的问题</b>
              <p>当前数据还不足以形成可行动的问题卡；这里不会硬凑结论。</p>
            </div>
          )}
      {data?.skipped?.length ? (
        <details className="decision-skipped">
          <summary>还有 {data.skipped.length} 项未达到出卡条件</summary>
          <ul>
            {data.skipped.map((item, index) => (
              <li key={`${item.analysis || 'skip'}-${index}`}>
                <b>{item.analysis || '分析'}</b>：{item.reason || '数据不足'}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {data?.note ? <p className="decision-chart-note">{data.note}</p> : null}
    </section>
  )
}

function BriefCard({ item, onOpen }: { item: DecisionBriefingItem; onOpen: () => void }) {
  const severity = ['high', 'medium', 'low'].includes(String(item.severity)) ? String(item.severity) : 'low'
  const n = num(item.n)
  return (
    <article className={`decision-brief-card tone-${severity}`}>
      <span className="decision-brief-sev" aria-hidden="true" />
      <div className="decision-brief-meta">
        <span className={`decision-brief-kind tone-${severity}`}>{KIND_LABEL[item.kind] || item.kind}</span>
        <span className={`decision-brief-confidence tone-${severity}`}>{SEVERITY_LABEL[severity] || severity} · {CONFIDENCE_LABEL[String(item.confidence || '')] || '观察'}</span>
      </div>
      <h3 className="decision-brief-title">{item.title}</h3>
      {item.detail ? <p className="decision-brief-detail">{item.detail}</p> : null}
      <div className="decision-chips">
        {(item.evidence || []).map((evidence, index) => evidence.game ? (
          <Link
            className="decision-chip"
            key={`${evidence.game}-${index}`}
            to={matchPath(evidence.game)}
            title={evidence.text || evidence.label || ''}
          >
            {evidence.label || evidence.game}
            {num(evidence.t) !== null ? ` · ≈${fmtDuration(evidence.t)}` : ''}
          </Link>
        ) : null)}
        {!item.evidence?.length ? <span className="board-muted">这条问题暂时没有关联到单局证据</span> : null}
      </div>
      {item.caveat ? <p className="decision-caveat">{item.caveat}</p> : null}
      <div className="decision-brief-foot">
        <span>
          {n === null ? 'n = —' : `n = ${number(n)}`}
          {n !== null && n < 10 ? <em className="decision-sample-badge is-warn">样本不足</em> : null}
        </span>
        <button type="button" className="btn btn-sm" onClick={onOpen}>查看分析 <Icon name="arrow" /></button>
      </div>
    </article>
  )
}

function ChainCard({
  chain,
  index,
  game,
  active,
  onSelect
}: {
  chain: LossRow
  index: number
  game: string
  active: boolean
  onSelect: () => void
}) {
  const phase = chain.phase || '阶段未知'
  return (
    <article
      id={`decision-chain-${index}`}
      className={`decision-chain-card${active ? ' is-active' : ''}`}
      tabIndex={0}
      role="button"
      onClick={onSelect}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect() } }}
    >
      <div className="decision-chain-head">
        <span className="decision-chain-time">≈{fmtDuration(chain.start)}–{fmtDuration(chain.end)}</span>
        <span className="board-tag tone-warn">{chain.typeLabel || chain.type || '未分类'}</span>
        <span className="decision-chain-phase">{phase}</span>
      </div>
      <h3 className="decision-chain-title">窗口内经济差 {signed(chain.delta)}</h3>
      {chain.candidates?.length ? (
        <ul className="decision-chain-list">
          {chain.candidates.slice(0, 6).map((candidate, candidateIndex) => (
            <li key={candidateIndex}>{candidateText(candidate)}</li>
          ))}
        </ul>
      ) : <p className="board-muted">窗口内没有找到可列出的候选事件，只保留经济损失本身。</p>}
      <div className="decision-chain-foot">
        <span className="board-tag tone-muted">候选事件 · 不证明因果</span>
        {game ? <Link className="card-link" to={matchPath(game)} onClick={(event) => event.stopPropagation()}>回到对局 <Icon name="arrow" /></Link> : null}
      </div>
    </article>
  )
}

function DecisionTabBar({ tab, onChange }: { tab: TabId; onChange: (tab: TabId) => void }) {
  return (
    <nav className="decision-tabs" aria-label="决策台页签">
      {TABS.map((item) => (
        <button
          type="button"
          key={item.id}
          className={`decision-tab${tab === item.id ? ' is-active' : ''}`}
          onClick={() => onChange(item.id)}
          aria-current={tab === item.id ? 'page' : undefined}
        >
          {item.label}
        </button>
      ))}
    </nav>
  )
}

function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="decision-loading" aria-busy="true">
      <i /><i /><i />
      <span>{label}…</span>
    </div>
  )
}
