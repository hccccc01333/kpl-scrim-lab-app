/**
 * 战队板块的共用计算：评分构成、四轴风格、分路资源、BP 画像与训练台账。
 * 评分与四轴只在同池分位上做加权，缺失项按剩余权重归一。
 */

import type {
  BpBoard,
  BpGame,
  CampCompare,
  CampCombo,
  StudioTeam,
  TeamMetrics,
  TeamPercentiles,
  TeamRoster,
  TeamTrainingTeam
} from '../types'

export const TEAM_LANES = ['对抗路', '打野', '中路', '发育路', '游走'] as const

export function isNum(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function mean(values: number[]): number | null {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

export function percentileOf(value: number | null | undefined, values: number[]): number | null {
  if (!isNum(value) || !values.length) return null
  let below = 0
  let equal = 0
  for (const item of values) {
    if (item < value) below += 1
    else if (item === value) equal += 1
  }
  return (below + equal * 0.5) / values.length * 100
}

const SCORE_WEIGHTS: [keyof TeamPercentiles, number][] = [
  ['winRate', 30],
  ['gpm', 20],
  ['kda', 20],
  ['dpm', 15],
  ['towerPerGame', 15]
]

export function teamScore(percentiles?: TeamPercentiles | null): number | null {
  if (!percentiles) return null
  let weighted = 0
  let weight = 0
  for (const [key, value] of SCORE_WEIGHTS) {
    const point = percentiles[key]
    if (!isNum(point)) continue
    weighted += point * value
    weight += value
  }
  return weight ? Math.round(weighted / weight) : null
}

export function teamTier(score?: number | null): 'S' | 'A' | 'B' | 'C' {
  if (!isNum(score)) return 'C'
  if (score >= 80) return 'S'
  if (score >= 60) return 'A'
  if (score >= 40) return 'B'
  return 'C'
}

export interface TeamAxis {
  key: string
  label: string
  value: number | null
  hint: string
}

const axisAverage = (values: (number | null | undefined)[]): number | null => mean(values.filter(isNum))

export function teamAxes(percentiles?: TeamPercentiles | null): TeamAxis[] {
  if (!percentiles) {
    return [
      { key: 'pace', label: '节奏', value: null, hint: '分均击杀 + 时长' },
      { key: 'fight', label: '团战', value: null, hint: '助攻 + 击杀 + 控制' },
      { key: 'macro', label: '运营', value: null, hint: '分均经济 + 推塔 + 少死' },
      { key: 'late', label: '后期', value: null, hint: '场均时长' }
    ]
  }
  const inverse = (value?: number | null) => (isNum(value) ? 100 - value : null)
  return [
    { key: 'pace', label: '节奏', value: axisAverage([percentiles.killsPerMin, inverse(percentiles.duration)]), hint: '分均击杀 + 短时长' },
    { key: 'fight', label: '团战', value: axisAverage([percentiles.assistsPerMin, percentiles.killsPerMin, percentiles.controlPerMin]), hint: '助攻 + 击杀 + 控制' },
    { key: 'macro', label: '运营', value: axisAverage([percentiles.gpm, percentiles.towerPerGame, inverse(percentiles.deathsPerGame)]), hint: '分均经济 + 推塔 + 少死' },
    { key: 'late', label: '后期', value: percentiles.duration ?? null, hint: '场均时长分位' }
  ]
}

export function axisTone(value?: number | null): 'strong' | 'weak' | 'flat' {
  if (!isNum(value)) return 'flat'
  if (value >= 65) return 'strong'
  if (value <= 35) return 'weak'
  return 'flat'
}

export interface TeamMetricDef {
  key: string
  label: string
  digits: number
  suffix?: string
}

export const TEAM_METRICS: TeamMetricDef[] = [
  { key: 'gpm', label: '分均经济', digits: 0 },
  { key: 'dpm', label: '分均输出', digits: 0 },
  { key: 'dtpm', label: '分均承伤', digits: 0 },
  { key: 'kda', label: 'KDA', digits: 2 },
  { key: 'towerPerGame', label: '场均推塔', digits: 1 },
  { key: 'duration', label: '场均时长', digits: 0 },
  { key: 'winRate', label: '胜率', digits: 1, suffix: '%' }
]

export function teamMetric(team: StudioTeam, key: string): number | null {
  const value = (team.metrics as TeamMetrics)[key]
  return isNum(value) ? value : null
}

export function metricText(value: number | null | undefined, metric: TeamMetricDef): string {
  if (!isNum(value)) return '—'
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: metric.digits })}${metric.suffix || ''}`
}

export interface TeamContrastRow {
  key: string
  label: string
  own: number | null
  foe: number | null
  diff: number | null
  diffPct: number | null
  digits: number
  suffix?: string
}

export function teamContrast(team: StudioTeam, own: StudioTeam | { metrics: TeamMetrics; percentiles: TeamPercentiles }): TeamContrastRow[] {
  return TEAM_METRICS.map((metric) => {
    const a = teamMetric(team, metric.key)
    const b = isNum((own.metrics as TeamMetrics)[metric.key]) ? (own.metrics as TeamMetrics)[metric.key] as number : null
    const diff = isNum(a) && isNum(b) ? a - b : null
    return {
      key: metric.key,
      label: metric.label,
      own: a,
      foe: b,
      diff,
      diffPct: isNum(diff) && isNum(b) && b !== 0 ? diff / Math.abs(b) * 100 : null,
      digits: metric.digits,
      suffix: metric.suffix
    }
  })
}

export function resourceShares(compare: CampCompare | undefined, side: 'own' | 'enemy' = 'own') {
  const lanes = compare?.lanes || []
  const sum = (key: 'gold' | 'damage' | 'taken') =>
    lanes.reduce((total, lane) => total + (lane[side]?.[key] || 0), 0)
  const totals = { gold: sum('gold'), damage: sum('damage'), taken: sum('taken') }
  return TEAM_LANES.map((laneName) => {
    const lane = lanes.find((item) => item.lane === laneName)
    const entry = lane?.[side] || null
    return {
      lane: laneName,
      gold: totals.gold && entry?.gold ? entry.gold / totals.gold * 100 : null,
      damage: totals.damage && entry?.damage ? entry.damage / totals.damage * 100 : null,
      taken: totals.taken && entry?.taken ? entry.taken / totals.taken * 100 : null,
      games: entry?.games || 0
    }
  })
}

export function lanePressure(compare: CampCompare | undefined) {
  const order = new Map<string, number>(TEAM_LANES.map((lane, index) => [lane, index]))
  return (compare?.lanes || [])
    .map((lane) => ({
      lane: lane.lane,
      ownGpm: lane.own?.gpm ?? null,
      enemyGpm: lane.enemy?.gpm ?? null,
      diff: isNum(lane.own?.gpm) && isNum(lane.enemy?.gpm) ? lane.own.gpm - lane.enemy.gpm : null,
      ownName: lane.own?.name,
      enemyName: lane.enemy?.name,
      ownKda: lane.own?.kda ?? null,
      enemyKda: lane.enemy?.kda ?? null
    }))
    .sort((a, b) => (order.get(a.lane) ?? 9) - (order.get(b.lane) ?? 9))
}

export function durationBuckets(games?: { duration?: number; win?: boolean }[]) {
  const buckets = [
    { label: '≤12 分', min: 0, max: 720, games: 0, wins: 0 },
    { label: '12–20 分', min: 720, max: 1200, games: 0, wins: 0 },
    { label: '>20 分', min: 1200, max: Infinity, games: 0, wins: 0 }
  ]
  for (const game of games || []) {
    const seconds = game.duration || 0
    if (!seconds) continue
    const bucket = buckets.find((item) => seconds >= item.min && seconds < item.max)
    if (!bucket) continue
    bucket.games += 1
    if (game.win) bucket.wins += 1
  }
  return buckets
}

export function rosterStability(roster?: TeamRoster): number | null {
  if (!roster) return null
  if (isNum(roster.stability)) return roster.stability
  const lineups = roster.lineups || []
  if (!lineups.length) return null
  const total = lineups.reduce((sum, lineup) => sum + lineup.games, 0)
  const biggest = Math.max(...lineups.map((lineup) => lineup.games))
  return total ? biggest / total * 100 : null
}

export function rosterRotation(roster?: TeamRoster): number | null {
  if (!roster) return null
  if (isNum(roster.rotation)) return roster.rotation
  if (!roster.lanes?.length) return null
  const rotating = roster.lanes.filter((lane) => lane.players.length > 1).length
  return rotating / roster.lanes.length * 100
}

/* ── BP 聚合 ──────────────────────────────────────────────────────── */

export function teamBpGames(board: BpBoard, teamId: string): BpGame[] {
  return board.games.filter((game) => game.teamId === teamId)
}

export interface BpCountRow {
  hero: string
  count: number
  share: number
  wins: number
  decided: number
  winRate: number | null
  icon?: string | null
}

function countEntries(games: BpGame[], select: (game: BpGame) => { name: string; icon?: string | null }[], subjectWins: (game: BpGame) => boolean): BpCountRow[] {
  const map = new Map<string, { count: number; wins: number; decided: number; icon?: string | null }>()
  for (const game of games) {
    const seen = new Set<string>()
    const win = subjectWins(game)
    for (const entry of select(game)) {
      const name = entry.name
      if (!name || seen.has(name)) continue
      seen.add(name)
      const row = map.get(name) || { count: 0, wins: 0, decided: 0, icon: entry.icon }
      row.count += 1
      if (game.result === 'win' || game.result === 'loss') {
        row.decided += 1
        if (win) row.wins += 1
      }
      map.set(name, row)
    }
  }
  const total = [...map.values()].reduce((sum, row) => sum + row.count, 0) || 1
  return [...map.entries()]
    .map(([hero, row]) => ({
      hero,
      count: row.count,
      share: row.count / total * 100,
      wins: row.wins,
      decided: row.decided,
      winRate: row.decided ? row.wins / row.decided * 100 : null,
      icon: row.icon
    }))
    .sort((a, b) => b.count - a.count || (b.winRate || 0) - (a.winRate || 0))
}

/** 本队视角的选/禁与“被选中时的胜率”。 */
export function ownBpCounts(games: BpGame[]) {
  return {
    picks: countEntries(games, (game) => game.picks.own, (game) => game.result === 'win'),
    bans: countEntries(games, (game) => game.bans.own, (game) => game.result === 'win'),
    enemyPicks: countEntries(games, (game) => game.picks.enemy, (game) => game.result === 'loss'),
    enemyBans: countEntries(games, (game) => game.bans.enemy, (game) => game.result === 'loss')
  }
}

export interface TeamBpProfile {
  team: BpBoard['teams'][number] | null
  games: BpGame[]
  wins: number
  losses: number
  winRate: number | null
  picks: BpCountRow[]
  bans: BpCountRow[]
  baselinePicks: BpCountRow[]
  coverage: number
  poolHeroes: number
  poolHhi: number
  poolEffective: number
  topShare: number
  combos2: CampCombo[]
  combos3: CampCombo[]
  competitions: { label: string; count: number; share: number; tone: string }[]
}

export function teamBpProfile(board: BpBoard, teamId: string): TeamBpProfile {
  const games = teamBpGames(board, teamId)
  const team = board.teams.find((item) => item.id === teamId) || null
  const winners = games.filter((game) => game.result === 'loss').length
  const losers = games.filter((game) => game.result === 'win').length
  const decided = winners + losers
  // 视角翻转：bp-board 的 enemy 就是这支对手战队。
  const picks = countEntries(games, (game) => game.picks.enemy, (game) => game.result === 'loss')
  const bans = countEntries(games, (game) => game.bans.enemy, (game) => game.result === 'loss')
  const baselinePicks = countEntries(
    board.games,
    (game) => game.picks.enemy,
    (game) => game.result === 'loss'
  )
  const totalPicks = picks.reduce((sum, row) => sum + row.count, 0)
  const shares = picks.map((row) => row.count / Math.max(1, totalPicks))
  const hhi = shares.reduce((sum, share) => sum + share * share, 0)
  const comboGames = games.map((game) => ({
    heroes: game.picks.enemy.map((entry) => entry.name).filter(Boolean),
    win: game.result === 'loss'
  }))
  const combos2 = combinationRows(comboGames, 2)
  const combos3 = combinationRows(comboGames, 3)
  const banCount = bans.reduce((sum, row) => sum + row.count, 0)
  const pickCount = picks.reduce((sum, row) => sum + row.count, 0)
  return {
    team,
    games,
    wins: winners,
    losses: losers,
    winRate: decided ? winners / decided * 100 : null,
    picks,
    bans,
    baselinePicks,
    coverage: games.length,
    poolHeroes: picks.length,
    poolHhi: hhi,
    poolEffective: hhi ? 1 / hhi : 0,
    topShare: picks[0]?.share ?? 0,
    combos2,
    combos3,
    competitions: [
      { label: '本队选用', count: pickCount, share: 25, tone: 'own' },
      { label: '对手禁用', count: banCount, share: 25, tone: 'foe' }
    ]
  }
}

function combinationRows(games: { heroes: string[]; win: boolean }[], size: number): CampCombo[] {
  const map = new Map<string, { games: number; wins: number }>()
  for (const game of games) {
    const heroes = [...new Set(game.heroes)].sort()
    for (let i = 0; i < heroes.length; i++) {
      for (let j = i + 1; j < heroes.length; j++) {
        if (size === 3) {
          for (let k = j + 1; k < heroes.length; k++) {
            const key = [heroes[i], heroes[j], heroes[k]].join('|')
            const row = map.get(key) || { games: 0, wins: 0 }
            row.games += 1
            if (game.win) row.wins += 1
            map.set(key, row)
          }
        } else {
          const key = [heroes[i], heroes[j]].join('|')
          const row = map.get(key) || { games: 0, wins: 0 }
          row.games += 1
          if (game.win) row.wins += 1
          map.set(key, row)
        }
      }
    }
  }
  return [...map.entries()]
    .map(([key, row]) => ({
      heroes: key.split('|'),
      games: row.games,
      wins: row.wins,
      decided: row.games,
      winRate: row.games ? row.wins / row.games * 100 : null,
      expected: null,
      synergy: null,
      small: row.games < 3
    }))
    .sort((a, b) => b.games - a.games || (b.winRate || 0) - (a.winRate || 0))
    .slice(0, 6)
}

export function liftOf(row: BpCountRow, baseline: BpCountRow[]): number | null {
  const base = baseline.find((item) => item.hero === row.hero)
  if (!base || !base.share || !isNum(row.share)) return null
  return row.share / base.share
}

export function competitionRows(games: BpGame[]) {
  const counts = ownBpCounts(games)
  const total = counts.picks.reduce((sum, row) => sum + row.count, 0)
    + counts.bans.reduce((sum, row) => sum + row.count, 0)
    + counts.enemyPicks.reduce((sum, row) => sum + row.count, 0)
    + counts.enemyBans.reduce((sum, row) => sum + row.count, 0)
  const base = Math.max(1, total)
  return [
    { label: '本队选用', count: counts.picks.reduce((sum, row) => sum + row.count, 0), share: 0, tone: 'own' },
    { label: '本队禁用', count: counts.bans.reduce((sum, row) => sum + row.count, 0), share: 0, tone: 'own-ban' },
    { label: '对手选用', count: counts.enemyPicks.reduce((sum, row) => sum + row.count, 0), share: 0, tone: 'foe' },
    { label: '对手禁用', count: counts.enemyBans.reduce((sum, row) => sum + row.count, 0), share: 0, tone: 'foe-ban' }
  ].map((row) => ({ ...row, share: row.count / base * 100 }))
}

export function trainingSummary(team: TeamTrainingTeam) {
  return {
    sessions: team.sessions || [],
    planCount: team.planCount,
    goalCount: team.goalCount,
    goalsDone: team.goalsDone,
    reviewed: team.reviewed
  }
}
