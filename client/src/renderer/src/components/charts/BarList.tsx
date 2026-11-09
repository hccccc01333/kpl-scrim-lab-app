import type { ReactNode } from 'react'

export interface BarItem {
  label: ReactNode
  value: number | null | undefined
  note?: ReactNode
  tone?: 'own' | 'foe' | 'accent' | 'muted'
  badge?: ReactNode
}

export function BarList({
  items,
  max,
  digits = 0,
  suffix = '',
  empty = '暂无可比样本'
}: {
  items: BarItem[]
  max?: number
  digits?: number
  suffix?: string
  empty?: string
}) {
  if (!items.length) return <p className="board-empty">{empty}</p>
  const ceiling = Math.max(1, max ?? Math.max(...items.map((item) => item.value || 0)))
  return (
    <div className="bar-list">
      {items.map((item, index) => (
        <div className="bar-list-row" key={index}>
          <span className="bar-list-label">{item.label}</span>
          <span className={`bar-list-track tone-${item.tone || 'own'}`}>
            <i style={{ width: `${Math.min(100, (item.value || 0) / ceiling * 100).toFixed(1)}%` }} />
          </span>
          <b className="bar-list-value">
            {item.value === null || item.value === undefined || !Number.isFinite(item.value)
              ? '—'
              : `${item.value.toLocaleString('zh-CN', { maximumFractionDigits: digits })}${suffix}`}
          </b>
          {item.badge ? <span className="bar-list-badge">{item.badge}</span> : null}
          {item.note ? <span className="bar-list-note">{item.note}</span> : null}
        </div>
      ))}
    </div>
  )
}
