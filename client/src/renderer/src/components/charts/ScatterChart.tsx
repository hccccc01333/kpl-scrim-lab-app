import { useId, useState } from 'react'
import { clamp } from '../../lib/analysis/match'

export interface ScatterPoint {
  x: number | null | undefined
  y: number | null | undefined
  label: string
  tone?: 'own' | 'foe' | 'accent' | 'muted'
  note?: string
}

export function ScatterChart({
  points,
  xLabel,
  yLabel,
  height = 260,
  onPick,
  selected
}: {
  points: ScatterPoint[]
  xLabel: string
  yLabel: string
  height?: number
  onPick?: (label: string) => void
  selected?: string | null
}) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const [hover, setHover] = useState<ScatterPoint | null>(null)
  const valid = points.filter((point): point is ScatterPoint & { x: number; y: number } =>
    typeof point.x === 'number' && Number.isFinite(point.x) &&
    typeof point.y === 'number' && Number.isFinite(point.y))
  if (!valid.length) return <p className="board-empty">暂无可绘制的样本</p>

  const width = 640
  const pad = { left: 52, right: 20, top: 18, bottom: 38 }
  const xs = valid.map((point) => point.x)
  const ys = valid.map((point) => point.y)
  let x0 = Math.min(...xs)
  let x1 = Math.max(...xs)
  let y0 = Math.min(...ys)
  let y1 = Math.max(...ys)
  if (x0 === x1) { x0 -= 1; x1 += 1 }
  if (y0 === y1) { y0 -= 1; y1 += 1 }
  const xPad = (x1 - x0) * 0.08
  const yPad = (y1 - y0) * 0.1
  x0 -= xPad; x1 += xPad; y0 -= yPad; y1 += yPad
  const px = (value: number) => pad.left + (value - x0) / (x1 - x0) * (width - pad.left - pad.right)
  const py = (value: number) => height - pad.bottom - (value - y0) / (y1 - y0) * (height - pad.top - pad.bottom)
  const midX = (x0 + x1) / 2
  const midY = (y0 + y1) / 2
  const active = hover

  return (
    <div className="scatter">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${xLabel} × ${yLabel} 散点图`}>
        <defs>
          <clipPath id={`clip-${id}`}>
            <rect x={pad.left} y={pad.top} width={width - pad.left - pad.right} height={height - pad.top - pad.bottom} />
          </clipPath>
        </defs>
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <line
            key={`h-${ratio}`}
            className="scatter-grid"
            x1={pad.left}
            x2={width - pad.right}
            y1={pad.top + ratio * (height - pad.top - pad.bottom)}
            y2={pad.top + ratio * (height - pad.top - pad.bottom)}
          />
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <line
            key={`v-${ratio}`}
            className="scatter-grid"
            x1={pad.left + ratio * (width - pad.left - pad.right)}
            x2={pad.left + ratio * (width - pad.left - pad.right)}
            y1={pad.top}
            y2={height - pad.bottom}
          />
        ))}
        <line className="scatter-mid" x1={px(midX)} x2={px(midX)} y1={pad.top} y2={height - pad.bottom} />
        <line className="scatter-mid" x1={pad.left} x2={width - pad.right} y1={py(midY)} y2={py(midY)} />
        {valid.map((point) => (
          <g
            key={point.label}
            className={`scatter-point tone-${point.tone || 'accent'}${selected === point.label ? ' is-selected' : ''}`}
            onPointerEnter={() => setHover(point)}
            onPointerLeave={() => setHover(null)}
            onClick={() => onPick?.(point.label)}
            role={onPick ? 'button' : undefined}
            tabIndex={onPick ? 0 : undefined}
          >
            <circle cx={px(point.x)} cy={py(point.y)} r={selected === point.label ? 6 : 4.2} />
            <title>{`${point.label} · ${xLabel} ${point.x.toFixed(1)} · ${yLabel} ${point.y.toFixed(1)}${point.note ? ` · ${point.note}` : ''}`}</title>
          </g>
        ))}
        <text className="scatter-axis" x={pad.left} y={height - 14}>{xLabel}</text>
        <text className="scatter-axis" x={width - pad.right} y={height - 14} textAnchor="end">
          {formatAxis(x0)} – {formatAxis(x1)}
        </text>
        <text className="scatter-axis" x={pad.left - 8} y={pad.top + 4} textAnchor="end">{formatAxis(y1)}</text>
        <text className="scatter-axis" x={pad.left - 8} y={height - pad.bottom} textAnchor="end">{formatAxis(y0)}</text>
      </svg>
      {active ? (
        <div className="scatter-tip">
          <b>{active.label}</b>
          <span>{xLabel} {active.x?.toFixed(1)} · {yLabel} {active.y?.toFixed(1)}</span>
          {active.note ? <small>{active.note}</small> : null}
        </div>
      ) : null}
    </div>
  )
}

function formatAxis(value: number) {
  const abs = Math.abs(value)
  if (abs >= 10000) return `${(value / 1000).toFixed(1)}k`
  if (abs >= 1000) return value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
  return String(Math.round(value * 10) / 10)
}

export function clampScatterValue(value: number, values: number[]) {
  if (!values.length) return value
  const sorted = [...values].sort((a, b) => a - b)
  const low = sorted[Math.floor(sorted.length * 0.02)] ?? sorted[0]
  const high = sorted[Math.floor(sorted.length * 0.98)] ?? sorted[sorted.length - 1]
  return clamp(value, low, high)
}
