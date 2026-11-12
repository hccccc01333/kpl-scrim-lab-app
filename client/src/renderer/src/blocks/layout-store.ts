/**
 * 上帝模式 · 页面布局存储（v2）
 *
 * 每个页面有三套布局槽：全面 / 专业 / 自定义。
 * - 全面、专业是给全组用的预设（谁在哪个模式，就看到哪套布局）；
 * - 自定义是个人稿。
 * 布局只记「块顺序 / 显隐」，数据、结论仍由页面渲染。
 *
 * v1 -> v2 自动迁移：旧的可自定义布局归入「自定义」槽，不丢。
 */

export type LayoutMode = 'public' | 'pro' | 'custom'

export const LAYOUT_SCHEMA = 'kpl-page-layouts-v2'
const STORAGE_KEY = 'kpl:page-layouts:v2'
const LEGACY_KEY = 'kpl:page-layouts:v1'

export const MODE_LABELS: Record<LayoutMode, string> = {
  public: '全面',
  pro: '专业',
  custom: '自定义'
}

export type BlockConfigMap = Record<string, Record<string, unknown>>

export interface PageLayout {
  /** 用户自定义顺序；没列到的块按页面原顺序追加 */
  order: string[]
  /** 隐藏的块 id；隐藏后仍在块库里，可随时勾回来 */
  hidden: string[]
  /** 从分析库加到这一页的注册块（全局 id，如 match.recent） */
  extras: string[]
  /** 每个块实例的配置（超块的内容/展示/范围选项，随布局保存） */
  configs: BlockConfigMap
}

export type PageModes = Record<LayoutMode, PageLayout>

export interface LayoutState {
  schema: string
  mode: LayoutMode
  pages: Record<string, PageModes>
  updatedAt: string
}

const MODES: LayoutMode[] = ['public', 'pro', 'custom']

function emptyPage(): PageLayout {
  return { order: [], hidden: [], extras: [], configs: {} }
}

function emptyPageModes(): PageModes {
  return { public: emptyPage(), pro: emptyPage(), custom: emptyPage() }
}

function emptyState(): LayoutState {
  return {
    schema: LAYOUT_SCHEMA,
    mode: 'custom',
    pages: {},
    updatedAt: new Date().toISOString()
  }
}

function normalizePage(value: unknown): PageLayout {
  if (!value || typeof value !== 'object') return emptyPage()
  const raw = value as { order?: unknown; hidden?: unknown; extras?: unknown; configs?: unknown }
  const order = Array.isArray(raw.order) ? raw.order.filter((id): id is string => typeof id === 'string') : []
  const hidden = Array.isArray(raw.hidden) ? raw.hidden.filter((id): id is string => typeof id === 'string') : []
  const extras = Array.isArray(raw.extras) ? raw.extras.filter((id): id is string => typeof id === 'string') : []
  const configs: BlockConfigMap = {}
  if (raw.configs && typeof raw.configs === 'object') {
    for (const [id, value] of Object.entries(raw.configs as Record<string, unknown>)) {
      if (value && typeof value === 'object' && !Array.isArray(value)) configs[id] = { ...(value as Record<string, unknown>) }
    }
  }
  return { order: [...new Set(order)], hidden: [...new Set(hidden)], extras: [...new Set(extras)], configs }
}

function normalizeModes(value: unknown): PageModes {
  const modes = emptyPageModes()
  if (!value || typeof value !== 'object') return modes
  const raw = value as Record<string, unknown>
  // v1 形状：{ order, hidden } —— 归入自定义槽
  if ('order' in raw || 'hidden' in raw) {
    modes.custom = normalizePage(raw)
    return modes
  }
  for (const mode of MODES) {
    if (mode in raw) modes[mode] = normalizePage(raw[mode])
  }
  return modes
}

export function normalizeState(value: unknown): LayoutState {
  if (!value || typeof value !== 'object') return emptyState()
  const raw = value as { schema?: unknown; mode?: unknown; pages?: unknown; updatedAt?: unknown }
  const pages: Record<string, PageModes> = {}
  if (raw.pages && typeof raw.pages === 'object') {
    for (const [page, layout] of Object.entries(raw.pages as Record<string, unknown>)) {
      pages[page] = normalizeModes(layout)
    }
  }
  const mode = MODES.includes(raw.mode as LayoutMode) ? raw.mode as LayoutMode : 'custom'
  return {
    schema: LAYOUT_SCHEMA,
    mode,
    pages,
    updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : new Date().toISOString()
  }
}

function readStorage(key: string): unknown {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function load(): LayoutState {
  const current = readStorage(STORAGE_KEY)
  if (current) return normalizeState(current)
  const legacy = readStorage(LEGACY_KEY)
  if (legacy) return normalizeState(legacy)
  return emptyState()
}

let state: LayoutState = load()
const listeners = new Set<() => void>()

function commit(next: LayoutState): void {
  state = { ...next, updatedAt: new Date().toISOString() }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    /* 本地存储不可用时只影响持久化，不阻断使用 */
  }
  for (const listener of listeners) listener()
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function getSnapshot(): LayoutState {
  return state
}

export function getMode(): LayoutMode {
  return state.mode
}

export function setMode(mode: LayoutMode): void {
  if (state.mode === mode) return
  commit({ ...state, mode })
}

export function getPageLayout(page: string, mode: LayoutMode = state.mode): PageLayout {
  return state.pages[page]?.[mode] || emptyPage()
}

export function setPageLayout(page: string, patch: Partial<PageLayout>, mode: LayoutMode = state.mode): void {
  const current = state.pages[page] || emptyPageModes()
  const currentMode = current[mode] || emptyPage()
  const nextPage: PageModes = {
    ...emptyPageModes(),
    ...current,
    [mode]: {
      order: patch.order ? [...new Set(patch.order)] : currentMode.order,
      hidden: patch.hidden ? [...new Set(patch.hidden)] : currentMode.hidden,
      extras: patch.extras ? [...new Set(patch.extras)] : currentMode.extras,
      configs: patch.configs !== undefined ? patch.configs : currentMode.configs
    }
  }
  commit({ ...state, pages: { ...state.pages, [page]: nextPage } })
}

/** 写入某个块实例的配置（超块选项）。 */
export function setBlockConfig(page: string, blockId: string, config: Record<string, unknown>, mode: LayoutMode = state.mode): void {
  const current = getPageLayout(page, mode)
  setPageLayout(page, { configs: { ...current.configs, [blockId]: { ...(current.configs[blockId] || {}), ...config } } }, mode)
}

export function setPageOrder(page: string, order: string[], mode: LayoutMode = state.mode): void {
  setPageLayout(page, { order }, mode)
}

export function setBlockHidden(page: string, id: string, hidden: boolean, mode: LayoutMode = state.mode): void {
  const current = getPageLayout(page, mode)
  const nextHidden = hidden ? [...new Set([...current.hidden, id])] : current.hidden.filter((item) => item !== id)
  setPageLayout(page, { hidden: nextHidden }, mode)
}

/** 从分析库往页面加一个注册块。 */
export function addPageExtra(page: string, blockId: string, mode: LayoutMode = state.mode): void {
  const current = getPageLayout(page, mode)
  if (current.extras.includes(blockId)) return
  setPageLayout(page, { extras: [...current.extras, blockId] }, mode)
}

/** 从页面移除一个注册块（同时清掉它的顺序与隐藏记录）。 */
export function removePageExtra(page: string, blockId: string, mode: LayoutMode = state.mode): void {
  const current = getPageLayout(page, mode)
  const prefixed = `lib:${blockId}`
  setPageLayout(page, {
    extras: current.extras.filter((id) => id !== blockId),
    order: current.order.filter((id) => id !== prefixed),
    hidden: current.hidden.filter((id) => id !== prefixed)
  }, mode)
}

export function resetPage(page: string, mode: LayoutMode = state.mode): void {
  const pages = { ...state.pages }
  const current = pages[page]
  if (!current) return
  pages[page] = { ...current, [mode]: emptyPage() }
  commit({ ...state, pages })
}

/** 恢复所有页面的默认布局（三套槽全部清掉）。 */
export function resetAll(): void {
  commit({ ...state, pages: {} })
}

/** 已自定义过的页面数（任一模式有布局就算）。 */
export function customizedPageCount(): number {
  return Object.values(state.pages).filter((modes) =>
    MODES.some((mode) => modes[mode].order.length > 0 || modes[mode].hidden.length > 0 || modes[mode].extras.length > 0)
  ).length
}

/** 分享/导出：整份布局（含当前模式）。只含结构与顺序，不含任何数据。 */
export function exportBundle(): LayoutState {
  return normalizeState(JSON.parse(JSON.stringify(state)))
}

export interface ImportResult {
  applied: number
  skipped: number
}

/** 导入：合并（同页覆盖），不认识的页也保留，等以后有了该页再生效。 */
export function importBundle(value: unknown): ImportResult {
  const rawMode = value && typeof value === 'object' ? (value as { mode?: unknown }).mode : undefined
  const incoming = normalizeState(value)
  const pages = { ...state.pages }
  let applied = 0
  let skipped = 0
  for (const [page, modes] of Object.entries(incoming.pages)) {
    const hasAny = MODES.some((mode) => modes[mode].order.length || modes[mode].hidden.length || Object.keys(modes[mode].configs).length)
    if (!hasAny) { skipped += 1; continue }
    pages[page] = modes
    applied += 1
  }
  // 老分享码没有 mode：保持接收方当前模式，不被强行切走。
  const nextMode = MODES.includes(rawMode as LayoutMode) ? rawMode as LayoutMode : state.mode
  commit({ ...state, pages, mode: nextMode })
  return { applied, skipped }
}
