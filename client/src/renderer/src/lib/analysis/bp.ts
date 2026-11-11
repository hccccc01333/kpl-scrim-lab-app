/**
 * BP 板块的共用计算：筛选、选禁计数、英雄透镜、阵营赛果、教练画像。
 * 口径固定为「本队 = bp-board 的 own」，对象战队是 enemy；不做禁选顺序推断。
 */

import type { BpBoard, BpGame } from '../types'

export const BP_SIDES = ['all', 'blue', 'red'] as const
export const BP_RESULTS = ['all', 'win', 'loss'] as const

export function isNum(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export interface BpFilters {
  opponent: string
  day: string
  side: string
  result: string
  hero: string
  range: number
}

export const EMPTY_FILTERS: BpFilters = {
  opponent: '',
  day: '',
  side: 'all',
  result: 'all',
  hero: '',
  range: 0
}

export function filterGames(games: BpGame[], filters: BpFilters): BpGame[] {
  const list = games.filter((game) => {
    if (filters.opponent && game.opponent !== filters.opponent) return false
    if (filters.day && game.day !== filters.day) return false
    if (filters.side !== 'all' && game.side !== filters.side) return false
    if (filters.result !== 'all' && game.result !== filters.result) return false
    if (filters.hero) {
      const heroes = [
        ...game.picks.own, ...game.picks.enemy,
        ...game.bans.own, ...game.bans.enemy
      ].map((entry) => entry.name)
      if (!heroes.includes(filters.hero)) return false
    }
    return true
  })
  const ranged = filters.range > 0 ? list.slice(0, filters.range) : list
  return [...ranged].sort((a, b) => b.start.localeCompare(a.start))
}

export interface BpCount {
  hero: string
  count: number
  share: number
  wins: number
  decided: number
  winRate: number | null
  icon?: string | null
  lane?: string | null
}

type PickSet = { name: string; icon?: string | null; lane?: string | null }

function count(games: BpGame[], select: (game: BpGame) => PickSet[], win: (game: BpGame) => boolean): BpCount[] {
  const map = new Map<string, { count: number; wins: number; decided: number; icon?: string | null; lane?: string | null }>()
  for (const game of games) {
    const seen = new Set<string>()
    for (const entry of select(game)) {
      if (!entry.name || seen.has(entry.name)) continue
      seen.add(entry.name)
      const row = map.get(entry.name) || { count: 0, wins: 0, decided: 0, icon: entry.icon, lane: entry.lane }
      row.count += 1
      if (game.result === 'win' || game.result === 'loss') {
        row.decided += 1
        if (win(game)) row.wins += 1
      }
      map.set(entry.name, row)
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
      icon: row.icon,
      lane: row.lane
    }))
    .sort((a, b) => b.count - a.count || (b.winRate || 0) - (a.winRate || 0))
}

export function pickBanCounts(games: BpGame[]) {
  return {
    ownPicks: count(games, (game) => game.picks.own, (game) => game.result === 'win'),
    ownBans: count(games, (game) => game.bans.own, (game) => game.result === 'win'),
    enemyPicks: count(games, (game) => game.picks.enemy, (game) => game.result === 'loss'),
    enemyBans: count(games, (game) => game.bans.enemy, (game) => game.result === 'loss')
  }
}

export interface HeroLensRow {
  game: BpGame
  role: '本方选用' | '对手选用' | '本方禁用' | '对手禁用'
  win: boolean | null
}

export function heroLens(games: BpGame[], hero: string): HeroLensRow[] {
  if (!hero) return []
  const rows: HeroLensRow[] = []
  for (const game of games) {
    if (game.picks.own.some((entry) => entry.name === hero)) rows.push({ game, role: '本方选用', win: game.result === 'win' })
    else if (game.picks.enemy.some((entry) => entry.name === hero)) rows.push({ game, role: '对手选用', win: game.result === 'loss' })
    else if (game.bans.own.some((entry) => entry.name === hero)) rows.push({ game, role: '本方禁用', win: null })
    else if (game.bans.enemy.some((entry) => entry.name === hero)) rows.push({ game, role: '对手禁用', win: null })
  }
  return rows
}

export interface BpCombo {
  heroes: string[]
  games: number
  wins: number
  winRate: number | null
  small: boolean
}

export function comboRows(games: BpGame[], side: 'own' | 'enemy', size: 2 | 3): BpCombo[] {
  const map = new Map<string, { games: number; wins: number }>()
  for (const game of games) {
    const heroes = [...new Set(game.picks[side].map((entry) => entry.name))].sort()
    const win = side === 'own' ? game.result === 'win' : game.result === 'loss'
    for (let i = 0; i < heroes.length; i++) {
      for (let j = i + 1; j < heroes.length; j++) {
        if (size === 3) {
          for (let k = j + 1; k < heroes.length; k++) {
            addCombo(map, [heroes[i], heroes[j], heroes[k]].join('|'), win)
          }
        } else {
          addCombo(map, [heroes[i], heroes[j]].join('|'), win)
        }
      }
    }
  }
  return [...map.entries()]
    .map(([key, row]) => ({
      heroes: key.split('|'),
      games: row.games,
      wins: row.wins,
      winRate: row.games ? row.wins / row.games * 100 : null,
      small: row.games < 3
    }))
    .sort((a, b) => b.games - a.games || (b.winRate || 0) - (a.winRate || 0))
    .slice(0, 8)
}

function addCombo(map: Map<string, { games: number; wins: number }>, key: string, win: boolean) {
  const row = map.get(key) || { games: 0, wins: 0 }
  row.games += 1
  if (win) row.wins += 1
  map.set(key, row)
}

export interface SideCell {
  side: 'blue' | 'red'
  result: 'win' | 'loss'
  games: number
  wins: number
  share: number
}

export function sideResult(games: BpGame[]): SideCell[] {
  const cells: SideCell[] = [
    { side: 'blue', result: 'win', games: 0, wins: 0, share: 0 },
    { side: 'blue', result: 'loss', games: 0, wins: 0, share: 0 },
    { side: 'red', result: 'win', games: 0, wins: 0, share: 0 },
    { side: 'red', result: 'loss', games: 0, wins: 0, share: 0 }
  ]
  for (const game of games) {
    if (game.result !== 'win' && game.result !== 'loss') continue
    const cell = cells.find((item) => item.side === game.side && item.result === game.result)
    if (cell) {
      cell.games += 1
      if (game.result === 'win') cell.wins += 1
    }
  }
  const total = Math.max(1, cells.reduce((sum, cell) => sum + cell.games, 0))
  return cells.map((cell) => ({ ...cell, share: cell.games / total * 100 }))
}

export interface DayBucket {
  day: string
  games: number
  wins: number
  winRate: number | null
}

export function dayBuckets(games: BpGame[]): DayBucket[] {
  const map = new Map<string, { games: number; wins: number }>()
  for (const game of games) {
    const row = map.get(game.day) || { games: 0, wins: 0 }
    row.games += 1
    if (game.result === 'win') row.wins += 1
    map.set(game.day, row)
  }
  return [...map.entries()]
    .map(([day, row]) => ({ day, games: row.games, wins: row.wins, winRate: row.games ? row.wins / row.games * 100 : null }))
    .sort((a, b) => a.day.localeCompare(b.day))
}

/* ── 教练画像 ─────────────────────────────────────────────────────── */

export interface CoachRecord {
  coach: string
  teamId: string
  teamName: string
  games: number
  wins: number
  losses: number
  winRate: number | null
}

export function coachRecords(board: BpBoard): CoachRecord[] {
  return board.teams
    .map((team) => {
      const games = board.games.filter((game) => game.teamId === team.id)
      const wins = games.filter((game) => game.result === 'loss').length
      const losses = games.filter((game) => game.result === 'win').length
      return {
        coach: team.coach || '未录入',
        teamId: team.id,
        teamName: team.name,
        games: wins + losses,
        wins,
        losses,
        winRate: wins + losses ? wins / (wins + losses) * 100 : null
      }
    })
    .sort((a, b) => b.games - a.games || b.wins - a.wins)
}

export interface CoachProfile {
  record: CoachRecord | null
  games: BpGame[]
  picks: BpCount[]
  bans: BpCount[]
  allPicks: BpCount[]
  allBans: BpCount[]
  pickRank: number | null
  banRank: number | null
  sides: { side: 'blue' | 'red'; label: string; games: number; wins: number; winRate: number | null }[]
  latest: BpGame | null
  banHits: number
  banCount: number
  lanePicks: { lane: string; hero: string; count: number }[]
  laneMatchup: { lane: string; coachHero: string; ownHero: string; heatCoach: number; heatOwn: number; diff: number }[]
  scatter: { coach: string; pickHeat: number; banHeat: number; teamId: string }[]
}

export function coachProfile(board: BpBoard, coach: string): CoachProfile {
  const team = board.teams.find((item) => item.coach === coach) || null
  const games = team ? board.games.filter((game) => game.teamId === team.id) : []
  const wins = games.filter((game) => game.result === 'loss').length
  const losses = games.filter((game) => game.result === 'win').length
  const picks = count(games, (game) => game.picks.enemy, (game) => game.result === 'loss')
  const bans = count(games, (game) => game.bans.enemy, (game) => game.result === 'loss')
  const allPicks = count(board.games, (game) => game.picks.enemy, (game) => game.result === 'loss')
  const allBans = count(board.games, (game) => game.bans.enemy, (game) => game.result === 'loss')
  const pickRank = picks[0] ? allPicks.findIndex((row) => row.hero === picks[0].hero) + 1 : null
  const banRank = bans[0] ? allBans.findIndex((row) => row.hero === bans[0].hero) + 1 : null
  const sideStats = (['blue', 'red'] as const).map((side) => {
    if (!team) return { side, label: side === 'blue' ? '蓝方' : '红方', games: 0, wins: 0, winRate: null }
    const rows = games.filter((game) => (game.side === 'blue' ? 'red' : 'blue') === side)
    const sideWins = rows.filter((game) => game.result === 'loss').length
    const decided = rows.filter((game) => game.result === 'win' || game.result === 'loss').length
    return {
      side,
      label: side === 'blue' ? '蓝方' : '红方',
      games: rows.length,
      wins: sideWins,
      winRate: decided ? sideWins / decided * 100 : null
    }
  })
  const latest = [...games].sort((a, b) => b.start.localeCompare(a.start))[0] || null
  const pickHeatMap = new Map(picks.map((row) => [row.hero, row.count]))
  const banCount = latest?.bans.enemy.length || 0
  const banHits = latest
    ? latest.bans.enemy.filter((entry) => (pickHeatMap.get(entry.name) || 0) > 0).length
    : 0
  const laneMap = new Map<string, { lane: string; hero: string; count: number }>()
  for (const game of games) {
    for (const entry of game.picks.enemy) {
      if (!entry.lane) continue
      const key = `${entry.lane}-${entry.name}`
      const row = laneMap.get(key) || { lane: entry.lane, hero: entry.name, count: 0 }
      row.count += 1
      laneMap.set(key, row)
    }
  }
  const lanePicksMap = new Map<string, { lane: string; hero: string; count: number }>()
  for (const row of [...laneMap.values()].sort((a, b) => b.count - a.count)) {
    const lane = row.lane
    if (!lanePicksMap.has(lane)) lanePicksMap.set(lane, row)
  }
  const laneMatchup = latest
    ? latest.picks.enemy
      .filter((entry) => entry.lane)
      .map((entry) => {
        const own = latest.picks.own.find((item) => item.lane === entry.lane)
        const coachHeat = pickHeatMap.get(entry.name) || 0
        const ownHeat = own ? (pickHeatMap.get(own.name) || 0) : 0
        return { lane: entry.lane || '', coachHero: entry.name, ownHero: own?.name || '—', heatCoach: coachHeat, heatOwn: ownHeat, diff: coachHeat - ownHeat }
      })
    : []
  const coaches = coachRecords(board)
  const globalPickHeat = new Map(allPicks.map((row) => [row.hero, row.count]))
  const globalBanHeat = new Map(allBans.map((row) => [row.hero, row.count]))
  const scatter = coaches.map((row) => {
    const teamGames = board.games.filter((game) => game.teamId === row.teamId)
    const games = Math.max(1, teamGames.length)
    const pickHeat = teamGames.reduce((total, game) =>
      total + game.picks.enemy.reduce((sum, entry) => sum + (globalPickHeat.get(entry.name) || 0), 0), 0) / games
    const banHeat = teamGames.reduce((total, game) =>
      total + game.bans.enemy.reduce((sum, entry) => sum + (globalBanHeat.get(entry.name) || 0), 0), 0) / games
    return { coach: row.coach, pickHeat, banHeat, teamId: row.teamId }
  })
  return {
    record: team
      ? { coach, teamId: team.id, teamName: team.name, games: wins + losses, wins, losses,
          winRate: wins + losses ? wins / (wins + losses) * 100 : null }
      : null,
    games,
    picks,
    bans,
    allPicks,
    allBans,
    pickRank,
    banRank,
    sides: sideStats,
    latest,
    banHits,
    banCount,
    lanePicks: [...lanePicksMap.values()],
    laneMatchup,
    scatter
  }
}
