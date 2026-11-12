/**
 * 上帝模式 · 块级筛选
 *
 * 每个分析块可以声明自己支持哪些筛选（时间 / 对手 / 选手 / 英雄 / 阵营 / 赛果）。
 * 页面把「块数据 + 这些筛选值」接起来即可；筛选只影响这个块，不影响页面其它块。
 */

export type BlockFilterKey = 'range' | 'opponent' | 'player' | 'hero' | 'side' | 'result'

export interface BlockFilterValues {
  /** 0 = 全部，7/15/30/60/90 = 最近 N 天，-1 = 自定义日期区间 */
  range: number
  from: string
  to: string
  opponent: string
  player: string
  hero: string
  side: string
  result: string
}

export const EMPTY_BLOCK_FILTERS: BlockFilterValues = {
  range: 0,
  from: '',
  to: '',
  opponent: '',
  player: '',
  hero: '',
  side: '',
  result: ''
}

export interface BlockFilterOptions {
  opponents?: string[]
  players?: string[]
  heroes?: string[]
}

export const RANGE_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: '全部时间' },
  { value: 7, label: '近 7 天' },
  { value: 15, label: '近 15 天' },
  { value: 30, label: '近 30 天' },
  { value: 60, label: '近 60 天' },
  { value: 90, label: '近 90 天' },
  { value: -1, label: '自定义' }
]

export const SIDE_OPTIONS = [
  { value: '', label: '全部阵营' },
  { value: 'blue', label: '蓝方' },
  { value: 'red', label: '红方' }
]

export const RESULT_OPTIONS = [
  { value: '', label: '全部赛果' },
  { value: 'win', label: '胜' },
  { value: 'loss', label: '负' }
]

export const FILTER_LABELS: Record<BlockFilterKey, string> = {
  range: '时间',
  opponent: '对手',
  player: '选手',
  hero: '英雄',
  side: '阵营',
  result: '赛果'
}

export function activeFilterCount(values: BlockFilterValues | undefined): number {
  if (!values) return 0
  let count = 0
  if (values.range !== 0) count += 1
  if (values.from || values.to) count += 1
  if (values.opponent) count += 1
  if (values.player) count += 1
  if (values.hero) count += 1
  if (values.side) count += 1
  if (values.result) count += 1
  return count
}

function dayOf(text: string | null | undefined): string {
  return String(text || '').slice(0, 10)
}

function rollingStart(days: number): string {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  now.setDate(now.getDate() - Math.max(0, days - 1))
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** 日期（含时间）是否落在当前时间筛选里；没有日期时保留，避免误删数据。 */
export function dateInBlockRange(text: string | null | undefined, values: BlockFilterValues): boolean {
  const day = dayOf(text)
  if (!day) return true
  if (values.from && day < values.from) return false
  if (values.to && day > values.to) return false
  if (values.range > 0 && day < rollingStart(values.range)) return false
  return true
}

export function filterByRange<T>(list: T[], values: BlockFilterValues, getDate: (item: T) => string | null | undefined): T[] {
  if (values.range === 0 && !values.from && !values.to) return list
  return list.filter((item) => dateInBlockRange(getDate(item), values))
}
