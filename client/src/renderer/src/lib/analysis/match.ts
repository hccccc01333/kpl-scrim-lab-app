/**
 * 单局深度分析的计算内核。
 *
 * 逐条对应 v3/public/match-deep.js 与 app.js 的单局口径：位置样本剔除、
 * 入侵/集结、团战与掉点反事实、阵线、对位纵深。这里只做纯计算，
 * 页面负责文案与图形，方便拿同一份响应做回归对照。
 */

import type {
  MatchPlayer,
  PositionsData,
  ReplayData,
  ReplayDeath,
  ReplayEvent,
  ReplayFight,
  ReplayKill,
  TimelinePoint
} from '../types'

export const LANES = ['对抗路', '发育路', '中路', '打野', '游走'] as const
export type Lane = (typeof LANES)[number]

export const MAP = 60
export const GRID = 16
export const DEEP = 0.66
export const HALF = 0.5
export const STILL_SECONDS = 12
export const PROX_RADIUS = 22.5
export const PROX_SECONDS = 5
export const HEAT_WINDOW = 90

export type Camp = 'blue' | 'red'

export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
export const isNum = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

export function ownCampOf(camp?: string | null): Camp {
  return camp === 'red' || camp === 'right' ? 'red' : 'blue'
}

export function foeCampOf(camp: Camp): Camp {
  return camp === 'blue' ? 'red' : 'blue'
}

export function laneOf(player?: { position?: string | null } | null): Lane {
  const position = player?.position
  return position && (LANES as readonly string[]).includes(position) ? (position as Lane) : '游走'
}

export function playerKey(camp: string, slot: number) {
  return `${camp}-${slot}`
}

export function readNumber(player: MatchPlayer | null | undefined, key: string): number | null {
  const value = player ? (player as Record<string, unknown>)[key] : null
  return isNum(value) ? value : null
}

/** 推进进度：0 = 蓝方基地，1 = 红方基地 */
export function progress(x: number, y: number): number {
  return clamp((x + y + 112) / 224, 0, 1)
}

/** 连续静止 ≥12 秒的样本（阵亡停留等）剔除，与后端 active_mask 同口径。 */
export function activeMask(points: [number, number][], step: number): boolean[] {
  const limit = Math.max(1, Math.round(STILL_SECONDS / (step || 1)))
  const mask: boolean[] = []
  let run = 0
  for (let i = 0; i < points.length; i++) {
    const same = i > 0 && points[i][0] === points[i - 1][0] && points[i][1] === points[i - 1][1]
    run = same ? run + 1 : 0
    mask.push(run < limit)
  }
  return mask
}

export function phaseOf(t: number, duration: number): number {
  return duration > 0 ? Math.min(2, Math.floor(t / (duration / 3))) : 0
}

/* ── 经济序列与阶段表 ───────────────────────────────────────────── */

export interface PulsePoint {
  t: number
  own: number
  foe: number
  diff: number
}

export interface PhaseRow {
  label: string
  start: number
  end: number
  ownGain: number | null
  foeGain: number | null
  net: number | null
  ownPct: number
  foePct: number
  res: { own: number; foe: number }
  struct: { own: number; foe: number }
  invade: number | null
}

function validTimeline(timeline: TimelinePoint[] | undefined, duration?: number | null) {
  return (timeline || [])
    .filter((point) => isNum(point.gameTime) && isNum(point.blueGold) && isNum(point.redGold))
    .filter((point) => !isNum(duration) || !duration || point.gameTime <= duration)
}

function nearestPoint<T extends { t: number }>(list: T[], t: number): T | null {
  let best: T | null = null
  for (const item of list) {
    if (!best || Math.abs(item.t - t) < Math.abs(best.t - t)) best = item
  }
  return best
}

export function buildSeries(
  timeline: TimelinePoint[] | undefined,
  ownCamp: Camp,
  duration?: number | null
): PulsePoint[] {
  const ownKey = ownCamp === 'red' ? 'redGold' : 'blueGold'
  const foeKey = ownCamp === 'red' ? 'blueGold' : 'redGold'
  return validTimeline(timeline, duration).map((point) => {
    const own = point[ownKey]
    const foe = point[foeKey]
    return { t: point.gameTime, own, foe, diff: own - foe }
  })
}

export function diffAt(series: PulsePoint[], t: number): number | null {
  return nearestPoint(series, t)?.diff ?? null
}

export function phaseRows(
  timeline: TimelinePoint[] | undefined,
  events: ReplayEvent[] | undefined,
  positions: PositionsData | undefined,
  duration: number | null | undefined,
  ownCamp: Camp
): PhaseRow[] {
  const labels = ['对线期', '转线期', '决胜期']
  const total = isNum(duration) ? duration : 0
  const absPoints = validTimeline(timeline, duration).map((point) => ({
    t: point.gameTime,
    blue: point.blueGold,
    red: point.redGold
  }))
  const ownKey = ownCamp
  const foeKey = foeCampOf(ownCamp)
  const absAt = (t: number, key: Camp) => {
    const point = nearestPoint(absPoints, t)
    return point ? point[key] : null
  }
  const phaseGain = (index: number, key: Camp) => {
    if (!total) return null
    const a = absAt(total * index / 3, key)
    const b = absAt(total * (index + 1) / 3, key)
    return isNum(a) && isNum(b) ? b - a : null
  }
  const gains = [0, 1, 2].map((index) => ({
    own: phaseGain(index, ownKey),
    foe: phaseGain(index, foeKey)
  }))
  const gainMax = Math.max(1, ...gains.flatMap((gain) => [Math.abs(gain.own || 0), Math.abs(gain.foe || 0)]))
  const phaseFor = (t: number) => (total ? Math.min(2, Math.floor(t / (total / 3))) : 0)

  const phaseEvents = [0, 1, 2].map((index) => {
    const res = { own: 0, foe: 0 }
    const struct = { own: 0, foe: 0 }
    for (const event of events || []) {
      if (!isNum(event.t) || phaseFor(event.t) !== index) continue
      const side = event.killerCamp === ownCamp ? 'own' : 'foe'
      if (event.kind === 'resource') res[side] += 1
      else if (event.kind === 'structure') struct[side] += 1
    }
    return { res, struct }
  })

  const invadeRates = [0, 1, 2].map((index) => {
    if (!positions?.players?.length) return null
    let inside = 0
    let samples = 0
    for (const source of positions.players) {
      if (source.camp !== ownCamp) continue
      for (let i = 0; i < source.points.length; i++) {
        const t = i * positions.step
        if (total > 0 && t > total) break
        if (phaseFor(t) !== index) continue
        const [x, y] = source.points[i]
        const value = progress(x, y)
        samples += 1
        if (ownCamp === 'blue' ? value > HALF : value < HALF) inside += 1
      }
    }
    return samples ? inside / samples * 100 : null
  })

  return [0, 1, 2].map((index) => {
    const gain = gains[index]
    const net = isNum(gain.own) && isNum(gain.foe) ? gain.own - gain.foe : null
    return {
      label: labels[index],
      start: total * index / 3,
      end: total * (index + 1) / 3,
      ownGain: gain.own,
      foeGain: gain.foe,
      net,
      ownPct: clamp(Math.abs(gain.own || 0) / gainMax, 0, 1),
      foePct: clamp(Math.abs(gain.foe || 0) / gainMax, 0, 1),
      res: phaseEvents[index].res,
      struct: phaseEvents[index].struct,
      invade: invadeRates[index]
    }
  })
}

export interface TotalRow {
  label: string
  own: number | null
  foe: number | null
  share: number
}

export function totalRows(
  own: { gold?: number | null; kills?: number | null; damage?: number | null; taken?: number | null },
  foe: { gold?: number | null; kills?: number | null; damage?: number | null; taken?: number | null }
): TotalRow[] {
  const items: { label: string; a: number | null | undefined; b: number | null | undefined }[] = [
    { label: '总经济', a: own.gold, b: foe.gold },
    { label: '击杀', a: own.kills, b: foe.kills },
    { label: '输出', a: own.damage, b: foe.damage },
    { label: '承伤', a: own.taken ?? foe.damage, b: foe.taken ?? own.damage }
  ]
  return items.map(({ label, a, b }) => {
    const total = (isNum(a) ? a : 0) + (isNum(b) ? b : 0)
    return {
      label,
      own: isNum(a) ? a : null,
      foe: isNum(b) ? b : null,
      share: total > 0 && isNum(a) ? a / total * 100 : 50
    }
  })
}

/* ── 入侵：进入对侧半区的时间占比 ──────────────────────────────── */

export interface InvasionStat {
  label?: string
  hero?: string
  camp: string
  rate: number | null
  phases: (number | null)[]
  episodes: number
  first: number | null
  longest: number
  peak: number
  windows: [number, number][]
  seconds: number
}

export function invasionStats(
  positions: PositionsData,
  players: MatchPlayer[],
  duration: number | null | undefined
): Map<string, InvasionStat> {
  const step = positions.step || 2
  const meta = new Map(players.map((player) => [playerKey(player.camp, player.slot), player]))
  const phaseFor = (t: number) => phaseOf(t, isNum(duration) ? duration : 0)
  const result = new Map<string, InvasionStat>()

  for (const source of positions.players) {
    const info = meta.get(playerKey(source.camp, source.slot))
    const forward = source.camp === 'blue' ? 1 : -1
    const mask = activeMask(source.points, step)
    const phaseIn = [0, 0, 0]
    const phaseAll = [0, 0, 0]
    const windows: [number, number][] = []
    let total = 0
    let inside = 0
    let run = 0
    let runStart = 0
    let episodes = 0
    let first: number | null = null
    let longest = 0
    let peak = 0

    const close = (lastIndex: number) => {
      if (run >= 2) {
        episodes += 1
        longest = Math.max(longest, run * step)
        windows.push([runStart * step, (lastIndex + 1) * step])
      }
      run = 0
    }

    for (let i = 0; i < source.points.length; i++) {
      if (!mask[i]) {
        close(i - 1)
        continue
      }
      const [x, y] = source.points[i]
      const depth = forward > 0 ? progress(x, y) : 1 - progress(x, y)
      const phase = phaseFor(i * step)
      total += 1
      phaseAll[phase] += 1
      if (depth > peak) peak = depth
      if (depth > HALF) {
        if (first === null) first = i * step
        if (!run) runStart = i
        run += 1
        inside += 1
        phaseIn[phase] += 1
      } else {
        close(i - 1)
      }
    }
    close(source.points.length - 1)

    result.set(playerKey(source.camp, source.slot), {
      label: info?.label,
      hero: info?.hero,
      camp: source.camp,
      rate: total ? inside / total * 100 : null,
      phases: phaseAll.map((count, index) => (count ? phaseIn[index] / count * 100 : null)),
      episodes,
      first,
      longest,
      peak: peak * 100,
      windows,
      seconds: total * step
    })
  }
  return result
}

export interface MetricDef {
  key: string
  label: string
  rate?: boolean
  get: (player: MatchPlayer | null | undefined) => number | null
  hasTip?: boolean
}

export function buildMetrics(invasion?: Map<string, InvasionStat> | null): MetricDef[] {
  const base: MetricDef[] = [
    { key: 'gold', label: '经济', get: (player) => readNumber(player, 'gold') },
    { key: 'damage', label: '输出', get: (player) => readNumber(player, 'damage') },
    { key: 'taken', label: '承伤', get: (player) => readNumber(player, 'taken') },
    { key: 'participation', label: '参团', rate: true, get: (player) => readNumber(player, 'participation') },
    { key: 'cs', label: '发育', get: (player) => readNumber(player, 'cs') }
  ]
  if (!invasion) return base
  const entry = (player: MatchPlayer | null | undefined) => (player ? invasion.get(playerKey(player.camp, player.slot)) : null)
  base.push({
    key: 'invade',
    label: '入侵',
    rate: true,
    hasTip: true,
    get: (player) => entry(player)?.rate ?? null
  })
  return base
}

export function invasionOf(
  invasion: Map<string, InvasionStat> | null | undefined,
  player: MatchPlayer | null | undefined
): InvasionStat | null {
  if (!invasion || !player) return null
  return invasion.get(playerKey(player.camp, player.slot)) ?? null
}

export interface DuelPair {
  lane: Lane
  own: MatchPlayer | null
  foe: MatchPlayer | null
}

export function duelPairs(players: MatchPlayer[], ownCamp: Camp): DuelPair[] {
  const pick = (camp: Camp) => {
    const map = new Map<Lane, MatchPlayer>()
    for (const player of players) if (player.camp === camp) map.set(laneOf(player), player)
    return map
  }
  const mine = pick(ownCamp)
  const theirs = pick(foeCampOf(ownCamp))
  return LANES.map((lane) => ({ lane, own: mine.get(lane) || null, foe: theirs.get(lane) || null }))
}

export interface TeamMetricRow {
  player: MatchPlayer
  values: (number | null)[]
}

export function teamMetricRows(
  players: MatchPlayer[],
  camp: Camp,
  metrics: MetricDef[]
): { team: MatchPlayer[]; rows: TeamMetricRow[]; scale: number[] } {
  const team = players
    .filter((player) => player.camp === camp)
    .sort((a, b) => LANES.indexOf(laneOf(a)) - LANES.indexOf(laneOf(b)))
    .slice(0, 5)
  if (!team.length) return { team, rows: [], scale: [] }
  const totals = metrics.map((metric) =>
    team.reduce((sum, player) => sum + (metric.get(player) || 0), 0)
  )
  const rows = team.map((player) => ({
    player,
    values: metrics.map((metric, index) => {
      const value = metric.get(player)
      if (!isNum(value)) return null
      return metric.rate ? value : totals[index] ? value / totals[index] * 100 : 0
    })
  }))
  const scale = metrics.map((_, index) =>
    Math.max(1, ...rows.map((row) => row.values[index] ?? 0))
  )
  return { team, rows, scale }
}

/* ── 中野辅集结与入侵归因 ───────────────────────────────────────── */

export interface ProximityStat {
  rate: number | null
  count: number
  longest: number
  gap: number | null
  seconds: number
}

const TRIO: Lane[] = ['中路', '打野', '游走']
const PAIRS: [number, number][] = [[0, 1], [0, 2], [1, 2]]

export function proximity(positions: PositionsData, players: MatchPlayer[]): Map<Camp, ProximityStat> {
  const result = new Map<Camp, ProximityStat>()
  if (!positions?.players?.length) return result
  const step = positions.step || 2
  const meta = new Map(players.map((player) => [playerKey(player.camp, player.slot), player]))
  const pick = (camp: Camp) =>
    TRIO.map((lane) =>
      positions.players.find((source) => {
        const info = meta.get(playerKey(source.camp, source.slot))
        return source.camp === camp && Boolean(info) && laneOf(info) === lane
      })
    )

  for (const camp of ['blue', 'red'] as Camp[]) {
    const three = pick(camp)
    if (three.some((source) => !source)) continue
    const sources = three as PositionsData['players']
    const masks = sources.map((source) => activeMask(source.points, step))
    const n = Math.min(...sources.map((source) => source.points.length))
    let valid = 0
    let forming = 0
    let run = 0
    let count = 0
    let longest = 0
    let gapSum = 0
    const close = () => {
      if (run * step >= PROX_SECONDS) {
        count += 1
        longest = Math.max(longest, run * step)
      }
      run = 0
    }
    for (let i = 0; i < n; i++) {
      if (!masks.every((mask) => mask[i])) {
        close()
        continue
      }
      const points = sources.map((source) => source.points[i])
      const distances = PAIRS.map(([a, b]) =>
        Math.hypot(points[a][0] - points[b][0], points[a][1] - points[b][1])
      )
      valid += 1
      gapSum += (distances[0] + distances[1] + distances[2]) / 3
      if (distances.every((distance) => distance <= PROX_RADIUS)) {
        run += 1
        forming += 1
      } else {
        close()
      }
    }
    close()
    result.set(camp, {
      rate: valid ? forming / valid * 100 : null,
      count,
      longest,
      gap: valid ? gapSum / valid : null,
      seconds: valid * step
    })
  }
  return result
}

export interface InvadeSummary {
  episodes: number
  kills: number
  lost: number
  objects: number
}

export function invadeSummary(
  invasion: Map<string, InvasionStat> | null | undefined,
  events: ReplayEvent[] | undefined,
  kills: ReplayKill[] | undefined
): Map<Camp, InvadeSummary> {
  const result = new Map<Camp, InvadeSummary>()
  if (!invasion) return result
  for (const camp of ['blue', 'red'] as Camp[]) {
    const entries = [...invasion.values()].filter((item) => item.camp === camp)
    if (!entries.length) continue
    const windows = entries.flatMap((item) => item.windows)
    const won = new Set<string>()
    const lost = new Set<string>()
    const objects = new Set<string>()
    for (const [start, end] of windows) {
      for (const kill of kills || []) {
        if (!isNum(kill.t) || kill.t < start - 5 || kill.t > end + 10) continue
        const key = `${kill.t}-${kill.killer}-${kill.victim}`
        if (kill.killerCamp === camp) won.add(key)
        else if (kill.victimCamp === camp) lost.add(key)
      }
      for (const event of events || []) {
        if (!isNum(event.t) || event.t < start - 5 || event.t > end + 10) continue
        objects.add(`${event.kind}-${event.t}-${event.id || ''}`)
      }
    }
    result.set(camp, {
      episodes: entries.reduce((sum, item) => sum + item.episodes, 0),
      kills: won.size,
      lost: lost.size,
      objects: objects.size
    })
  }
  return result
}

/* ── 热区 ────────────────────────────────────────────────────────── */

export interface HeatPlayer {
  camp: string
  slot: number
  points: [number, number][]
  cells: Int16Array
  enemy: Uint8Array
  info: { label?: string | null; hero?: string | null; position?: string | null }
}

export interface HeatState {
  step: number
  duration: number
  list: HeatPlayer[]
}

export function prepareHeat(
  positions: PositionsData,
  players: MatchPlayer[],
  duration?: number | null
): HeatState | null {
  if (!positions?.players?.length) return null
  const step = positions.step || 2
  const byKey = new Map(players.map((player) => [playerKey(player.camp, player.slot), player]))
  const list = positions.players.map((source) => {
    const info = byKey.get(playerKey(source.camp, source.slot)) || source
    const mask = activeMask(source.points, step)
    const cells = new Int16Array(source.points.length).fill(-1)
    const enemy = new Uint8Array(source.points.length)
    const forward = source.camp === 'blue' ? 1 : -1
    for (let i = 0; i < source.points.length; i++) {
      if (!mask[i]) continue
      const [x, y] = source.points[i]
      const gx = clamp(Math.floor((x + MAP) / (MAP * 2) * GRID), 0, GRID - 1)
      const gy = clamp(Math.floor((y + MAP) / (MAP * 2) * GRID), 0, GRID - 1)
      cells[i] = gy * GRID + gx
      const depth = forward > 0 ? progress(x, y) : 1 - progress(x, y)
      enemy[i] = depth > HALF ? 1 : 0
    }
    return { camp: source.camp, slot: source.slot, points: source.points, cells, enemy, info }
  })
  return {
    step,
    duration: isNum(duration) && duration ? duration : (list[0]?.points.length || 0) * step,
    list
  }
}

export interface HeatCounts {
  counts: Uint16Array
  enemy: number
  total: number
}

export function heatCounts(
  list: HeatPlayer[],
  i0: number,
  i1: number
): { out: Map<string, HeatCounts>; max: number } {
  const out = new Map<string, HeatCounts>()
  let max = 1
  for (const player of list) {
    const counts = new Uint16Array(GRID * GRID)
    const end = Math.min(i1, player.cells.length - 1)
    let enemy = 0
    let total = 0
    for (let i = i0; i <= end; i++) {
      const cell = player.cells[i]
      if (cell < 0) continue
      counts[cell] += 1
      if (counts[cell] > max) max = counts[cell]
      total += 1
      if (player.enemy[i]) enemy += 1
    }
    out.set(playerKey(player.camp, player.slot), { counts, enemy, total })
  }
  return { out, max }
}

/* ── 团战与掉点 ─────────────────────────────────────────────────── */

export interface DeathRow {
  death: ReplayDeath
  t1: number
  loss: number | null
  raw: number | null
  confident: boolean
  shared: boolean
}

export interface BattleMark {
  fightIndex: number
  t: number
  x: number
  y: number
  total: number
  mine: number
  theirs: number
  side: 'own' | 'foe' | 'even'
  heroes: string[]
}

export interface ContributionRow {
  player: MatchPlayer
  joined: number
  hurt: number
  taken: number
  ctrl: number
  share: number | null
}

export interface BattleData {
  rows: DeathRow[]
  marks: BattleMark[]
  fights: { t: number; heroes: string[] }[]
  contributions: Record<Camp, ContributionRow[]>
  fightCount: number
  hasFightData: boolean
  playerCamps: Map<string, string>
}

export function buildBattle(args: {
  positions?: PositionsData
  players: MatchPlayer[]
  ownCamp: Camp
  duration?: number | null
  series?: [number, number][]
  replay?: ReplayData | null
}): BattleData {
  const { positions, players, ownCamp, duration, series, replay } = args
  const deaths = (replay?.deaths || []).filter((death) => isNum(death.t))
  const fightList = (replay?.fights || []).filter((fight) => isNum(fight.t))
  const foeCamp = foeCampOf(ownCamp)
  const step = positions?.step || 2
  const sources = positions?.players || []
  const seriesPairs = series || []

  const slotOf = (camp: string, hero: string) => {
    const player = players.find((item) => item.camp === camp && item.hero === hero)
    return player ? player.slot : null
  }
  const sourceOf = (camp: string, hero: string) => {
    const slot = slotOf(camp, hero)
    if (slot == null) return null
    return sources.find((source) => source.camp === camp && source.slot === slot) || null
  }
  const pointAt = (camp: string, hero: string, t: number) => {
    const source = sourceOf(camp, hero)
    if (!source || !source.points.length) return null
    return source.points[clamp(Math.round(t / step), 0, source.points.length - 1)]
  }
  const reviveAt = (camp: string, hero: string, t0: number) => {
    const source = sourceOf(camp, hero)
    if (!source || !source.points.length) return null
    let i = clamp(Math.floor(t0 / step), 0, source.points.length - 1)
    const start = i
    while (i < source.points.length - 1) {
      const [x, y] = source.points[i]
      const [nx, ny] = source.points[i + 1]
      if (nx !== x || ny !== y) break
      i += 1
    }
    return (i - start) * step >= 8 ? (i + 1) * step : null
  }
  const interp = (t: number): number | null => {
    if (!seriesPairs.length) return null
    if (t <= seriesPairs[0][0]) return seriesPairs[0][1]
    if (t >= seriesPairs[seriesPairs.length - 1][0]) return seriesPairs[seriesPairs.length - 1][1]
    for (let i = 1; i < seriesPairs.length; i++) {
      if (seriesPairs[i][0] >= t) {
        const [ta, va] = seriesPairs[i - 1]
        const [tb, vb] = seriesPairs[i]
        return va + (vb - va) * (t - ta) / Math.max(1, tb - ta)
      }
    }
    return null
  }
  const project = (t0: number, t1: number) => {
    const base = seriesPairs.filter(([t]) => t >= t0 - 120 && t <= t0 - 10)
    const actual = interp(t1)
    const start = interp(t0)
    const raw = isNum(actual) && isNum(start) ? actual - start : null
    if (base.length < 2 || !isNum(actual)) return { raw, loss: null, confident: false }
    const slopes: number[] = []
    for (let i = 0; i < base.length; i++) {
      for (let j = i + 1; j < base.length; j++) {
        const dt = base[j][0] - base[i][0]
        if (dt > 0) slopes.push((base[j][1] - base[i][1]) / dt)
      }
    }
    slopes.sort((a, b) => a - b)
    const slope = slopes.length ? clamp(slopes[Math.floor(slopes.length / 2)], -30, 30) : 0
    const last = base[base.length - 1]
    const expected = last[1] + slope * (t1 - last[0])
    return { raw, loss: expected - actual, confident: base.length >= 3 && last[0] - base[0][0] >= 60 }
  }

  const rows: DeathRow[] = []
  for (const death of deaths) {
    if (!isNum(death.x) || !isNum(death.y)) continue
    const revived = reviveAt(death.camp, death.hero, death.t)
    const clipped = Math.min(revived || death.t + 20, isNum(duration) && duration ? duration : Infinity)
    const t1 = Math.max(clipped, death.t + 1)
    const info = t1 - death.t >= 8 ? project(death.t, t1) : { raw: null, loss: null, confident: false }
    rows.push({ death, t1, ...info, shared: false })
  }
  rows.sort((a, b) => (isNum(b.loss) ? b.loss : -1e9) - (isNum(a.loss) ? a.loss : -1e9))
  for (const row of rows) {
    row.shared = rows.some((other) =>
      other !== row && other.death.camp === row.death.camp &&
      Math.min(row.t1, other.t1) - Math.max(row.death.t, other.death.t) > 5
    )
  }

  const marks: BattleMark[] = []
  fightList.forEach((fight, fightIndex) => {
    const points = (fight.details || []).flatMap((detail) =>
      [0, 4, 8]
        .map((offset) => pointAt(detail.camp, detail.hero, fight.t + offset))
        .filter((point): point is [number, number] => Boolean(point))
    )
    if (!points.length) return
    const x = points.reduce((sum, point) => sum + point[0], 0) / points.length
    const y = points.reduce((sum, point) => sum + point[1], 0) / points.length
    const mine = (fight[ownCamp] || 0) as number
    const theirs = (fight[foeCamp] || 0) as number
    marks.push({
      fightIndex,
      t: fight.t,
      x,
      y,
      total: (fight.camp1 || 0) + (fight.camp2 || 0),
      mine,
      theirs,
      side: mine > theirs ? 'own' : theirs > mine ? 'foe' : 'even',
      heroes: (fight.details || []).map((detail) => detail.hero).filter(Boolean)
    })
  })

  const fightRows = fightList.map((fight: ReplayFight) => {
    const details = fight.details || []
    const byCamp: Record<Camp, typeof details> = {
      blue: details.filter((item) => item.camp === 'blue'),
      red: details.filter((item) => item.camp === 'red')
    }
    const sum: Record<Camp, number> = { blue: 0, red: 0 }
    for (const camp of ['blue', 'red'] as Camp[]) {
      sum[camp] = byCamp[camp].reduce((total, item) => total + (item.hurt || 0), 0)
    }
    return { fight, byCamp, sum }
  })

  const contributionFor = (camp: Camp) => {
    const team = LANES
      .map((lane) => players.find((player) => player.camp === camp && laneOf(player) === lane))
      .filter((player): player is MatchPlayer => Boolean(player))
    return team.map((player) => {
      let joined = 0
      let hurt = 0
      let taken = 0
      let ctrl = 0
      let shareSum = 0
      let shareN = 0
      for (const row of fightRows) {
        const hit = row.byCamp[camp].find((item) => item.hero === player.hero)
        if (!hit) continue
        joined += 1
        hurt += hit.hurt || 0
        taken += hit.taken || 0
        ctrl += (hit.hardCtrl || 0) / 1000
        if (row.sum[camp]) {
          shareSum += (hit.hurt || 0) / row.sum[camp] * 100
          shareN += 1
        }
      }
      return { player, joined, hurt, taken, ctrl, share: shareN ? shareSum / shareN : null }
    })
  }

  const playerCamps = new Map<string, string>()
  for (const player of players) if (player.hero) playerCamps.set(player.hero, player.camp)

  return {
    rows,
    marks,
    fights: fightList.map((fight) => ({
      t: fight.t,
      heroes: (fight.details || []).map((detail) => detail.hero).filter(Boolean)
    })),
    contributions: { blue: contributionFor('blue'), red: contributionFor('red') },
    fightCount: fightList.length,
    hasFightData: fightList.length > 0,
    playerCamps
  }
}

/* ── 阵线：五人平均推进进度 ─────────────────────────────────────── */

export interface FrontlineRow {
  t: number
  own: number | null
  foe: number | null
}

export interface FrontlineData {
  total: number
  rows: FrontlineRow[]
  ownLine: (number | null)[]
  foeLine: (number | null)[]
  avg: number | null
  ahead: number | null
}

export function frontline(
  positions: PositionsData | undefined,
  players: MatchPlayer[],
  ownCamp: Camp,
  duration?: number | null
): FrontlineData | null {
  if (!positions?.players?.length) return null
  const step = positions.step || 2
  const foeCamp = foeCampOf(ownCamp)
  const prep = positions.players.map((source) => {
    const mask = activeMask(source.points, step)
    const forward = source.camp === 'blue' ? 1 : -1
    const advance = new Float32Array(source.points.length).fill(-1)
    for (let i = 0; i < source.points.length; i++) {
      if (!mask[i]) continue
      const [x, y] = source.points[i]
      const value = progress(x, y)
      advance[i] = forward > 0 ? value : 1 - value
    }
    return { camp: source.camp, advance }
  })
  const len = Math.min(...prep.map((entry) => entry.advance.length))
  if (len < 2) return null
  const total = Math.min(isNum(duration) && duration ? duration : Infinity, (len - 1) * step)
  const SAMPLE = 10
  const rows: FrontlineRow[] = []
  for (let t = 0; t <= total; t += SAMPLE) {
    const i = Math.min(len - 1, Math.round(t / step))
    const mean = (camp: Camp) => {
      const values = prep
        .filter((entry) => entry.camp === camp)
        .map((entry) => entry.advance[i])
        .filter((value) => value >= 0)
      return values.length >= 3 ? values.reduce((sum, value) => sum + value, 0) / values.length : null
    }
    rows.push({ t, own: mean(ownCamp), foe: mean(foeCamp) })
  }
  if (rows.length < 2) return null

  const smooth = (key: 'own' | 'foe') =>
    rows.map((row, index) => {
      const window = [rows[index - 1], row, rows[index + 1]]
        .filter((item): item is FrontlineRow => Boolean(item))
        .filter((item) => isNum(item[key]))
      return window.length
        ? window.reduce((sum, item) => sum + (item[key] as number), 0) / window.length
        : null
    })

  const ownLine = smooth('own')
  const foeLine = smooth('foe')
  const own = rows.filter((row) => isNum(row.own))
  return {
    total,
    rows,
    ownLine,
    foeLine,
    avg: own.length ? own.reduce((sum, row) => sum + (row.own as number), 0) / own.length : null,
    ahead: own.length ? own.filter((row) => (row.own as number) > 0.5).length / own.length * 100 : null
  }
}

/* ── 对位纵深 ───────────────────────────────────────────────────── */

export interface DepthCell {
  seconds: number[]
  info: MatchPlayer
}

export interface DepthRow {
  lane: Lane
  own: DepthCell | null
  foe: DepthCell | null
}

export function duelDepth(
  positions: PositionsData | undefined,
  players: MatchPlayer[],
  ownCamp: Camp,
  duration: number | null | undefined,
  threshold: number
): DepthRow[] {
  if (!positions?.players?.length) return []
  const step = positions.step || 2
  const foeCamp = foeCampOf(ownCamp)
  const index = new Map<string, DepthCell>()
  for (const source of positions.players) {
    const info = players.find((player) => player.camp === source.camp && player.slot === source.slot)
    if (!info) continue
    const mask = activeMask(source.points, step)
    const seconds = [0, 0, 0]
    for (let i = 0; i < source.points.length; i++) {
      if (!mask[i]) continue
      const t = i * step
      if (isNum(duration) && duration && t > duration) break
      const [x, y] = source.points[i]
      const value = progress(x, y)
      const inside = source.camp === 'blue' ? value > threshold : value < 1 - threshold
      if (!inside) continue
      seconds[phaseOf(t, isNum(duration) ? duration : 0)] += step
    }
    index.set(`${source.camp}-${laneOf(info)}`, { info, seconds })
  }
  return LANES.map((lane) => ({
    lane,
    own: index.get(`${ownCamp}-${lane}`) || null,
    foe: index.get(`${foeCamp}-${lane}`) || null
  }))
}

/* ── 关键节点 ───────────────────────────────────────────────────── */

export interface Swing {
  t: number
  delta: number
  value: number
}

export interface KeyNode {
  t: number
  event: string
  delta: number | null
  value: number | null
  dir: '利于本队' | '利于对手' | '回放事件'
}

const EVENT_NAMES: Record<string, string> = {
  resource: '资源',
  structure: '建筑',
  kill: '击杀',
  heroKill: '击杀'
}

export function keyNodes(
  series: PulsePoint[],
  events: ReplayEvent[] | undefined,
  result?: string | null
): KeyNode[] {
  const swings: Swing[] = []
  for (let i = 1; i < series.length; i++) {
    const delta = series[i].diff - series[i - 1].diff
    if (Math.abs(delta) >= 200) swings.push({ t: series[i].t, delta, value: series[i].diff })
  }
  const nodes = [
    ...[...swings]
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      .slice(0, 4)
      .map<KeyNode>((swing) => ({
        t: swing.t,
        event: '经济差波动',
        delta: swing.delta,
        value: swing.value,
        dir: (result === 'win' ? swing.delta > 0 : swing.delta < 0) ? '利于本队' : '利于对手'
      })),
    ...(events || [])
      .filter((event) => /kill|death|resource|structure/i.test(event.kind || ''))
      .slice(0, 4)
      .map<KeyNode>((event) => ({
        t: event.t,
        event: `${EVENT_NAMES[event.kind] || event.kind || '事件'} · ${event.killer || event.killerHero || '—'}`,
        delta: null,
        value: diffAt(series, event.t),
        dir: '回放事件'
      }))
  ]
  return nodes.sort((a, b) => (a.t || 0) - (b.t || 0)).slice(0, 8)
}

/* ── 阶段变化摘要（结论卡用） ───────────────────────────────────── */

export interface TurnSummary {
  t: number
  delta: number
  value: number
}

export function biggestTurn(series: PulsePoint[]): TurnSummary | null {
  let best: TurnSummary | null = null
  for (let i = 1; i < series.length; i++) {
    const delta = series[i].diff - series[i - 1].diff
    if (Math.abs(delta) < 200) continue
    const item = { t: series[i].t, delta, value: series[i].diff }
    if (!best || Math.abs(item.delta) > Math.abs(best.delta)) best = item
  }
  return best
}
