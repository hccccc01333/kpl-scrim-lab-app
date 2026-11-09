import type { MetricDef } from '../../lib/analysis/match'
import { clamp, isNum } from '../../lib/analysis/match'
import type { MatchPlayer } from '../../lib/types'

interface RadarChartProps {
  metrics: MetricDef[]
  own: MatchPlayer | null
  foe: MatchPlayer | null
  ownLabel?: string
  foeLabel?: string
}

const SIZE = 132
const CENTER = SIZE / 2
const RADIUS = 44

export function RadarChart({ metrics, own, foe, ownLabel = '本队', foeLabel = '对手' }: RadarChartProps) {
  const angle = (index: number) => -Math.PI / 2 + index * Math.PI * 2 / metrics.length
  const point = (index: number, radius: number): [number, number] => [
    CENTER + Math.cos(angle(index)) * radius,
    CENTER + Math.sin(angle(index)) * radius
  ]
  const scale = metrics.map((metric) => Math.max(1, metric.get(own) || 0, metric.get(foe) || 0))
  const area = (player: MatchPlayer | null, side: 'own' | 'foe') => {
    if (!player) return null
    const points = metrics.map((metric, index) => {
      const value = metric.get(player)
      return point(index, Math.max(2.5, clamp((isNum(value) ? value : 0) / scale[index], 0, 1) * RADIUS))
    })
    return (
      <polygon
        className={`md-radar-area is-${side}`}
        points={points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}
      />
    )
  }
  return (
    <svg
      className="md-radar"
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      role="img"
      aria-label={`对位雷达：${own?.label || own?.hero || ownLabel} 与 ${foe?.label || foe?.hero || foeLabel}`}
    >
      {[0.34, 0.67, 1].map((ratio) => (
        <polygon
          key={ratio}
          className="md-radar-ring"
          points={metrics.map((_, index) => point(index, RADIUS * ratio).map((value) => value.toFixed(1)).join(',')).join(' ')}
        />
      ))}
      {metrics.map((metric, index) => {
        const [x, y] = point(index, RADIUS)
        return <line key={metric.key} className="md-radar-spoke" x1={CENTER} y1={CENTER} x2={x.toFixed(1)} y2={y.toFixed(1)} />
      })}
      {area(own, 'own')}
      {area(foe, 'foe')}
      {metrics.map((metric, index) => {
        const [x, y] = point(index, RADIUS + 12)
        return (
          <text key={metric.key} className="md-radar-label" x={x.toFixed(1)} y={(y + 3).toFixed(1)} textAnchor="middle">
            {metric.label}
          </text>
        )
      })}
    </svg>
  )
}
