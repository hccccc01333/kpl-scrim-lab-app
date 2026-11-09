import type { ReactNode } from 'react'

export interface StatItem {
  label: ReactNode
  value: ReactNode
  note?: ReactNode
  tone?: 'own' | 'foe' | 'muted' | 'accent'
}

export function StatGrid({ items, columns }: { items: StatItem[]; columns?: number }) {
  return (
    <div className="board-stats" style={columns ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}>
      {items.map((item, index) => (
        <div className={`board-stat${item.tone ? ` tone-${item.tone}` : ''}`} key={index}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          {item.note ? <small>{item.note}</small> : null}
        </div>
      ))}
    </div>
  )
}

export function TierBadge({ tier }: { tier: 'S' | 'A' | 'B' | 'C' }) {
  return <span className={`tier-badge is-${tier.toLowerCase()}`}>{tier}</span>
}

export function BoardEmpty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="board-empty-state">
      <b>{title}</b>
      {children ? <p>{children}</p> : null}
    </div>
  )
}

export function PercentBar({
  value,
  label,
  digits = 1,
  tone = 'own'
}: {
  value: number | null | undefined
  label?: ReactNode
  digits?: number
  tone?: 'own' | 'foe' | 'accent' | 'muted'
}) {
  const safe = typeof value === 'number' && Number.isFinite(value) ? value : null
  return (
    <div className="pct-bar">
      {label ? <span>{label}</span> : null}
      <i className={`tone-${tone}`}><em style={{ width: `${Math.max(0, Math.min(100, safe ?? 0)).toFixed(1)}%` }} /></i>
      <b>{safe === null ? '—' : `${safe.toLocaleString('zh-CN', { maximumFractionDigits: digits })}%`}</b>
    </div>
  )
}

export function WinRing({
  value,
  size = 86,
  label
}: {
  value: number | null | undefined
  size?: number
  label?: string
}) {
  const safe = typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null
  const radius = size / 2 - 7
  const circumference = 2 * Math.PI * radius
  const dash = (safe ?? 0) / 100 * circumference
  return (
    <span className="win-ring" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label || '胜率'} ${safe === null ? '无样本' : `${safe.toFixed(1)}%`}`}>
        <circle className="win-ring-track" cx={size / 2} cy={size / 2} r={radius} />
        <circle
          className="win-ring-value"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeDasharray={`${dash} ${circumference - dash}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span><b>{safe === null ? '—' : `${safe.toFixed(0)}%`}</b><small>{label || '胜率'}</small></span>
    </span>
  )
}

export function MiniLine({
  values,
  width = 520,
  height = 150,
  label
}: {
  values: { x: number; y: number | null }[]
  width?: number
  height?: number
  label?: string
}) {
  const valid = values.filter((point): point is { x: number; y: number } => typeof point.y === 'number' && Number.isFinite(point.y))
  if (valid.length < 2) return <BoardEmpty title="暂无可绘制的曲线">需要至少两个采样点。</BoardEmpty>
  const xs = valid.map((point) => point.x)
  const ys = valid.map((point) => point.y)
  let x0 = Math.min(...xs)
  let x1 = Math.max(...xs)
  let y0 = Math.min(...ys)
  let y1 = Math.max(...ys)
  if (x0 === x1) { x0 -= 1; x1 += 1 }
  const pad = 8
  const range = y1 - y0 || 1
  y0 -= range * 0.1
  y1 += range * 0.1
  const px = (value: number) => pad + (value - x0) / (x1 - x0) * (width - pad * 2)
  const py = (value: number) => height - pad - (value - y0) / (y1 - y0) * (height - pad * 2)
  const line = valid.map((point, index) => `${index ? 'L' : 'M'}${px(point.x).toFixed(1)},${py(point.y).toFixed(1)}`).join(' ')
  const area = `${line} L${px(valid[valid.length - 1].x).toFixed(1)},${height - pad} L${px(valid[0].x).toFixed(1)},${height - pad} Z`
  return (
    <svg className="mini-line" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label || '趋势'}>
      <line className="mini-line-zero" x1={pad} x2={width - pad} y1={py(0)} y2={py(0)} />
      <path className="mini-line-area" d={area} />
      <path className="mini-line-path" d={line} />
    </svg>
  )
}

export function Tag({ children, tone = 'muted' }: { children: ReactNode; tone?: 'own' | 'foe' | 'muted' | 'warn' }) {
  return <span className={`board-tag tone-${tone}`}>{children}</span>
}
