import { createContext, useContext } from 'react'

/**
 * 块页面上下文：让“本局 BP 纸”“该选手对位”这类需要页面对象的注册块，
 * 加到单局 / 选手 / 英雄 / 战队详情页时自动知道自己在哪一页。
 */
export interface BlockPageContext {
  page: string
  matchKey?: string
  player?: string
  team?: string
  hero?: string
  reportId?: string
}

export const EMPTY_PAGE_CONTEXT: BlockPageContext = { page: '' }

export const BlockPageContextValue = createContext<BlockPageContext>(EMPTY_PAGE_CONTEXT)

export function useBlockPageContext(): BlockPageContext {
  return useContext(BlockPageContextValue)
}

const MODULE_PATHS = new Set(['cross', 'query', 'featured', 'records', 'versions', 'archive', 'lanes', 'compare', 'bp', 'team', 'coach', 'effect', 'sessions', 'reports', 'weekly'])

function decode(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

/** 从路由还原页面上下文；块据此决定要不要显示内容。 */
export function pageContextFromPath(pathname: string): BlockPageContext {
  const parts = pathname.split('/').filter(Boolean)
  const [first, second] = parts
  if (!first) return { page: 'overview' }
  if (first === 'matches') {
    if (!second || MODULE_PATHS.has(second)) return { page: 'matches' }
    return { page: 'match', matchKey: decode(parts.slice(1).join('/')) }
  }
  if (first === 'players') {
    if (!second || MODULE_PATHS.has(second)) return { page: 'players' }
    return { page: 'player', player: decode(second) }
  }
  if (first === 'teams') {
    if (!second || MODULE_PATHS.has(second)) return { page: 'teams' }
    return { page: 'team', team: decode(second) }
  }
  if (first === 'heroes') {
    if (!second || MODULE_PATHS.has(second)) return { page: 'heroes' }
    return { page: 'hero', hero: decode(second) }
  }
  if (first === 'training') {
    if (second === 'reports' && parts[2]) return { page: 'report', reportId: decode(parts[2]) }
    return { page: 'training' }
  }
  if (first === 'bp') return { page: 'bp' }
  if (first === 'studio') return { page: 'studio' }
  return { page: first }
}
