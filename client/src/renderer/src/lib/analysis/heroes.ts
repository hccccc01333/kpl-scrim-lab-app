/**
 * 英雄板块的共用计算：档位、英雄榜、组合、对比分位与时间聚合。
 * 全部来自 camp-compare / camp-combos / camp-partners / hero-detail / matches。
 */

import type {
  CampCompare,
  CampCombo,
  CampHeroRow,
  CampPartners,
  HeroDetailData,
  LaneMatchupPayload,
  MatchSummary
} from '../types'

export const HERO_LANES = ['对抗路', '打野', '中路', '发育路', '游走'] as const

export function isNum(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function heroTier(winRate?: number | null): 'S' | 'A' | 'B' | 'C' {
  if (!isNum(winRate)) return 'C'
  if (winRate >= 55) return 'S'
  if (winRate >= 50) return 'A'
  if (winRate >= 45) return 'B'
  return 'C'
}

export function heroTone(tier: 'S' | 'A' | 'B' | 'C') {
  return tier === 'S' ? 'is-s' : tier === 'A' ? 'is-a' : tier === 'B' ? 'is-b' : 'is-c'
}

export function laneOrder(lane?: string | null) {
  const index = HERO_LANES.indexOf((lane || '') as (typeof HERO_LANES)[number])
  return index < 0 ? HERO_LANES.length : index
}

export function sortHeroes(rows: CampHeroRow[]): CampHeroRow[] {
  return [...rows].sort((a, b) => b.games - a.games || (b.winRate || 0) - (a.winRate || 0))
}

export function heroKey(row: { hero: string; lane?: string | null }) {
  return `${row.hero}|${row.lane || ''}`
}

export function parseHeroKey(key: string): { hero: string; lane: string } {
  const [hero, lane = ''] = key.split('|')
  return { hero, lane }
}

export function quantile(values: number[], p: number): number | null {
  if (!values.length) return null
  const list = [...values].sort((a, b) => a - b)
  const index = clamp(p, 0, 1) * (list.length - 1)
  const low = Math.floor(index)
  const high = Math.ceil(index)
  if (low === high) return list[low]
  return list[low] + (list[high] - list[low]) * (index - low)
}

export function rankOf(value: number | null | undefined, values: number[], descending = true): number | null {
  if (!isNum(value) || !values.length) return null
  return 1 + values.filter((item) => (descending ? item > value : item < value)).length
}

export interface HeroCompareMetric {
  key: string
  label: string
  digits: number
  suffix?: string
  better: 'high' | 'low'
}

export const HERO_COMPARE_METRICS: HeroCompareMetric[] = [
  { key: 'games', label: '出场', digits: 0, better: 'high' },
  { key: 'winRate', label: '胜率', digits: 1, suffix: '%', better: 'high' },
  { key: 'kda', label: 'KDA', digits: 2, better: 'high' },
  { key: 'gpm', label: '分均经济', digits: 0, better: 'high' },
  { key: 'dpmTotal', label: '分均输出', digits: 0, better: 'high' },
  { key: 'participation', label: '参团率', digits: 1, suffix: '%', better: 'high' }
]

export function heroMetric(row: CampHeroRow | undefined, key: string): number | null {
  if (!row) return null
  const value = (row as unknown as Record<string, unknown>)[key]
  return isNum(value) ? value : null
}

export function metricText(value: number | null | undefined, metric: HeroCompareMetric): string {
  if (!isNum(value)) return '—'
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: metric.digits })}${metric.suffix || ''}`
}

export function heroRows(compare: CampCompare | undefined, side: 'own' | 'enemy' = 'own'): CampHeroRow[] {
  return sortHeroes(compare?.heroes?.[side] || [])
}

export function heroPool(compare: CampCompare | undefined, side: 'own' | 'enemy' = 'own') {
  return compare?.pool?.[side] || { heroes: 0, picks: 0, hhi: 0, effective: 0 }
}

export interface PartnerCard {
  partner: string
  games: number
  winRate: number | null
  expected: number | null
  synergy: number | null
  small: boolean
  heroes: string[]
}

export function partnerCards(data: CampPartners | undefined): PartnerCard[] {
  return (data?.partners || []).slice(0, 9).map((row: CampCombo & { partner: string }) => ({
    partner: row.partner,
    games: row.games,
    winRate: row.winRate,
    expected: row.expected,
    synergy: row.synergy,
    small: row.small,
    heroes: row.heroes
  }))
}

export function comboRows(compare: CampCompare | undefined, size: 2 | 3, side: 'own' | 'enemy' = 'own'): CampCombo[] {
  const group = size === 2 ? compare?.combos : compare?.combos3
  return (group?.[side]?.combos || []).slice(0, 9)
}

export interface LeagueRow {
  key: string
  label: string
  hero: number | null
  all: number | null
  digits: number
  suffix?: string
}

export function leagueRows(detail: HeroDetailData | undefined): LeagueRow[] {
  if (!detail) return []
  return [
    { key: 'kda', label: 'KDA', hero: detail.league.kda?.hero ?? null, all: detail.league.kda?.all ?? null, digits: 2 },
    { key: 'gpm', label: '分均经济', hero: detail.league.gpm?.hero ?? null, all: detail.league.gpm?.all ?? null, digits: 0 },
    { key: 'dpm', label: '分均输出', hero: detail.league.dpm?.hero ?? null, all: detail.league.dpm?.all ?? null, digits: 0 },
    { key: 'participation', label: '参团率', hero: detail.league.participation?.hero ?? null, all: detail.league.participation?.all ?? null, digits: 1, suffix: '%' },
    { key: 'gold', label: '终局经济', hero: detail.league.gold?.hero ?? null, all: detail.league.gold?.all ?? null, digits: 0 },
    { key: 'cs', label: '补刀', hero: detail.league.cs?.hero ?? null, all: detail.league.cs?.all ?? null, digits: 0 }
  ]
}

export function leagueDelta(hero: number | null, all: number | null): number | null {
  if (!isNum(hero) || !isNum(all) || all === 0) return null
  return (hero - all) / Math.abs(all) * 100
}

export interface TimeBucket {
  key: string
  label: string
  games: number
  wins: number
  losses: number
  undecided: number
  winRate: number | null
}

export function timeBuckets(matches: MatchSummary[], hero: string, mode: 'week' | 'month' | 'year'): TimeBucket[] {
  const map = new Map<string, TimeBucket>()
  for (const match of matches) {
    if (!(match.heroes || []).includes(hero)) continue
    const day = String(match.date || '').slice(0, 10)
    if (!day) continue
    const key = bucketKey(day, mode)
    const bucket = map.get(key) || { key, label: bucketLabel(key, mode), games: 0, wins: 0, losses: 0, undecided: 0, winRate: null }
    bucket.games += 1
    if (match.result === 'win') bucket.wins += 1
    else if (match.result === 'loss') bucket.losses += 1
    else bucket.undecided += 1
    map.set(key, bucket)
  }
  return [...map.values()]
    .map((bucket) => {
      const decided = bucket.wins + bucket.losses
      return { ...bucket, winRate: decided ? bucket.wins / decided * 100 : null }
    })
    .sort((a, b) => a.key.localeCompare(b.key))
    .slice(-12)
}

function bucketKey(day: string, mode: 'week' | 'month' | 'year') {
  if (mode === 'year') return day.slice(0, 4)
  if (mode === 'month') return day.slice(0, 7)
  const date = new Date(`${day}T00:00:00`)
  if (Number.isNaN(date.getTime())) return day
  const offset = (date.getDay() + 6) % 7
  date.setDate(date.getDate() - offset)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function bucketLabel(key: string, mode: 'week' | 'month' | 'year') {
  if (mode === 'year') return key
  if (mode === 'month') return key.replace('-', '/')
  return `${key.slice(5, 7)}/${key.slice(8, 10)} 周`
}

export function heroMatchups(
  payload: LaneMatchupPayload | undefined,
  hero: string,
  side: 'own' | 'enemy' = 'own'
): { hero: string; n: number; avgGoldDiff: number | null; aheadRate: number | null; winRate: number | null }[] {
  if (!payload?.heroes?.length) return []
  const map = new Map<string, { n: number; goldWeight: number; aheadWeight: number; winWeight: number; winN: number }>()
  for (const row of payload.heroes) {
    const self = side === 'own' ? row.ownHero : row.enemyHero
    if (self !== hero) continue
    const other = side === 'own' ? row.enemyHero : row.ownHero
    const weight = Math.max(1, row.n || 1)
    const item = map.get(other) || { n: 0, goldWeight: 0, aheadWeight: 0, winWeight: 0, winN: 0 }
    item.n += weight
    if (isNum(row.avgGoldDiff)) item.goldWeight += row.avgGoldDiff * weight
    if (isNum(row.aheadRate)) item.aheadWeight += row.aheadRate * weight
    if (isNum(row.winRate)) {
      item.winWeight += row.winRate * weight
      item.winN += weight
    }
    map.set(other, item)
  }
  return [...map.entries()]
    .map(([other, item]) => ({
      hero: other,
      n: item.n,
      avgGoldDiff: item.n ? item.goldWeight / item.n : null,
      aheadRate: item.n ? item.aheadWeight / item.n : null,
      winRate: item.winN ? item.winWeight / item.winN : null
    }))
    .sort((a, b) => b.n - a.n)
    .slice(0, 8)
}

export function heroRecent(matches: MatchSummary[], hero: string): MatchSummary[] {
  return matches.filter((match) => (match.heroes || []).includes(hero)).slice(0, 8)
}
