import { useQuery } from '@tanstack/react-query'
import { useConnection } from '../lib/app-context'
import { api } from '../lib/api'
import type { BpBoard } from '../lib/types'
import type { BlockFilterOptions } from './filters'

/**
 * 通用筛选选项：注册块被加到任意页面时，页面未必自带对手/选手/英雄列表。
 * 这里统一从 bp-board 取（与各页 useBpBoard 同一个 queryKey，会复用缓存）。
 */
export function useGlobalBlockFilterOptions(active: boolean): BlockFilterOptions {
  const { baseUrl } = useConnection()
  const query = useQuery({
    queryKey: ['bp-board', baseUrl],
    queryFn: () => api<BpBoard>(baseUrl, '/api/v3/bp-board', { timeout: 60_000 }),
    enabled: active && Boolean(baseUrl),
    staleTime: 2 * 60_000,
    retry: 1,
    refetchOnWindowFocus: false
  })
  const games = query.data?.games || []
  const opponents = [...new Set(games.map((game) => game.opponent).filter(Boolean))].sort()
  const players = [...new Set(games.flatMap((game) => [...game.players.own, ...game.players.enemy]))].sort()
  const heroes = [...new Set([
    ...(query.data?.heroMeta ? Object.keys(query.data.heroMeta) : []),
    ...games.flatMap((game) => [...game.picks.own, ...game.picks.enemy, ...game.bans.own, ...game.bans.enemy].map((entry) => entry.name))
  ])].sort()
  return { opponents, players, heroes }
}

export function mergeFilterOptions(base: BlockFilterOptions, fallback: BlockFilterOptions): BlockFilterOptions {
  return {
    opponents: base.opponents?.length ? base.opponents : fallback.opponents,
    players: base.players?.length ? base.players : fallback.players,
    heroes: base.heroes?.length ? base.heroes : fallback.heroes
  }
}
