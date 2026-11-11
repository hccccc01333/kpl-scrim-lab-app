import { useMemo } from 'react'
import { signed, duration as fmtDuration } from '../lib/format'

interface EconomyChartProps {
  points: [number, number][]
  duration?: number | null
  label?: string
  note?: string
  height?: number
}

export function EconomyChart({ points, duration, label = '本队经济差', note, height }: EconomyChartProps) {
  const chart = useMemo(() => {
    const values = (points || [])
      .filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v))
      .sort((a, b) => a[0] - b[0])
    if (!values.length) return null
    const maxAbs = Math.max(1, ...values.map(([, value]) => Math.abs(value)))
    const limit = Math.max(5000, Math.ceil(maxAbs / 5000) * 5000)
    const low = Math.min(0, ...values.map(([, value]) => value)) < 0 ? -limit : 0
    const high = limit
    const x0 = values[0][0]
    const x1 = values[values.length - 1][0]
    const plotLeft = 52
    const plotRight = 696
    const plotTop = 20
    const plotBottom = 218
    const x = (time: number) => plotLeft + (x1 === x0 ? 0.5 : (time - x0) / (x1 - x0)) * (plotRight - plotLeft)
    const y = (value: number) => plotTop + (high - value) / (high - low) * (plotBottom - plotTop)
    const line = values.map(([time, value], index) => `${index ? 'L' : 'M'}${x(time).toFixed(1)},${y(value).toFixed(1)}`).join(' ')
    const area = `${line} L${x(x1).toFixed(1)},${y(0).toFixed(1)} L${x(x0).toFixed(1)},${y(0).toFixed(1)} Z`
    const ticks = [low, low + (high - low) / 4, low + (high - low) / 2, low + (high - low) * 0.75, high]
    const last = values[values.length - 1]
    const showEnd = duration && duration > x1 ? duration : x1
    return { values, x, y, line, area, ticks, last, x0, x1, showEnd, negative: last[1] < 0 }
  }, [points, duration])

  if (!chart) {
    return <div className="chart-empty">还没有可用的经济时间轴。等这一局的营地面板或回放采样补齐后，这里会显示经济走势。</div>
  }

  return (
    <div className="economy-chart" style={height ? { minHeight: height } : undefined}>
      <svg viewBox="0 0 720 260" role="img" aria-label={`${label}，${chart.values.length} 个采样点，最后 ${signed(chart.last[1])} 金`}>
        {chart.ticks.map((tick) => (
          <g key={tick}>
            <line x1="52" x2="696" y1={chart.y(tick)} y2={chart.y(tick)} className="chart-grid" />
            <text x="42" y={chart.y(tick) + 4} textAnchor="end" className="chart-axis">
              {tick === 0 ? '0' : `${tick > 0 ? '+' : ''}${(tick / 1000).toFixed(1)}k`}
            </text>
          </g>
        ))}
        <line x1="52" x2="696" y1={chart.y(0)} y2={chart.y(0)} className="chart-zero" />
        <path d={chart.area} className={`chart-area${chart.negative ? ' is-negative' : ''}`} />
        <path d={chart.line} className={`chart-line${chart.negative ? ' is-negative' : ''}`} />
        <circle cx={chart.x(chart.last[0])} cy={chart.y(chart.last[1])} r="4" className="chart-dot" />
        <g transform={`translate(${Math.min(636, Math.max(58, chart.x(chart.last[0]) - 44))}, ${Math.max(8, chart.y(chart.last[1]) - 34)})`}>
          <rect width="88" height="23" rx="3" className="chart-label-box" />
          <text x="9" y="15" className="chart-label-text">{signed(chart.last[1])} 金</text>
        </g>
        <text x="52" y="246" className="chart-axis">{fmtDuration(chart.x0)}</text>
        <text x="696" y="246" textAnchor="end" className="chart-axis">{fmtDuration(chart.showEnd)}</text>
      </svg>
      <div className="chart-foot">
        <span><i /> {label}</span>
        <span>{note || `${chart.values.length} 个采样点 · 最后 ${signed(chart.last[1])} 金`}</span>
      </div>
    </div>
  )
}
