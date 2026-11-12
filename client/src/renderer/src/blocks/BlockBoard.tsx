/**
 * 上帝模式 · 块容器
 *
 * 页面把内联分析块包成 <Block id title filters?>，外层套 <BlockBoard page filterOptions>；
 * 注册块（分析库里的自治块）通过 layout.extras 加到页面上，同样由 BlockBoard 渲染。
 *
 * BlockBoard 负责：显隐、拖拽排序、恢复默认、块级筛选、分析库、分享/导入、三套模式。
 */
import {
  Fragment,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode
} from 'react'
import { Icon } from '../components/Icon'
import {
  MODE_LABELS,
  getSnapshot,
  removePageExtra,
  resetPage,
  setBlockConfig,
  setBlockHidden,
  setPageOrder,
  subscribe
} from './layout-store'
import { getPresetLayout, hasLayoutContent } from './presets'
import {
  EMPTY_BLOCK_FILTERS,
  type BlockFilterKey,
  type BlockFilterOptions,
  type BlockFilterValues
} from './filters'
import { BlockFilterContext, useBlockFilter } from './filter-context'
import { BlockFilterBar } from './BlockFilterBar'
import { BlockLibrary } from './BlockLibrary'
import { ShareDialog } from './ShareDialog'
import { getRegisteredBlock, type BlockOptions, type RegisteredBlock } from './registry'
import { mergeFilterOptions, useGlobalBlockFilterOptions } from './filter-options'

export { useBlockFilter }

export function Block({
  id: _id,
  title: _title,
  filters: _filters,
  children
}: {
  id: string
  title?: string
  /** 声明这个块支持哪些筛选；页面用函数子节点接收筛选值 */
  filters?: BlockFilterKey[]
  children: ReactNode | ((values: BlockFilterValues) => ReactNode)
}) {
  const values = useBlockFilter()
  return <>{typeof children === 'function' ? children(values) : children}</>
}

interface BlockItem {
  id: string
  title: string
  filters: BlockFilterKey[]
  node: ReactNode
  /** 注册块的全局 id（用于从本页移除） */
  extraId?: string
  /** 注册块定义（有 options 时显示配置按钮） */
  definition?: RegisteredBlock
}

function resolveOptions(definition: RegisteredBlock, config: Record<string, unknown> | undefined): BlockOptions {
  const resolved: BlockOptions = {}
  for (const field of definition.options || []) {
    const value = config?.[field.key]
    resolved[field.key] = (value as string | number | boolean | undefined) ?? field.default
  }
  return resolved
}

function BlockConfigDialog({
  definition,
  values,
  onChange,
  onClose
}: {
  definition: RegisteredBlock
  values: Record<string, unknown>
  onChange: (patch: Record<string, unknown>) => void
  onClose: () => void
}) {
  return (
    <div className="god-config-backdrop" role="dialog" aria-modal="true">
      <div className="god-config-panel">
        <header>
          <b>配置 · {definition.title}</b>
          <button type="button" onClick={onClose}>完成</button>
        </header>
        <p className="god-config-note">配置随布局保存；专业模式会作为组内默认，全面模式按个人布局保存。</p>
        <div className="god-config-fields">
          {(definition.options || []).map((field) => {
            const raw = values[field.key]
            const value = raw !== undefined ? raw : field.default
            if (field.type === 'toggle') {
              return (
                <label key={field.key} className="god-config-row">
                  <span>{field.label}</span>
                  <input
                    type="checkbox"
                    checked={Boolean(value)}
                    onChange={(event) => onChange({ [field.key]: event.target.checked })}
                  />
                </label>
              )
            }
            if (field.type === 'number') {
              return (
                <label key={field.key} className="god-config-row">
                  <span>{field.label}</span>
                  <input
                    type="number"
                    min={field.min}
                    max={field.max}
                    step={field.step}
                    value={Number(value)}
                    onChange={(event) => onChange({ [field.key]: Number(event.target.value) })}
                  />
                </label>
              )
            }
            return (
              <label key={field.key} className="god-config-row">
                <span>{field.label}</span>
                <select value={String(value ?? '')} onChange={(event) => onChange({ [field.key]: event.target.value })}>
                  {(field.options || []).map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function collectBlocks(children: ReactNode): BlockItem[] {
  const items: BlockItem[] = []
  const visit = (node: ReactNode): void => {
    if (node === null || node === undefined || typeof node === 'boolean') return
    if (Array.isArray(node)) {
      for (const child of node) visit(child)
      return
    }
    if (!node || typeof node !== 'object' || !('type' in node)) return
    const element = node as {
      type: unknown
      props: { children?: ReactNode; id?: unknown; title?: unknown; filters?: unknown }
    }
    if (element.type === Fragment) {
      visit(element.props.children)
      return
    }
    if (element.type !== Block) return
    const id = typeof element.props.id === 'string' ? element.props.id : ''
    if (!id) return
    const filters = Array.isArray(element.props.filters)
      ? (element.props.filters as BlockFilterKey[])
      : []
    items.push({
      id,
      title: typeof element.props.title === 'string' && element.props.title ? element.props.title : id,
      filters,
      node: node as ReactNode
    })
  }
  visit(children)
  return items
}

function mergeOrder(order: string[], ids: string[]): string[] {
  const known = new Set(ids)
  const ordered = order.filter((id) => known.has(id))
  const seen = new Set(ordered)
  for (const id of ids) if (!seen.has(id)) ordered.push(id)
  return ordered
}

export function BlockBoard({
  page,
  children,
  filterOptions = {},
  allowEmpty = false
}: {
  page: string
  children?: ReactNode
  filterOptions?: BlockFilterOptions
  /** 允许空白页（「我的看板」）：没有内联块时也能从分析库加块 */
  allowEmpty?: boolean
}) {
  const store = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  const mode = store.mode
  const storedLayout = store.pages[page]?.[mode]
  const presetLayout = mode === 'pro' ? getPresetLayout(page) : undefined
  const layout = !hasLayoutContent(storedLayout) && presetLayout ? presetLayout : storedLayout
  const inlineBlocks = useMemo(() => collectBlocks(children), [children])
  const extraBlocks = useMemo<BlockItem[]>(() => {
    const items: BlockItem[] = []
    for (const id of layout?.extras || []) {
      const definition = getRegisteredBlock(id)
      if (!definition) continue
      const Component = definition.Component
      const itemId = `lib:${id}`
      const options = resolveOptions(definition, layout?.configs?.[itemId])
      items.push({
        id: itemId,
        title: definition.title,
        filters: definition.filters,
        node: <Component options={options} />,
        extraId: id,
        definition
      })
    }
    return items
  }, [layout])
  const blocks = useMemo(() => [...inlineBlocks, ...extraBlocks], [inlineBlocks, extraBlocks])
  const ids = useMemo(() => blocks.map((block) => block.id), [blocks])
  const order = useMemo(() => mergeOrder(layout?.order || [], ids), [layout, ids])
  const hidden = useMemo(() => {
    const known = new Set(ids)
    const raw = layout?.hidden || []
    const hideInline = raw.includes('*')
    const next = new Set(raw.filter((id) => id !== '*' && known.has(id)))
    if (hideInline) for (const id of ids) if (!id.startsWith('lib:')) next.add(id)
    return next
  }, [layout, ids])
  const byId = useMemo(() => new Map(blocks.map((block) => [block.id, block])), [blocks])
  const needExtraFilterOptions = blocks.some((block) =>
    block.extraId ? block.filters.some((key) => key === 'opponent' || key === 'player' || key === 'hero') : false)
  const fallbackFilterOptions = useGlobalBlockFilterOptions(needExtraFilterOptions)
  const mergedFilterOptions = useMemo(
    () => mergeFilterOptions(filterOptions, fallbackFilterOptions),
    [filterOptions, fallbackFilterOptions]
  )

  const [editing, setEditing] = useState(false)
  const [dragId, setDragId] = useState('')
  const [dropId, setDropId] = useState('')
  const [dialog, setDialog] = useState<'share' | 'import' | null>(null)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [blockFilters, setBlockFilters] = useState<Record<string, BlockFilterValues>>({})
  const [configId, setConfigId] = useState<string | null>(null)

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2400)
    return () => window.clearTimeout(timer)
  }, [notice])

  // 没接入任何块的普通页面：原样渲染，避免迁移期间白屏。
  if (!blocks.length && !allowEmpty) return <>{children}</>

  // 保存顺序时保留其它页签/未挂载块的顺序记录（决策台等页签页共用同一 page slug）。
  const commitOrder = (next: string[]) => {
    const mounted = new Set(ids)
    const preserved = (layout?.order || []).filter((id) => !mounted.has(id))
    setPageOrder(page, [...next, ...preserved], mode)
  }

  const move = (id: string, delta: number) => {
    const index = order.indexOf(id)
    const target = index + delta
    if (index < 0 || target < 0 || target >= order.length) return
    const next = [...order]
    next.splice(index, 1)
    next.splice(target, 0, id)
    commitOrder(next)
  }

  const reorder = (from: string, to: string) => {
    if (!from || !to || from === to) return
    const next = order.filter((id) => id !== from)
    const target = next.indexOf(to)
    next.splice(target < 0 ? next.length : target, 0, from)
    commitOrder(next)
  }

  const filtersOf = (id: string): BlockFilterValues => blockFilters[id] || EMPTY_BLOCK_FILTERS
  const updateFilter = (id: string, patch: Partial<BlockFilterValues>) => {
    setBlockFilters((current) => ({ ...current, [id]: { ...(current[id] || EMPTY_BLOCK_FILTERS), ...patch } }))
  }
  const clearFilter = (id: string) => {
    setBlockFilters((current) => ({ ...current, [id]: { ...EMPTY_BLOCK_FILTERS } }))
  }

  const renderFilterBar = (item: BlockItem) => {
    if (!item.filters.length) return null
    return (
      <BlockFilterBar
        keys={item.filters}
        options={mergedFilterOptions}
        values={filtersOf(item.id)}
        onChange={(patch) => updateFilter(item.id, patch)}
        onClear={() => clearFilter(item.id)}
      />
    )
  }

  const library = (
    <BlockLibrary
      open={libraryOpen}
      onClose={() => setLibraryOpen(false)}
      page={page}
      mode={mode}
      existing={layout?.extras || []}
      onAdded={(title) => {
        setNotice(`已加入：${title}`)
        setLibraryOpen(false)
      }}
    />
  )

  const emptyState = blocks.length === 0 ? (
    <div className="god-empty">
      <b>这一页还空着</b>
      <p>从分析库挑块，自己拼一页。每个块自带数据和口径，加进来就能看。</p>
      <button type="button" className="btn btn-primary" onClick={() => setLibraryOpen(true)}>打开分析库</button>
    </div>
  ) : null

  if (!editing) {
    return (
      <div className="god-board">
        <div className="god-toolbar is-quiet">
          {notice ? <span className="god-notice">{notice}</span> : null}
          {allowEmpty ? (
            <button type="button" className="god-edit-btn" onClick={() => setLibraryOpen(true)}>
              <Icon name="spark" size={14} /> 分析库
            </button>
          ) : null}
          <button type="button" className="god-edit-btn" onClick={() => setEditing(true)}>
            <Icon name="layout" size={14} />
            自定义布局
          </button>
        </div>
        {emptyState}
        {order.filter((id) => !hidden.has(id)).map((id) => {
          const item = byId.get(id)
          if (!item) return null
          const values = filtersOf(id)
          return (
            <div className="god-block" key={id}>
              {renderFilterBar(item)}
              <BlockFilterContext.Provider value={values}>{item.node}</BlockFilterContext.Provider>
            </div>
          )
        })}
        {library}
      </div>
    )
  }

  return (
    <div className="god-board is-editing">
      <div className="god-toolbar is-editing">
        <span className="god-hint">
          <b className="god-mode-tag">{MODE_LABELS[mode]}模式</b>
          拖动排序 · 眼睛控制显隐 · 隐藏的块仍保留，随时可以勾回来
        </span>
        {notice ? <span className="god-notice">{notice}</span> : null}
        <div className="god-actions">
          <button type="button" className="btn btn-sm" onClick={() => setLibraryOpen(true)}><Icon name="spark" size={14} /> 分析库</button>
          <button type="button" className="btn btn-sm" onClick={() => setDialog('import')}>导入布局</button>
          <button type="button" className="btn btn-sm" onClick={() => setDialog('share')}><Icon name="share" size={14} /> 分享</button>
          <button type="button" className="btn btn-sm" onClick={() => { resetPage(page, mode); setNotice(`已恢复本页${MODE_LABELS[mode]}默认布局`) }}><Icon name="refresh" size={14} /> 恢复默认</button>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setEditing(false)}><Icon name="check" size={14} /> 完成</button>
        </div>
      </div>
      {emptyState}
      {order.map((id, index) => {
        const item = byId.get(id)
        if (!item) return null
        const values = filtersOf(id)
        return (
          <div
            className={`god-block is-editing${hidden.has(id) ? ' is-hidden' : ''}${dragId === id ? ' is-dragging' : ''}${dropId === id && dragId !== id ? ' is-drop' : ''}`}
            key={id}
            onDragOver={(event) => {
              if (!dragId || dragId === id) return
              event.preventDefault()
              event.dataTransfer.dropEffect = 'move'
              if (dropId !== id) setDropId(id)
            }}
            onDrop={(event) => {
              event.preventDefault()
              reorder(dragId, id)
              setDragId('')
              setDropId('')
            }}
          >
            <div className="god-block-bar">
              <button
                type="button"
                className="god-grip"
                title="按住拖动排序"
                draggable
                onDragStart={(event) => {
                  setDragId(id)
                  event.dataTransfer.effectAllowed = 'move'
                  event.dataTransfer.setData('text/plain', id)
                }}
                onDragEnd={() => { setDragId(''); setDropId('') }}
              >
                <Icon name="grip" size={14} />
                <b>{item.title}</b>
                {item.extraId ? <em className="god-filter-badge">分析库</em> : null}
                {item.filters.length ? <em className="god-filter-badge">可筛选</em> : null}
              </button>
              <span className="god-block-actions">
                {item.definition?.options?.length ? (
                  <button type="button" title="配置这个块" onClick={() => setConfigId(id)}>配置</button>
                ) : null}
                <button type="button" title="上移" disabled={index === 0} onClick={() => move(id, -1)}><Icon name="up" size={14} /></button>
                <button type="button" title="下移" disabled={index === order.length - 1} onClick={() => move(id, 1)}><Icon name="down" size={14} /></button>
                <button
                  type="button"
                  className={hidden.has(id) ? 'is-off' : ''}
                  title={hidden.has(id) ? '显示这个块' : '隐藏这个块（仍保留）'}
                  onClick={() => setBlockHidden(page, id, !hidden.has(id), mode)}
                >
                  <Icon name={hidden.has(id) ? 'eyeOff' : 'eye'} size={15} />
                </button>
                {item.extraId ? (
                  <button
                    type="button"
                    className="is-off"
                    title="从本页移除（可再从分析库加回来）"
                    onClick={() => {
                      if (item.extraId) removePageExtra(page, item.extraId, mode)
                    }}
                  >
                    <Icon name="close" size={14} />
                  </button>
                ) : null}
              </span>
            </div>
            <div className="god-block-body">
              {renderFilterBar(item)}
              <BlockFilterContext.Provider value={values}>{item.node}</BlockFilterContext.Provider>
            </div>
          </div>
        )
      })}

      {configId ? (() => {
        const item = byId.get(configId)
        if (!item || !item.definition) return null
        const values = layout?.configs?.[configId] || {}
        return (
          <BlockConfigDialog
            definition={item.definition}
            values={values}
            onChange={(patch) => setBlockConfig(page, configId, patch, mode)}
            onClose={() => setConfigId(null)}
          />
        )
      })() : null}
      <ShareDialog
        open={dialog !== null}
        initialTab={dialog || 'share'}
        onClose={() => setDialog(null)}
        onImported={(count) => setNotice(`已导入 ${count} 页布局`)}
      />
      {library}
    </div>
  )
}
