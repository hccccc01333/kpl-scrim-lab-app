import { useId, useMemo, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { PulsePoint } from '../../lib/analysis/match'
import { clamp } from '../../lib/analysis/match'
import { number, signed } from '../../lib/format'
import type { ReplayEvent } from '../../lib/types'

interface PulseChartProps {
  series: PulsePoint[]
  events?: ReplayEvent[]
  duration?: number | null
  ownName?: string
  foeName?: string
}

const W = 1000
const H = 300
const L = 58
const R = 982
const TOP = 26
const BOT = 250

export function PulseChart({ series, events, duration, ownName = '本队', foeName = '对手' }: PulseChartProps) {
  const areaId = `pulse-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const [active, setActive] = useState<PulsePoint | null>(null)
  const [hovering, setHovering] = useState(false)

  const chart = useMemo(() => {
    if (!series.length) return null
    const t0 = series[0].t
    const t1 = series[series.length - 1].t
    const span = Math.max(1, t1 - t0)
    const absMax = Math.max(1000, ...series.map((point) => Math.abs(point.diff)))
    const limit = Math.ceil(absMax / 5000) * 5000
    const low = Math.min(0, ...series.map((point) => point.diff)) < 0 ? -limit : 0
    const high = limit
    const x = (t: number) => L + (t - t0) / span * (R - L)
    const y = (value: number) => TOP + (high - value) / (high - low) * (BOT - TOP)
    const line = series.map((point, index) => `${index ? 'L' : 'M'}${x(point.t).toFixed(1)},${y(point.diff).toFixed(1)}`).join(' ')
    const stepSize = limit >= 20000 ? 10000 : 5000
    const steps: number[] = []
    for (let value = low; value <= high; value += stepSize) steps.push(value)
    const bands = duration && duration > 0
      ? ['对线期', '转线期', '决胜期'].map((name, index) => {
        const a = Math.max(duration * index / 3, t0)
        const b = Math.min(duration * (index + 1) / 3, t1)
        return b > a ? { name, a, b } : null
      }).filter((band): band is { name: string; a: number; b: number } => Boolean(band))
      : []
    const diffAt = (t: number) => {
      let best = series[0]
      for (const point of series) if (Math.abs(point.t - t) < Math.abs(best.t - t)) best = point
      return best.diff
    }
    const marks = (events || [])
      .filter((event) => Number.isFinite(event.t) && event.t >= t0 && event.t <= t1 && (event.kind === 'resource' || event.kind === 'structure'))
      .map((event) => ({
        event,
        x: x(event.t),
        y: y(diffAt(event.t)) - 13,
        own: event.killerCamp === undefined || event.killerCamp === null ? null : event.killerCamp
      }))
    return { t0, t1, x, y, line, steps, bands, marks, low, high }
  }, [series, events, duration])

  if (!chart) return null

  const point = active || series[0]
  const nearby = (events || [])
    .filter((event) => Number.isFinite(event.t) && Math.abs(event.t - point.t) <= 45)
    .sort((a, b) => Math.abs(a.t - point.t) - Math.abs(b.t - point.t))[0]
  const cursorX = chart.x(point.t)
  const cursorY = chart.y(point.diff)

  const handleMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.width) return
    const px = clamp(event.clientX - rect.left, 0, rect.width)
    const t = chart.t0 + (px / rect.width * W - L) / (R - L) * (chart.t1 - chart.t0)
    let nearest = series[0]
    for (const item of series) {
      if (Math.abs(item.t - t) < Math.abs(nearest.t - t)) nearest = item
    }
    setActive(nearest)
  }

  return (
    <div className="md-pulse">
      <div className="md-pulse-readout">
        <span><small>指针时刻</small><b>{formatClock(point.t)}</b></span>
        <span><small className="is-own">{ownName}经济</small><b>{number(point.own)}</b></span>
        <span><small className="is-foe">{foeName}经济</small><b>{number(point.foe)}</b></span>
        <span><small>经济差</small><b className={point.diff >= 0 ? 'is-own' : 'is-foe'}>{signed(point.diff)}</b></span>
        <span className="md-pulse-at">
          {nearby
            ? `${formatClock(nearby.t)} ${kindName(nearby.kind)} · ${nearby.killer || nearby.killerHero || ''}`
            : active ? '该时刻附近没有记录事件' : '拖动或点按曲线，查看任意时刻'}
        </span>
      </div>
      <svg
        className="md-pulse-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`经济差随时间变化，共 ${series.length} 个采样点`}
        onPointerMove={(event) => { setHovering(true); handleMove(event) }}
        onPointerDown={(event) => { setHovering(true); handleMove(event) }}
        onPointerLeave={() => setHovering(false)}
      >
        <defs>
          <linearGradient id={areaId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" className="md-pulse-stop-own" stopOpacity=".34" />
            <stop offset="1" className="md-pulse-stop-own" stopOpacity="0" />
          </linearGradient>
        </defs>
        {chart.bands.map((band, index) => (
          <g key={band.name}>
            <rect
              x={chart.x(band.a)}
              y={TOP}
              width={chart.x(band.b) - chart.x(band.a)}
              height={BOT - TOP}
              className={`md-pulse-band${index % 2 ? ' is-alt' : ''}`}
            />
            <text x={(chart.x(band.a) + chart.x(band.b)) / 2} y={TOP - 9} textAnchor="middle" className="md-band-label">
              {band.name}
            </text>
          </g>
        ))}
        <line className="md-grid" x1={L} x2={R} y1={chart.y(0)} y2={chart.y(0)} />
        {chart.steps.filter((value) => value !== 0).map((value) => (
          <g key={value}>
            <line className="md-grid" x1={L} x2={R} y1={chart.y(value)} y2={chart.y(value)} />
            <text x={L - 10} y={chart.y(value) + 4} textAnchor="end" className="md-axis">
              {number(value / 1000)}k
            </text>
          </g>
        ))}
        <text x={L - 10} y={chart.y(0) + 4} textAnchor="end" className="md-axis">0</text>
        <path
          d={`${chart.line} L${chart.x(series[series.length - 1].t).toFixed(1)},${chart.y(0).toFixed(1)} L${chart.x(chart.t0).toFixed(1)},${chart.y(0).toFixed(1)} Z`}
          fill={`url(#${areaId})`}
        />
        <path d={chart.line} className="md-pulse-curve" />
        {chart.marks.map(({ event, x, y, own }, index) => (
          <g
            key={`${event.kind}-${event.t}-${event.id ?? index}`}
            className={`md-pulse-mark${own === 'blue' ? ' is-blue' : own === 'red' ? ' is-red' : ''}`}
          >
            {event.kind === 'structure'
              ? <rect x={x - 4} y={y - 4} width="8" height="8" rx="1.5" />
              : <path d={`M${x},${y - 5} L${x + 5},${y} L${x},${y + 5} L${x - 5},${y} Z`} />}
            <title>{`${formatClock(event.t)} · ${kindName(event.kind)} · ${event.killer || ''}`}</title>
          </g>
        ))}
        <circle cx={chart.x(series[series.length - 1].t)} cy={chart.y(series[series.length - 1].diff)} r="4.5" className="md-pulse-end" />
        {active && hovering ? (
          <g className="md-pulse-cursor">
            <line x1={cursorX} x2={cursorX} y1={TOP} y2={BOT} />
            <circle cx={cursorX} cy={cursorY} r="5" />
          </g>
        ) : null}
        <rect className="md-pulse-hit" x={L} y={TOP} width={R - L} height={BOT - TOP} />
      </svg>
      <div className="md-pulse-axis">
        <span>{formatClock(chart.t0)}</span>
        <span>{formatClock(chart.t1)}</span>
      </div>
    </div>
  )
}

function formatClock(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function kindName(kind: string) {
  if (kind === 'structure') return '建筑'
  if (kind === 'resource') return '资源'
  return '击杀'
}
