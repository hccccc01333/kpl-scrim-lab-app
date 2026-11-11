/**
 * 选手板块的共用计算：分位、档位、切片、对位、搭档、对比与稳定性。
 * 数据来自 /api/v3/players-board；这里不复制后端的聚合口径，只做页面派生。
 */

import type {
  BoardGame,
  BoardPlayer,
  BoardRecentGame,
  PlayerSplit,
  PlayersBoard
} from '../types'

export const PLAYER_LANES = ['对抗路', '打野', '中路', '发育路', '游走'] as const
export type PlayerLane = (typeof PLAYER_LANES)[number]

export function laneIndex(lane?: string | null): number {
  const index = PLAYER_LANES.indexOf((lane || '') as PlayerLane)
  return index < 0 ? PLAYER_LANES.length : index
}

export function isNum(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function mean(values: number[]): number | null {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

export function median(values: number[]): number | null {
  if (!values.length) return null
  const list = [...values].sort((a, b) => a - b)
  const middle = Math.floor(list.length / 2)
  return list.length % 2 ? list[middle] : (list[middle - 1] + list[middle]) / 2
}

export function stddev(values: number[]): number | null {
  const average = mean(values)
  if (average === null || values.length < 2) return null
  return Math.sqrt(values.reduce((sum, value) => sum + (value - average) ** 2, 0) / values.length)
}

/** 线性插值分位，hero 对比与对位分布带共用。 */
export function quantile(values: number[], p: number): number | null {
  if (!values.length) return null
  const list = [...values].sort((a, b) => a - b)
  const index = clamp(p, 0, 1) * (list.length - 1)
  const low = Math.floor(index)
  const high = Math.ceil(index)
  if (low === high) return list[low]
  return list[low] + (list[high] - list[low]) * (index - low)
}

export function scoreTier(score?: number | null): 'S' | 'A' | 'B' | 'C' {
  if (!isNum(score)) return 'C'
  if (score >= 75) return 'S'
  if (score >= 60) return 'A'
  if (score >= 45) return 'B'
  return 'C'
}

export function winTier(winRate?: number | null): 'S' | 'A' | 'B' | 'C' {
  if (!isNum(winRate)) return 'C'
  if (winRate >= 55) return 'S'
  if (winRate >= 50) return 'A'
  if (winRate >= 45) return 'B'
  return 'C'
}

export function sideName(side?: string | null): string {
  return side === 'enemy' ? '对手' : '本队'
}

export function formLabel(form?: BoardPlayer['form']): string {
  if (!form?.available) return '样本不足'
  if (form.tone === 'up') return '上升'
  if (form.tone === 'down') return '回落'
  return '平稳'
}

export function formTone(form?: BoardPlayer['form']): 'up' | 'down' | 'flat' | 'muted' {
  if (!form?.available) return 'muted'
  if (form.tone === 'up') return 'up'
  if (form.tone === 'down') return 'down'
  return 'flat'
}

export function recentGames(player: BoardPlayer): BoardRecentGame[] {
  return player.recent || []
}

export function playerSlice(player: BoardPlayer, kind: 'day' | 'opponent', key: string): BoardPlayer {
  const split = player.splits?.[kind]?.[key]
  if (!split) return player
  const merged: Partial<PlayerSplit> = split
  return {
    ...player,
    ...merged,
    recent: filterRecent(player.recent || [], kind, key)
  }
}

export function filterRecent(recent: BoardRecentGame[], kind: 'day' | 'opponent', key: string): BoardRecentGame[] {
  return recent.filter((game) => (kind === 'day' ? game.day === key : game.opponent === key))
}

export function sliceOptions(player: BoardPlayer, kind: 'day' | 'opponent'): string[] {
  const splits = player.splits?.[kind] || {}
  return Object.keys(splits).sort((a, b) => b.localeCompare(a))
}

export interface CompareMetric {
  key: string
  label: string
  digits: number
  suffix?: string
}

export const COMPARE_METRICS: CompareMetric[] = [
  { key: 'kda', label: 'KDA', digits: 2 },
  { key: 'gpm', label: '分均经济', digits: 0 },
  { key: 'dpm', label: '分均输出', digits: 0 },
  { key: 'participation', label: '参团率', digits: 1, suffix: '%' },
  { key: 'damageShare', label: '输出占比', digits: 1, suffix: '%' },
  { key: 'goldShare', label: '经济占比', digits: 1, suffix: '%' },
  { key: 'takenShare', label: '承伤占比', digits: 1, suffix: '%' },
  { key: 'dtpm', label: '分均承伤', digits: 0 }
]

export const PERCENT_METRICS = [
  { key: 'kda', label: 'KDA' },
  { key: 'gpm', label: '分均经济' },
  { key: 'dpm', label: '分均输出' },
  { key: 'participation', label: '参团' },
  { key: 'damageShare', label: '输出份额' },
  { key: 'takenShare', label: '承伤份额' },
  { key: 'goldShare', label: '经济份额' }
]

export const STYLE_AXES = [
  { key: 'goldShare', label: '资源投入' },
  { key: 'damageShare', label: '输出产出' },
  { key: 'participation', label: '团战参与' },
  { key: 'takenShare', label: '承伤承担' },
  { key: 'kda', label: '生存收割' },
  { key: 'gpm', label: '经济份额' }
]

export function playerValue(player: BoardPlayer, key: string): number | null {
  const value = (player as unknown as Record<string, unknown>)[key]
  return isNum(value) ? value : null
}

export function metricText(player: BoardPlayer, metric: CompareMetric): string {
  const value = playerValue(player, metric.key)
  if (!isNum(value)) return '—'
  const digits = metric.digits
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })}${metric.suffix || ''}`
}

export function playerPercent(player: BoardPlayer, key: string): number | null {
  const value = player.percent?.[key]
  return isNum(value) ? value : null
}

export function styleAxes(player: BoardPlayer): { key: string; label: string; value: number }[] {
  return STYLE_AXES.map((axis) => ({
    ...axis,
    value: playerPercent(player, axis.key) ?? 0
  }))
}

export function playstyleTags(player: BoardPlayer): string[] {
  const tags: string[] = []
  for (const axis of STYLE_AXES) {
    const value = playerPercent(player, axis.key)
    if (!isNum(value)) continue
    if (value >= 65) tags.push(`强${axis.label}`)
    if (value <= 35) tags.push(`弱${axis.label}`)
  }
  if (player.lane === '打野' && (player.gpm || 0) >= 700) tags.push('野核节奏')
  if (player.lane === '游走' && (player.participation || 0) >= 65) tags.push('开团支点')
  if (player.lane === '发育路' && (player.damageShare || 0) >= 28) tags.push('主输出')
  return [...new Set(tags)].slice(0, 5)
}

export interface KeyGame {
  game: BoardRecentGame
  tone: 'best' | 'worst'
}

export function keyGames(player: BoardPlayer): KeyGame[] {
  const list = [...(player.recent || [])].filter((game) => isNum(game.rating))
  if (!list.length) return []
  const best = [...list].sort((a, b) => (b.rating || 0) - (a.rating || 0)).slice(0, 3)
  const worst = [...list].sort((a, b) => (a.rating || 0) - (b.rating || 0)).slice(0, 3)
  const seen = new Set<string>()
  const rows: KeyGame[] = []
  for (const game of best) {
    if (seen.has(game.gameId)) continue
    seen.add(game.gameId)
    rows.push({ game, tone: 'best' })
  }
  for (const game of worst) {
    if (seen.has(game.gameId)) continue
    seen.add(game.gameId)
    rows.push({ game, tone: 'worst' })
  }
  return rows
}

export interface PartnerRow {
  name: string
  games: number
  wins: number
  winRate: number | null
  hero?: string
}

export function partnersOf(board: PlayersBoard, playerName: string): PartnerRow[] {
  const player = board.players.find((item) => item.name === playerName)
  const side = player?.side === 'enemy' ? 'enemy' : 'own'
  const map = new Map<string, { games: number; wins: number; heroes: Map<string, number> }>()
  for (const game of board.games) {
    const own = game[side].find((row) => row.name === playerName)
    if (!own) continue
    const won = side === 'own' ? game.result === 'win' : game.result === 'loss'
    for (const mate of game[side]) {
      if (mate.name === playerName) continue
      const entry = map.get(mate.name) || { games: 0, wins: 0, heroes: new Map<string, number>() }
      entry.games += 1
      if (won) entry.wins += 1
      entry.heroes.set(mate.hero, (entry.heroes.get(mate.hero) || 0) + 1)
      map.set(mate.name, entry)
    }
  }
  return [...map.entries()]
    .map(([name, entry]) => ({
      name,
      games: entry.games,
      wins: entry.wins,
      winRate: entry.games ? entry.wins / entry.games * 100 : null,
      hero: [...entry.heroes.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
    }))
    .sort((a, b) => b.games - a.games || (b.winRate || 0) - (a.winRate || 0))
    .slice(0, 8)
}

export interface LaneMatchupRow {
  game: BoardGame
  ownHero: string
  enemyHero: string
  enemyPlayer: string
  goldDiff: number | null
  win: boolean
}

export function sameLaneMatchups(board: PlayersBoard, playerName: string): LaneMatchupRow[] {
  const player = board.players.find((item) => item.name === playerName)
  const side = player?.side === 'enemy' ? 'enemy' : 'own'
  const other = side === 'own' ? 'enemy' : 'own'
  const rows: LaneMatchupRow[] = []
  for (const game of board.games) {
    const mine = game[side].find((row) => row.name === playerName)
    if (!mine) continue
    const opponent = game[other].find((row) => row.lane === mine.lane)
    if (!opponent) continue
    const myGold = mine.gold
    const enemyGold = opponent.gold
    rows.push({
      game,
      ownHero: mine.hero,
      enemyHero: opponent.hero,
      enemyPlayer: opponent.name,
      goldDiff: isNum(myGold) && isNum(enemyGold) ? myGold - enemyGold : null,
      win: side === 'own' ? game.result === 'win' : game.result === 'loss'
    })
  }
  return rows.slice(0, 10)
}

export function sameLanePeers(board: PlayersBoard, lane: string, side: 'own' | 'enemy' = 'own'): BoardPlayer[] {
  return board.players
    .filter((player) => player.side === side && player.lane === lane)
    .sort((a, b) => (b.score || 0) - (a.score || 0) || b.games - a.games)
    .slice(0, 8)
}

export interface LaneGoldDiff {
  lane: string
  games: number
  ahead: number
  avgDiff: number | null
  rows: { day: string; diff: number; win: boolean }[]
}

/** 逐局同分路终局经济差；只统计同路各有一人的局。 */
export function laneGoldDiffs(board: PlayersBoard): LaneGoldDiff[] {
  return PLAYER_LANES.map((lane) => {
    const rows: LaneGoldDiff['rows'] = []
    for (const game of board.games) {
      const own = game.own.find((row) => row.lane === lane)
      const enemy = game.enemy.find((row) => row.lane === lane)
      if (!own || !enemy || !isNum(own.gold) || !isNum(enemy.gold)) continue
      rows.push({ day: game.day, diff: own.gold - enemy.gold, win: game.result === 'win' })
    }
    const ahead = rows.filter((row) => row.diff > 0).length
    return {
      lane,
      games: rows.length,
      ahead,
      avgDiff: rows.length ? rows.reduce((sum, row) => sum + row.diff, 0) / rows.length : null,
      rows
    }
  })
}

export function laneDepth(board: PlayersBoard) {
  return board.lanes.map((lane) => ({
    lane: lane.lane,
    games: lane.own.games,
    players: lane.own.players,
    perGame: lane.own.games ? lane.own.players / lane.own.games : null,
    ownWinRate: lane.own.winRate,
    enemyWinRate: lane.enemy.winRate,
    gpmDiff: isNum(lane.own.gpm) && isNum(lane.enemy.gpm) ? lane.own.gpm - lane.enemy.gpm : null
  }))
}


export function laneOrder<T extends { lane: string }>(lanes: T[]): T[] {
  return [...lanes].sort((a, b) => laneIndex(a.lane) - laneIndex(b.lane))
}

export interface CompareShared {
  sameTeam: number
  sameTeamWins: number
  versus: number
  aWins: number
  rows: { game: BoardGame; mode: 'team' | 'versus'; aWin: boolean }[]
}

export function sharedGames(board: PlayersBoard, a: string, b: string): CompareShared {
  const rows: CompareShared['rows'] = []
  let sameTeamWins = 0
  let aWins = 0
  for (const game of board.games) {
    const aOwn = game.own.some((row) => row.name === a)
    const bOwn = game.own.some((row) => row.name === b)
    const aEnemy = game.enemy.some((row) => row.name === a)
    const bEnemy = game.enemy.some((row) => row.name === b)
    if (aOwn && bOwn) {
      const win = game.result === 'win'
      if (win) sameTeamWins += 1
      rows.push({ game, mode: 'team', aWin: win })
    } else if ((aOwn && bEnemy) || (aEnemy && bOwn)) {
      const aWin = aOwn ? game.result === 'win' : game.result === 'loss'
      if (aWin) aWins += 1
      rows.push({ game, mode: 'versus', aWin })
    }
  }
  return {
    sameTeam: rows.filter((row) => row.mode === 'team').length,
    sameTeamWins,
    versus: rows.filter((row) => row.mode === 'versus').length,
    aWins,
    rows: rows.slice(0, 10)
  }
}

export interface StabilityStats {
  count: number
  min: number | null
  max: number | null
  median: number | null
  mean: number | null
  sd: number | null
  values: number[]
}

export function stability(player: BoardPlayer): StabilityStats {
  const values = (player.recent || []).map((game) => game.rating).filter(isNum).slice(0, 12)
  return {
    count: values.length,
    min: values.length ? Math.min(...values) : null,
    max: values.length ? Math.max(...values) : null,
    median: median(values),
    mean: mean(values),
    sd: stddev(values),
    values
  }
}

export function heroPool(player: BoardPlayer) {
  return [...(player.heroes || [])].sort((a, b) => b.games - a.games || (b.rating || 0) - (a.rating || 0))
}

export function playerCsv(players: BoardPlayer[]): string {
  const header = ['昵称', '阵营', '位置', '局数', '胜率%', 'KDA', 'MVP', '参团率%', '输出占比%', '经济占比%', '承伤占比%', '表现分']
  const lines = players.map((player) => [
    player.name,
    sideName(player.side),
    player.lane,
    player.games,
    player.winRate ?? '',
    player.kda ?? '',
    player.mvp,
    player.participation ?? '',
    player.damageShare ?? '',
    player.goldShare ?? '',
    player.takenShare ?? '',
    player.score ?? ''
  ])
  return [header, ...lines].map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\r\n')
}
