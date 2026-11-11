export function Sparkline({
  points,
  width = 140,
  height = 36,
  duration,
  markAt,
  tone = 'auto'
}: {
  points: [number, number][]
  width?: number
  height?: number
  duration?: number | null
  markAt?: number | null
  tone?: 'auto' | 'win' | 'loss' | 'own' | 'foe'
}) {
  const values = points.filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v))
  if (values.length < 2) return <span className="spark-none">—</span>
  const pad = 3
  const t0 = values[0][0]
  const t1 = Math.max(values[values.length - 1][0], duration || 0)
  const low = Math.min(0, ...values.map(([, v]) => v))
  const high = Math.max(0, ...values.map(([, v]) => v))
  const span = high - low || 1
  const spanT = Math.max(1, t1 - t0)
  const x = (t: number) => pad + (t - t0) / spanT * (width - pad * 2)
  const y = (v: number) => height - pad - (v - low) / span * (height - pad * 2)
  const line = values.map(([t, v], index) => `${index ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${x(values[values.length - 1][0]).toFixed(1)},${y(0).toFixed(1)} L${x(values[0][0]).toFixed(1)},${y(0).toFixed(1)} Z`
  const last = values[values.length - 1][1]
  const cls = tone === 'auto' ? (last < 0 ? 'is-loss' : 'is-win') : `is-${tone}`
  return (
    <svg className={`sparkline ${cls}`} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="经济差走势">
      <line className="spark-zero" x1={pad} x2={width - pad} y1={y(0)} y2={y(0)} />
      {markAt && markAt > t0 && markAt < t1 ? (
        <line className="spark-mark" x1={x(markAt)} x2={x(markAt)} y1={pad} y2={height - pad} />
      ) : null}
      <path className="spark-area" d={area} />
      <path className="spark-path" d={line} />
    </svg>
  )
}
