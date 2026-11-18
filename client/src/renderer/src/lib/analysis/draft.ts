/**
 * 征召模式 · BP 手序模型
 *
 * 数据口径：分析数据 left = 蓝方，right = 红方；营地采集的 banHeros/pickHeros
 * 数组顺序就是该侧的禁选顺序（空 ban 位置保留，不压缩）。
 *
 * 模板（按 ruleProfile 优先，其次双方 ban 数量自动识别）：
 * 1. draft-18：禁① 蓝红蓝红 → 选① 6 手 → 禁② 红蓝红蓝 → 选② 4 手（征召；KPL 2024 夏季赛前）
 * 2. draft-20：禁① 蓝红蓝红 → 选① 6 手 → 禁② 红蓝红蓝红蓝 → 选② 4 手（KPL 2024 年度总决赛起）
 * 3. rank-20：5+5 同时禁用 + 10 选（排位/巅峰；Ban 无全局先后）
 * 4. blind：巅峰对决，无 Ban、双方盲选 5
 * 5. legacy-20：旧口径 10 Ban + 10 选，只用于历史记录
 */
export type DraftSide = 'blue' | 'red'
export type DraftPhase = 'ban' | 'pick'

export interface DraftSlot {
  /** 全局第几手（从 1 开始） */
  order: number
  /** 属于哪一段（禁用①/选用①…） */
  segment: string
  phase: DraftPhase
  side: DraftSide
  /** 该侧第几个；空 ban 留空串 */
  hero: string
}

export interface DraftSegment {
  label: string
  phase: DraftPhase
  slots: DraftSlot[]
}

export interface DraftSource {
  bans?: { left?: string[]; right?: string[] }
  picks?: { left?: string[]; right?: string[] }
  /** 保留空位的槽位数组：null（或空串）= 空 ban；优先于压缩后的 bans/picks */
  banSlots?: { left?: (string | null)[]; right?: (string | null)[] }
  pickSlots?: { left?: (string | null)[]; right?: (string | null)[] }
  pickOrderKnown?: boolean
  ruleProfile?: string
  firstPick?: string | null
}

interface SegmentDef {
  label: string
  phase: DraftPhase
  actions: DraftSide[]
}

interface DraftTemplate {
  id: 'draft-18' | 'draft-20' | 'rank-20' | 'blind' | 'legacy-20'
  label: string
  segments: SegmentDef[]
}

const B: DraftSide = 'blue'
const R: DraftSide = 'red'

const DRAFT18: DraftTemplate = {
  id: 'draft-18',
  label: '征召 · 4 Ban + 5 Pick（18 手）',
  segments: [
    { label: '禁用 ①', phase: 'ban', actions: [B, R, B, R] },
    { label: '选用 ①', phase: 'pick', actions: [B, R, R, B, B, R] },
    { label: '禁用 ②', phase: 'ban', actions: [R, B, R, B] },
    { label: '选用 ②', phase: 'pick', actions: [R, B, B, R] }
  ]
}

const DRAFT20: DraftTemplate = {
  id: 'draft-20',
  label: 'KPL · 5 Ban + 5 Pick（20 手）',
  segments: [
    { label: '禁用 ①', phase: 'ban', actions: [B, R, B, R] },
    { label: '选用 ①', phase: 'pick', actions: [B, R, R, B, B, R] },
    { label: '禁用 ②', phase: 'ban', actions: [R, B, R, B, R, B] },
    { label: '选用 ②', phase: 'pick', actions: [R, B, B, R] }
  ]
}

const RANK20: DraftTemplate = {
  id: 'rank-20',
  label: '排位/巅峰 · 5+5 同时 Ban + 10 选',
  segments: [
    { label: '禁用（同时）', phase: 'ban', actions: [B, B, B, B, B, R, R, R, R, R] },
    { label: '选用', phase: 'pick', actions: [B, R, R, B, B, R, R, B, B, R] }
  ]
}

const BLIND: DraftTemplate = {
  id: 'blind',
  label: '巅峰对决 · 双方盲选 5',
  segments: [
    { label: '盲选', phase: 'pick', actions: [B, R, R, B, B, R, R, B, B, R] }
  ]
}

const LEGACY20: DraftTemplate = {
  id: 'legacy-20',
  label: '旧口径 · 10 Ban + 10 选',
  segments: [
    { label: '禁用', phase: 'ban', actions: [B, R, B, R, B, R, B, R, B, R] },
    { label: '选用', phase: 'pick', actions: [B, R, R, B, B, R, R, B, B, R] }
  ]
}

export function sideLabel(side: DraftSide): string {
  return side === 'blue' ? '蓝' : '红'
}

function banCounts(source: DraftSource): { blue: number; red: number } {
  return {
    blue: (source.bans?.left || []).filter(Boolean).length,
    red: (source.bans?.right || []).filter(Boolean).length
  }
}

/** 先看 ruleProfile，再按双方 ban 数量兜底；不再默认 20 手训练赛。 */
export function detectTemplate(source: DraftSource): DraftTemplate {
  const { blue, red } = banCounts(source)
  const profile = String(source.ruleProfile || '')
  const minBans = Math.min(blue, red)
  if (profile === 'rank-20') return RANK20
  if (profile === 'draft-20') return DRAFT20
  if (profile === 'draft-18') return DRAFT18
  if (profile === 'blind') return BLIND
  if (profile === 'scrim-global-20') return LEGACY20
  if (profile === 'kpl-recorded') return minBans >= 5 ? DRAFT20 : DRAFT18
  if (minBans >= 5) return RANK20
  if (minBans >= 4) return DRAFT18
  if (blue + red >= 9) return DRAFT20
  return DRAFT18
}

/** 按模板把两侧名单填进手序槽位；空 ban 占位，不压缩后面的位置。 */
export function buildDraftSegments(source: DraftSource): { template: DraftTemplate; segments: DraftSegment[] } {
  const template = detectTemplate(source)
  const compactBans: Record<DraftSide, string[]> = {
    blue: source.bans?.left || [],
    red: source.bans?.right || []
  }
  const compactPicks: Record<DraftSide, string[]> = {
    blue: source.picks?.left || [],
    red: source.picks?.right || []
  }
  const listOf = (phase: DraftPhase, side: DraftSide): (string | null)[] => {
    if (phase === 'ban') {
      const slots = source.banSlots?.[side === 'blue' ? 'left' : 'right']
      return slots && slots.length ? slots : compactBans[side]
    }
    const slots = source.pickSlots?.[side === 'blue' ? 'left' : 'right']
    return slots && slots.length ? slots : compactPicks[side]
  }
  const counters: Record<DraftPhase, Record<DraftSide, number>> = {
    ban: { blue: 0, red: 0 },
    pick: { blue: 0, red: 0 }
  }
  let order = 0
  const segments = template.segments.map((segment) => {
    const slots: DraftSlot[] = segment.actions.map((side) => {
      order += 1
      const list = listOf(segment.phase, side)
      const value = list[counters[segment.phase][side]]
      counters[segment.phase][side] += 1
      const hero = value === null || value === undefined ? '' : String(value)
      return { order, segment: segment.label, phase: segment.phase, side, hero }
    })
    return { label: segment.label, phase: segment.phase, slots }
  })
  return { template, segments }
}

/** 兼容旧调用：只要扁平槽位列表。 */
export function buildDraftSlots(source: DraftSource): DraftSlot[] {
  return buildDraftSegments(source).segments.flatMap((segment) => segment.slots)
}

/** 选人是否完整（双方各 5 个）。 */
export function isCompleteDraft(source: DraftSource): boolean {
  return (source.picks?.left || []).filter(Boolean).length === 5
    && (source.picks?.right || []).filter(Boolean).length === 5
}

/** 首 ban 位（蓝方第一 ban）；空 ban 占位时返回空串。 */
export function firstBanHero(source: DraftSource): string {
  const slots = source.banSlots?.left
  if (slots && slots.length) return slots[0] || ''
  return (source.bans?.left || [])[0] || ''
}
