import { useQuery } from '@tanstack/react-query'
import { api, queryString } from './api'

/**
 * 赛训决策台数据层（/api/decision/*）。
 *
 * 类型按 docs/decision_workbench_contract.md 第 3 节与各报告模块的输出契约编写：
 * - 顶层 always-present 的字段标必需；报告内部可缺省/小样本时给 null 的字段标 optional。
 * - 所有报告在无数据时返回 available=false + reason，不抛 500；页面据此显示原因而不是空图。
 */

const common = {
  staleTime: 30_000,
  refetchOnWindowFocus: false,
  retry: 1
}

/* ── 通用 ─────────────────────────────────────────────────────────── */

export type DecisionSeverity = 'high' | 'medium' | 'low'
export type DecisionConfidence = 'high' | 'medium' | 'low'

export interface DecisionCoverageOpponents {
  total?: number
  replayOpponents?: number
  with3Games?: number
}

export interface DecisionIdentityCoverage {
  playersWithNickname?: number
  namedOpponents?: number
}

export interface DecisionCoverage {
  panelGames?: number
  panelRows?: number
  replayGames?: number
  pairedGames?: number
  games?: number
  withResult?: number
  wins?: number
  losses?: number
  positionGames?: number
  fightGames?: number
  fights?: number
  deaths?: number
  events?: number
  dateRange?: string[]
  calibrated?: boolean
  calibrationNote?: string
  opponents?: DecisionCoverageOpponents
  identity?: DecisionIdentityCoverage
  errors?: number
}

export interface DecisionFiltersApplied {
  game?: string | null
  opponent?: string | null
  from?: string | null
  to?: string | null
  result?: string | null
  side?: string | null
  lane?: string | null
  player?: string | null
  limit?: number | null
}

export interface DecisionEvidence {
  game?: string | null
  label?: string | null
  t?: number | null
  kind?: string | null
  text?: string | null
  start?: number | null
  end?: number | null
  cost?: number | null
}

/* ── catalog ─────────────────────────────────────────────────────── */

export interface DecisionCatalogAnalysis {
  id: string
  name: string
  priority?: string
  level?: string
  layer?: string
  available: boolean
  games?: number
  thresholds?: Record<string, number | number[] | string | boolean>
  note?: string
  link?: string
  emptyReason?: string | null
  caveat?: string
  fields?: string[]
}

export interface DecisionCatalogLayer {
  id: string
  name: string
  source?: string
  games?: number
  rows?: number
  supports?: string[]
  fields?: string[]
  limits?: string
}

export interface DecisionCatalogGame {
  id: string
  label?: string
  date?: string
  opponent?: string | null
  opponentId?: string | null
  ownCamp?: string | null
  result?: string | null
  duration?: number | null
  hasReplay?: boolean
  hasPositions?: boolean
  hasFights?: boolean
  hasEconomy?: boolean
  fights?: number
  deaths?: number
}

export interface DecisionCatalogOpponent {
  id: string
  name?: string
  games?: number
  replayGames?: number
  enough?: boolean
}

export interface DecisionCatalog {
  generatedAt?: string
  coverage: DecisionCoverage
  layers?: DecisionCatalogLayer[]
  analyses?: DecisionCatalogAnalysis[]
  games?: DecisionCatalogGame[]
  opponents?: DecisionCatalogOpponent[]
  notes?: string[]
}

/* ── briefing ────────────────────────────────────────────────────── */

export interface DecisionBriefingItem {
  id: string
  kind: string
  severity: DecisionSeverity | string
  title: string
  detail?: string
  n?: number
  confidence?: DecisionConfidence | string
  caveat?: string
  analysis?: string
  evidence?: DecisionEvidence[]
  link?: string
}

export interface DecisionBriefingSkipped {
  analysis?: string
  reason?: string
}

export interface DecisionBriefingCoverage {
  games?: number
  panelGames?: number
  losses?: number
  calibrated?: boolean
}

export interface DecisionBriefing {
  available: boolean
  reason?: string
  coverage?: DecisionBriefingCoverage
  items?: DecisionBriefingItem[]
  skipped?: DecisionBriefingSkipped[]
  note?: string
}

/* ── loss：失利关键链 ────────────────────────────────────────────── */

export interface DecisionCandidate {
  kind?: string
  type?: string
  label?: string
  text?: string
  name?: string
  player?: string
  hero?: string
  camp?: string
  timeSec?: number | null
  t?: number | null
  delta?: number | null
}

export interface LossPattern {
  type?: string
  typeLabel?: string
  label?: string
  windows?: number
  games?: number
  avgCost?: number | null
  minCost?: number | null
  cost?: number | null
  evidence?: DecisionEvidence[]
}

export interface LossPhaseRow {
  phase?: string
  windows?: number
  games?: number
  avgCost?: number | null
  cost?: number | null
  enough?: boolean
}

export interface LossSummary {
  games?: number
  gamesWithWindows?: number
  economyGames?: number
  windows?: number
  enough?: boolean
  reason?: string | null
  results?: Record<string, number>
  byType?: Record<string, number>
  patterns?: LossPattern[]
  phases?: LossPhaseRow[]
  byPhase?: LossPhaseRow[]
  thresholds?: Record<string, number | number[]>
  losses?: number | null
}

export interface LossRow {
  game?: string
  label?: string
  opponent?: string | null
  opponentId?: string | null
  result?: string | null
  ownCamp?: string | null
  phase?: string
  start?: number | null
  end?: number | null
  startClock?: string | null
  endClock?: string | null
  windowSec?: number | null
  delta?: number | null
  type?: string
  typeLabel?: string
  candidates?: DecisionCandidate[]
  evidence?: DecisionEvidence[]
  confidence?: string
  approx?: boolean
}

export interface LossSeries {
  times?: number[]
  ownDiff?: number[]
  rawDiff?: number[]
  duration?: number | null
  approx?: boolean
}

export interface LossGameDetail {
  id?: string
  game?: string
  label?: string
  date?: string
  start?: string
  opponentId?: string | null
  opponentName?: string | null
  ownCamp?: string | null
  enemyCamp?: string | null
  result?: string | null
  duration?: number | null
  series?: LossSeries | null
  chains?: LossRow[]
  threshold?: number | null
  approx?: boolean
  note?: string
}

export interface LossCoverage {
  games?: number
  economyGames?: number
  skippedGames?: number
  skipped?: { game?: string; label?: string; reason?: string }[]
  windows?: number
  gamesWithWindows?: number
  dateRange?: string[]
  results?: Record<string, number>
  approx?: boolean
}

export interface LossReport {
  available: boolean
  reason?: string | null
  filters?: DecisionFiltersApplied
  summary?: LossSummary
  rows?: LossRow[]
  game?: LossGameDetail | null
  coverage?: LossCoverage
  note?: string
}

/* ── advantage：优势保持与回撤 ───────────────────────────────────── */

export interface AdvantageCi {
  low?: number | null
  high?: number | null
}

export interface AdvantageGameRow {
  game?: string
  id?: string
  label?: string
  date?: string
  opponentId?: string | null
  opponentName?: string | null
  result?: string | null
  ownCamp?: string | null
  duration?: number | null
  samples?: number
  stepSec?: number | null
  maxLead?: number | null
  maxLeadAt?: number | null
  maxLeadAtClock?: string | null
  drawdown?: number | null
  drawdownAt?: number | null
  drawdownAtClock?: string | null
  finalOwnDiff?: number | null
  leadDurationSec?: number | null
  firstLeadAt?: number | null
  firstLeadAtClock?: string | null
  conversionSec?: number | null
  conversionN?: number | null
  postLead2mDelta?: number | null
  comeback?: boolean
  leadAt10?: number | null
  leadAt10Bucket?: string | null
  candidates?: DecisionCandidate[]
  enough?: boolean
  approx?: boolean
}

export interface AdvantageMaxDrawdownGame {
  game?: string
  label?: string
  drawdown?: number | null
  maxLead?: number | null
  maxLeadAt?: number | null
  drawdownAt?: number | null
}

export interface AdvantageSummary {
  games?: number
  ledGames?: number
  comebacks?: number
  comebackRate?: number | null
  comebackCiLow?: number | null
  comebackCiHigh?: number | null
  comebackCi?: AdvantageCi | number[] | null
  comebackRateCiLow?: number | null
  comebackRateCiHigh?: number | null
  enough?: boolean
  reason?: string | null
  avgMaxLead?: number | null
  medianMaxLead?: number | null
  avgDrawdown?: number | null
  avgLeadDurationSec?: number | null
  avgConversionSec?: number | null
  avgPostLead2mDelta?: number | null
  avgLeadAt10?: number | null
  maxDrawdown?: number | null
  maxDrawdownGame?: AdvantageMaxDrawdownGame | null
  counts?: Record<string, number>
  n?: Record<string, number>
  overall?: { n?: number; wins?: number; winRate?: number | null }
  lossThreshold?: number | null
  thresholds?: Record<string, number>
  note?: string
}

export interface BandStat {
  n?: number
  p25?: number | null
  p50?: number | null
  p75?: number | null
}

export interface AdvantageBandPoint {
  minute?: number
  t?: number
  n?: number
  nWin?: number
  nLoss?: number
  nAll?: number
  win?: BandStat | null
  loss?: BandStat | null
  all?: BandStat | null
  /** 兼容只给「全部对局」分位的实现：无 all 分组时读这三个字段。 */
  p25?: number | null
  p50?: number | null
  p75?: number | null
}

export interface AdvantageBucket {
  bucket?: string
  label?: string
  low?: number | null
  high?: number | null
  from?: number | null
  to?: number | null
  n?: number
  wins?: number
  winRate?: number | null
  ci?: AdvantageCi | number[] | null
  ciLow?: number | null
  ciHigh?: number | null
  enough?: boolean
}

export interface AdvantagePathGame {
  game?: string
  label?: string
  firstLeadAt?: number | null
  firstLeadAtClock?: string | null
}

export interface AdvantagePath {
  key?: string
  label?: string
  nextKind?: string
  nextName?: string | null
  tower?: boolean
  result?: string
  sequence?: string[]
  n?: number
  games?: AdvantagePathGame[]
  wins?: number
  rate?: number | null
  enough?: boolean
}

export interface AdvantageCoverage {
  games?: number
  economyGames?: number
  skippedGames?: number
  skipped?: { game?: string; label?: string; reason?: string }[]
  dateRange?: string[]
  results?: Record<string, number>
  samples?: number
  bandsMaxMinute?: number
  approx?: boolean
}

export interface AdvantageReport {
  available: boolean
  reason?: string | null
  filters?: DecisionFiltersApplied
  summary?: AdvantageSummary
  buckets?: AdvantageBucket[]
  bands?: AdvantageBandPoint[]
  games?: AdvantageGameRow[]
  paths?: AdvantagePath[]
  coverage?: AdvantageCoverage
  note?: string
}

/* ── fights：团战执行 ────────────────────────────────────────────── */

export interface FightOpeningBucket {
  advStart?: number
  n?: number
  wins?: number
  winRate?: number | null
  enough?: boolean
}

export interface FightHeatCell {
  x?: number
  y?: number
  count?: number
  ownWins?: number
}

export interface FightHeat {
  cells?: FightHeatCell[]
  max?: number
  skippedKillDiff?: number
}

export interface FightSummary {
  fights?: number
  avgArrivalLagSec?: number | null
  lateJoins?: number
  lateJoinRate?: number | null
  ownParticipants?: number
  firstArrival?: { own?: number; enemy?: number; tie?: number; none?: number }
  firstArrivalNote?: string
  firstKiller?: { own?: number; enemy?: number; none?: number }
  beginner?: { own?: number; enemy?: number; tie?: number; none?: number }
  openingBuckets?: FightOpeningBucket[]
  unbucketedAdvStart?: number
  heat?: FightHeat
  wipes?: number
  wipeSides?: { own?: number; enemy?: number }
  wipeNote?: string
  wipeRows?: FightRow[]
  ownKills?: number
  enemyKills?: number
  note?: string
}

export interface FightMember {
  objId?: string | null
  player?: string | null
  hero?: string | null
  lane?: string | null
  camp?: string | null
  campCode?: string | null
  arrivalLagSec?: number | null
  joinOrder?: number | null
  beginner?: boolean | number | null
  kills?: number
  deaths?: number
  assists?: number
  hurt?: number
  taken?: number
  heal?: number
  hardCtrl?: number
  softCtrl?: number
  beginHP?: number | null
  endHP?: number | null
  ultimates?: number
}

export interface FightArrivalBar {
  player?: string | null
  hero?: string | null
  lane?: string | null
  camp?: string | null
  from?: number | null
  to?: number | null
}

export interface FightRow {
  game?: string
  label?: string
  fightId?: string | number | null
  opponentId?: string | null
  opponentName?: string | null
  result?: string | null
  ownCamp?: string | null
  enemyCamp?: string | null
  phase?: string | null
  timeLabel?: string | null
  startSec?: number | null
  endSec?: number | null
  duration?: number | null
  ownParticipants?: number
  enemyParticipants?: number
  missingParticipants?: number
  avgArrivalLagSec?: number | null
  arrivalDiff?: number | null
  advStart?: number | null
  ownKills?: number
  enemyKills?: number
  killDiff?: number | null
  won?: boolean | null
  lateJoins?: number
  firstSide?: string | null
  /** 首个击杀方（先手）；真实数据里 firstSide/arrivalDiff 无区分度，先手只看这个字段。 */
  firstKillerSide?: 'own' | 'enemy' | null
  beginnerSide?: string | null
}

export interface FightSelected extends FightRow {
  members?: FightMember[]
  /** 每人 { from: 0, to: 到位延迟 }，用于画到位条；缺省时用 members 的 arrivalLagSec 还原。 */
  arrivalBars?: FightArrivalBar[]
}

export interface FightReport {
  available: boolean
  reason?: string
  filters?: DecisionFiltersApplied
  summary?: FightSummary | null
  rows?: FightRow[]
  selected?: FightSelected | null
  selectedReason?: string | null
  coverage?: DecisionCoverage
  note?: string
}

/* ── opening：对手开局路线与热区 ─────────────────────────────────── */

export interface OpeningOpponent {
  id?: string
  name?: string
  replayGames?: number
  positionGames?: number
  games?: number
  enough?: boolean
}

export interface OpeningSelected {
  id?: string | null
  opponentId?: string
  opponent?: string | null
  name?: string | null
  label?: string
  replayGames?: number
  positionGames?: number
  games?: number
  enough?: boolean
  note?: string
}

export interface OpeningNextObjective {
  type?: string
  name?: string
  minutes?: number | null
  t?: number | null
  count?: number
  games?: number
  enough?: boolean
  options?: OpeningNextObjective[]
}

export type OpeningRoutePoint =
  | [number, number, number]
  | [number, number]
  | { t?: number; x?: number; y?: number }

export interface OpeningRouteRepresentative {
  game?: string
  label?: string
  player?: string
  hero?: string
  name?: string
  lane?: string
  times?: number[]
  /** 归一化到 0–1 的路线坐标（已定标时为地图宽度比例）。 */
  points?: [number, number][]
}

export interface OpeningLaneRow {
  lane?: string
  routes?: number
  clusters?: number
  enough?: boolean
}

export interface OpeningRoute {
  lane?: string
  side?: string
  count?: number
  enough?: boolean
  games?: number
  gameIds?: string[]
  avgDistance?: number | null
  representative?: OpeningRouteRepresentative | null
  zoneSequence?: string[]
  zones?: Record<string, number>
  nextObjective?: OpeningNextObjective | null
  points?: OpeningRoutePoint[]
  route?: OpeningRoutePoint[]
}

export interface OpeningHeatCell {
  x?: number
  y?: number
  n?: number
}

export interface OpeningHeat {
  cells?: OpeningHeatCell[]
  max?: number
  grid?: number
  games?: number
  total?: number
  unit?: string
  calibrated?: boolean
  bounds?: number[] | null
}

export interface OpeningCoverage {
  games?: number
  positionGames?: number
  replayGamesAll?: number
  routes?: number
  skippedRoutes?: number
  clusters?: number
  sampleUntilSec?: number
  sampleStepSec?: number
  clusterThreshold?: number
  minCluster?: number
  calibrated?: boolean
  relative?: boolean
  heatPoints?: number
  opponents?: number
  dateRange?: string[]
}

export interface OpeningReport {
  available: boolean
  reason?: string
  filters?: DecisionFiltersApplied
  opponents?: OpeningOpponent[]
  selected?: OpeningSelected | null
  lanes?: OpeningLaneRow[]
  routes?: OpeningRoute[]
  heat?: OpeningHeat | null
  coverage?: OpeningCoverage
  notes?: string[]
  note?: string
}

/* ── resource：资源分配 ─────────────────────────────────────────── */

export interface ResourcePlayer {
  seq?: string
  game?: string
  date?: string
  start?: string
  playerId?: string
  name?: string | null
  lane?: string | null
  hero?: string | null
  side?: string | null
  result?: string | null
  won?: boolean | null
  opponentId?: string | null
  opponentName?: string | null
  minutes?: number | null
  gold?: number | null
  heroDamage?: number | null
  damage?: number | null
  taken?: number | null
  towerDamage?: number | null
  control?: number | null
  heal?: number | null
  jungleGold?: number | null
  cs?: number | null
  deaths?: number | null
  participation?: number | null
  grade?: number | null
  gpm?: number | null
  goldShare?: number | null
  heroDamageShare?: number | null
  towerShare?: number | null
  controlShare?: number | null
  healShare?: number | null
  jungleShare?: number | null
  goldDamageGap?: number | null
  quadrant?: string | null
  quadrantFlag?: boolean
}

export interface ResourceAnomaly {
  kind?: string
  text?: string
  gap?: number | null
  seq?: string
  date?: string
  start?: string
  opponentName?: string | null
  result?: string | null
  playerId?: string | null
  name?: string | null
  lane?: string | null
  hero?: string | null
  goldShare?: number | null
  heroDamageShare?: number | null
  deaths?: number | null
  gold?: number | null
  heroDamage?: number | null
  gpm?: number | null
  quadrant?: string | null
}

export interface ResourceLaneRow {
  lane?: string
  n?: number
  games?: number
  ratio?: number | null
  note?: string
  goldShare?: number | null
  heroDamageShare?: number | null
  towerShare?: number | null
  controlShare?: number | null
  healShare?: number | null
  jungleShare?: number | null
  deaths?: number | null
  gpm?: number | null
}

export interface ResourceQuadrant {
  x?: string
  y?: string
  xSplit?: number | null
  ySplit?: number | null
  basis?: string
  n?: number
  note?: string
}

export interface ResourceSummary {
  games?: number
  rows?: number
  players?: number
  quadrantFlagCount?: number
  deathAnomalyCount?: number
  anomalyCount?: number
  quadrantBasis?: string
  smallSample?: boolean
  flagLanes?: string[]
  supportLanes?: string[]
  note?: string
}

export interface ResourceCoverage {
  panelGames?: number
  panelGamesEligible?: number
  panelGamesTotal?: number
  rows?: number
  rowsEligible?: number
  rowsTotal?: number
  ownRows?: number
  enemyRows?: number
  rowsWithGold?: number
  gamesWithGold?: number
  unknownLaneRows?: number
  missingFields?: Record<string, number>
  dateRange?: string[]
}

export interface ResourceReport {
  available: boolean
  reason?: string | null
  filters?: DecisionFiltersApplied
  summary?: ResourceSummary
  quadrantBasis?: string
  quadrant?: ResourceQuadrant
  players?: ResourcePlayer[]
  anomalies?: ResourceAnomaly[]
  byLane?: ResourceLaneRow[]
  efficiency?: ResourceLaneRow[]
  efficiencyNote?: string
  metrics?: Record<string, string>
  coverage?: ResourceCoverage
  note?: string
  goldBasis?: string
  damageBasis?: string
  towerBasis?: string
}

/* ── 参数 ───────────────────────────────────────────────────────── */

export interface DecisionRangeParams {
  opponent?: string
  from?: string
  to?: string
  result?: string
}

export interface DecisionBriefingParams extends DecisionRangeParams {
  limit?: number
}

export interface DecisionLossParams extends DecisionRangeParams {
  game?: string
  limit?: number
}

export type DecisionAdvantageParams = DecisionRangeParams

export interface DecisionFightsParams extends DecisionRangeParams {
  game?: string
  side?: string
  limit?: number
}

export interface DecisionOpeningParams extends DecisionRangeParams {
  lane?: string
  side?: string
}

export interface DecisionResourceParams extends DecisionRangeParams {
  lane?: string
  player?: string
  side?: string
}

/* ── hooks ──────────────────────────────────────────────────────── */

export function useDecisionCatalog(baseUrl: string) {
  return useQuery({
    queryKey: ['decision-catalog', baseUrl],
    queryFn: () => api<DecisionCatalog>(baseUrl, '/api/decision/catalog', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useBriefing(baseUrl: string, params: DecisionBriefingParams = {}, active = true) {
  const { opponent = '', from = '', to = '', result = '', limit } = params
  return useQuery({
    queryKey: ['decision-briefing', baseUrl, opponent, from, to, result, limit ?? ''],
    queryFn: () => api<DecisionBriefing>(
      baseUrl,
      `/api/decision/briefing${queryString({ opponent, from, to, result, limit })}`,
      { timeout: 90_000 }
    ),
    enabled: Boolean(baseUrl) && active,
    ...common,
    staleTime: 60_000
  })
}

export function useLoss(baseUrl: string, params: DecisionLossParams = {}, active = true) {
  const { game = '', opponent = '', from = '', to = '', result = '', limit } = params
  return useQuery({
    queryKey: ['decision-loss', baseUrl, game, opponent, from, to, result, limit ?? ''],
    queryFn: () => api<LossReport>(
      baseUrl,
      `/api/decision/loss${queryString({ game, opponent, from, to, result, limit })}`,
      { timeout: 90_000 }
    ),
    enabled: Boolean(baseUrl) && active,
    ...common,
    staleTime: 60_000
  })
}

export function useAdvantage(baseUrl: string, params: DecisionAdvantageParams = {}, active = true) {
  const { opponent = '', from = '', to = '', result = '' } = params
  return useQuery({
    queryKey: ['decision-advantage', baseUrl, opponent, from, to, result],
    queryFn: () => api<AdvantageReport>(
      baseUrl,
      `/api/decision/advantage${queryString({ opponent, from, to, result })}`,
      { timeout: 90_000 }
    ),
    enabled: Boolean(baseUrl) && active,
    ...common,
    staleTime: 60_000
  })
}

export function useFights(baseUrl: string, params: DecisionFightsParams = {}, active = true) {
  const { game = '', opponent = '', from = '', to = '', result = '', side = '', limit } = params
  return useQuery({
    queryKey: ['decision-fights', baseUrl, game, opponent, from, to, result, side, limit ?? ''],
    queryFn: () => api<FightReport>(
      baseUrl,
      `/api/decision/fights${queryString({ game, opponent, from, to, result, side, limit })}`,
      { timeout: 90_000 }
    ),
    enabled: Boolean(baseUrl) && active,
    ...common,
    staleTime: 60_000
  })
}

export function useOpening(baseUrl: string, params: DecisionOpeningParams = {}, active = true) {
  const { opponent = '', lane = '', from = '', to = '', side = 'enemy' } = params
  return useQuery({
    queryKey: ['decision-opening', baseUrl, opponent, lane, from, to, side],
    queryFn: () => api<OpeningReport>(
      baseUrl,
      `/api/decision/opening${queryString({ opponent, lane, from, to, side })}`,
      { timeout: 90_000 }
    ),
    enabled: Boolean(baseUrl) && active,
    ...common,
    staleTime: 60_000
  })
}

export function useResource(baseUrl: string, params: DecisionResourceParams = {}, active = true) {
  const { lane = '', player = '', opponent = '', from = '', to = '', result = '', side = 'own' } = params
  return useQuery({
    queryKey: ['decision-resource', baseUrl, lane, player, opponent, from, to, result, side],
    queryFn: () => api<ResourceReport>(
      baseUrl,
      `/api/decision/resource${queryString({ lane, player, opponent, from, to, result, side })}`,
      { timeout: 90_000 }
    ),
    enabled: Boolean(baseUrl) && active,
    ...common,
    staleTime: 60_000
  })
}
