import { useId } from 'react'
import type { FrontlineData } from '../../lib/analysis/match'
import { isNum } from '../../lib/analysis/match'

const W = 1000
const H = 300
const L = 48
const R = 22
const TOP = 28
const BOT = H - 34

export function FrontlineChart({ data }: { data: FrontlineData }) {
  const areaId = `front-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const span = Math.max(1, data.total)
  const x = (t: number) => L + (t / span) * (W - L - R)
  const y = (value: number) => TOP + (1 - value) * (BOT - TOP)

  const path = (values: (number | null)[]) => {
    let d = ''
    let open = false
    values.forEach((value, index) => {
      if (!isNum(value)) {
        open = false
        return
      }
      d += `${open ? 'L' : 'M'}${x(data.rows[index].t).toFixed(1)},${y(value).toFixed(1)}`
      open = true
    })
    return d
  }

  const ownPath = path(data.ownLine)
  const lastOwn = data.ownLine.reduce<number>((index, value, current) => (isNum(value) ? current : index), -1)
  const firstOwn = data.ownLine.findIndex((value) => isNum(value))
  const area = ownPath && lastOwn > firstOwn
    ? `${ownPath}L${x(data.rows[lastOwn].t).toFixed(1)},${BOT}L${x(data.rows[firstOwn].t).toFixed(1)},${BOT}Z`
    : ''
  const ticks: number[] = []
  for (let t = 0; t <= data.total; t += 120) ticks.push(t)

  return (
    <svg className="md-front-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="双方阵线随时间变化">
      <defs>
        <linearGradient id={areaId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" className="md-front-stop-own" stopOpacity=".26" />
          <stop offset="1" className="md-front-stop-own" stopOpacity="0" />
        </linearGradient>
      </defs>
      {['对线期', '转线期', '决胜期'].map((label, index) => {
        const a = x(data.total * index / 3)
        const b = x(data.total * (index + 1) / 3)
        return (
          <g key={label}>
            <rect className={`md-front-band${index % 2 ? ' is-alt' : ''}`} x={a} y={TOP} width={Math.max(0, b - a)} height={BOT - TOP} />
            <text className="md-band-label" x={(a + b) / 2} y={TOP - 9} textAnchor="middle">{label}</text>
          </g>
        )
      })}
      {[0, 0.25, 0.5, 0.75, 1].map((value) => (
        <g key={value}>
          <line className={`md-grid${value === 0.5 ? ' is-mid' : ''}`} x1={L} x2={W - R} y1={y(value)} y2={y(value)} />
          <text className="md-axis" x={L - 10} y={y(value) + 4} textAnchor="end">{Math.round(value * 100)}%</text>
        </g>
      ))}
      {ticks.map((t) => (
        <text key={t} className="md-axis" x={x(t)} y={H - 12} textAnchor="middle">{formatClock(t)}</text>
      ))}
      <path className="md-front-area" d={area} fill={`url(#${areaId})`} />
      <path className="md-front-line is-foe" d={path(data.foeLine)} />
      <path className="md-front-line is-own" d={ownPath} />
    </svg>
  )
}

function formatClock(seconds: number) {
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
