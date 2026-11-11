interface Series {
  label: string
  tone: 'own' | 'foe'
  values: (number | null)[]
}

export function PercentileRadar({
  axes,
  series,
  size = 200
}: {
  axes: string[]
  series: Series[]
  size?: number
}) {
  const center = size / 2
  const radius = size * 0.34
  const angle = (index: number) => -Math.PI / 2 + index * Math.PI * 2 / Math.max(1, axes.length)
  const point = (index: number, value: number): [number, number] => {
    const r = radius * Math.max(0, Math.min(1, value / 100))
    return [center + Math.cos(angle(index)) * r, center + Math.sin(angle(index)) * r]
  }
  return (
    <svg className="pct-radar" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`分位雷达：${series.map((item) => item.label).join(' 与 ')}`}>
      {[0.2, 0.4, 0.6, 0.8, 1].map((ratio) => (
        <polygon
          key={ratio}
          className="pct-radar-ring"
          points={axes.map((_, index) => point(index, ratio * 100).map((value) => value.toFixed(1)).join(',')).join(' ')}
        />
      ))}
      {axes.map((axis, index) => {
        const [x, y] = point(index, 100)
        return <line key={axis} className="pct-radar-spoke" x1={center} y1={center} x2={x.toFixed(1)} y2={y.toFixed(1)} />
      })}
      {axes.map((axis, index) => {
        const [x, y] = point(index, 118)
        return (
          <text key={axis} className="pct-radar-label" x={x.toFixed(1)} y={(y + 3).toFixed(1)} textAnchor="middle">
            {axis}
          </text>
        )
      })}
      {series.map((item) => {
        const points = axes.map((_, index) => point(index, item.values[index] ?? 0))
        return (
          <polygon
            key={item.label}
            className={`pct-radar-area is-${item.tone}`}
            points={points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}
          />
        )
      })}
    </svg>
  )
}
