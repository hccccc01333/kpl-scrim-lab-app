import { useMemo } from 'react'
import { Icon } from '../components/Icon'
import { addPageExtra, type LayoutMode } from './layout-store'
import { domainLabel, listRegisteredBlocks, type RegisteredBlock } from './registry'

interface VariantGroup {
  base: string
  title: string
  question: string
  blocks: RegisteredBlock[]
}

interface DomainGroup {
  domain: string
  bases: VariantGroup[]
}

interface BlockLibraryProps {
  open: boolean
  onClose: () => void
  page: string
  mode: LayoutMode
  existing: string[]
  onAdded: (title: string) => void
}

export function BlockLibrary({ open, onClose, page, mode, existing, onAdded }: BlockLibraryProps) {
  const groups = useMemo<DomainGroup[]>(() => {
    const domainMap = new Map<string, DomainGroup>()
    const baseMap = new Map<string, VariantGroup>()
    for (const block of listRegisteredBlocks()) {
      const base = block.base || block.id
      const entry = baseMap.get(base) || { base, title: block.title, question: block.question, blocks: [] }
      entry.blocks.push(block)
      baseMap.set(base, entry)
    }
    for (const entry of baseMap.values()) {
      const domain = entry.blocks[0].domain
      const bucket = domainMap.get(domain) || { domain, bases: [] }
      bucket.bases.push(entry)
      domainMap.set(domain, bucket)
    }
    return [...domainMap.values()]
  }, [])

  if (!open) return null

  return (
    <div className="god-modal" role="dialog" aria-modal="true" aria-label="分析库">
      <div className="god-modal-backdrop" onClick={onClose} />
      <div className="god-modal-card god-library-card">
        <div className="god-modal-head">
          <div>
            <b>分析库</b>
            <small>所有分析都在这里。同一种分析有多个变体（卡片/表格/结论…），挑一个加到当前页，它带着自己的数据和口径过来。</small>
          </div>
          <button type="button" className="god-modal-close" onClick={onClose} aria-label="关闭"><Icon name="close" size={16} /></button>
        </div>
        <div className="god-library-body">
          {groups.map((group) => (
            <section className="god-library-group" key={group.domain}>
              <h4>{domainLabel(group.domain)}</h4>
              {group.bases.map((variant) => (
                <div className="god-library-row" key={variant.base}>
                  <div className="god-library-copy">
                    <b>{variant.title}</b>
                    <small>{variant.question}</small>
                  </div>
                  <div className="god-library-variants">
                    {variant.blocks.map((block) => {
                      const added = existing.includes(block.id)
                      return (
                        <button
                          type="button"
                          key={block.id}
                          className={`btn btn-sm${added ? '' : ' btn-primary'}`}
                          disabled={added}
                          onClick={() => {
                            addPageExtra(page, block.id, mode)
                            onAdded(`${variant.title} · ${block.variant || '默认'}`)
                          }}
                        >
                          {added ? '已加' : `+ ${block.variant || '默认'}`}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
