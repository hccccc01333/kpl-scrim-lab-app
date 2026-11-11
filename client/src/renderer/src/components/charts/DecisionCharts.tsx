import { useMemo, useState } from 'react'
import { duration as fmtDuration, number, percent, signed } from '../../lib/format'

/**
 * 决策台图表：纯 SVG，无第三方依赖。
 * 只接收已经算好的数据，不在这里请求接口；空数据返回原因而不是画一张看似完整的图。
 */

const TONE_LIST = ['own', 'foe', 'accent', 'warn', 'muted'] as const
export type DecisionTone = (typeof TONE_LIST)[number]

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value))
}

function axisNumber(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 10000) return `${(value / 1000).toFixed(1)}k`
  if (abs >= 1000) return `${(value / 1000).toFixed(1)}k`
  return String(Math.round(value))
}

function minuteLabel(value: number): string {
  return `${Math.round(value)}′`
}

/* ── EconomyTimeline ─────────────────────────────────────────────── */

export interface EconomyPoint {
  t: number
  v: number | null
}

export type EconomyEventKind = 'death' | 'fight' | 'objective' | 'other'

export interface EconomyEvent {
  id: string
  t: number
  kind: EconomyEventKind
  label: string
  note?: string
}

export interface EconomyWindow {
  id?: string
  start: number
  end: number
  tone?: 'loss' | 'lead'
}

const EVENT_KIND_LABEL: Record<EconomyEventKind, string> = {
  death: '死亡',
  fight: '团战',
  objective: '资源',
  other: '事件'
}

export function EconomyTimeline({
  points,
  duration,
  approx = true,
  events = [],
  windows = [],
  selectedId,
  onPickEvent,
  height = 260,
  note,
  empty
}: {
  points: EconomyPoint[]
  duration?: number | null
  approx?: boolean
  events?: EconomyEvent[]
  windows?: EconomyWindow[]
  selectedId?: string | null
  onPickEvent?: (id: string) => void
  height?: number
  note?: string
  empty?: string
}) {
  const valid = useMemo(
    () => points.filter((point) => Number.isFinite(point.t) && typeof point.v === 'number' && Number.isFinite(point.v)),
    [points]
  )
  if (valid.length < 2) {
    return <div className="decision-chart-empty">{empty || '暂无经济时间轴：这局没有可用的经济采样点。'}</div>
  }

  const width = 760
  const pad = { left: 58, right: 18, top: 20, bottom: 40 }
  const values = valid as (EconomyPoint & { v: number })[]
  const x0 = 0
  const x1 = Math.max(duration && duration > 0 ? duration : values[values.length - 1].t, 1)
  const rawLow = Math.min(0, ...values.map((point) => point.v))
  const rawHigh = Math.max(0, ...values.map((point) => point.v))
  const spanY = rawHigh - rawLow || 1000
  const low = rawLow - spanY * 0.12
  const high = rawHigh + spanY * 0.12
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const px = (time: number) => pad.left + (time - x0) / (x1 - x0) * plotW
  const py = (value: number) => pad.top + (high - value) / (high - low) * plotH

  const line = values
    .map((point, index) => `${index ? 'L' : 'M'}${px(point.t).toFixed(1)},${py(point.v).toFixed(1)}`)
    .join(' ')
  const area = `${line} L${px(values[values.length - 1].t).toFixed(1)},${py(0).toFixed(1)} L${px(values[0].t).toFixed(1)},${py(0).toFixed(1)} Z`
  const last = values[values.length - 1]
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => low + (high - low) * ratio)
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => x0 + (x1 - x0) * ratio)
  const negative = last.v < 0

  return (
    <div className="decision-chart decision-economy">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`我方视角经济差时间轴，${values.length} 个近似采样点`}>
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line className="decision-grid-line" x1={pad.left} x2={width - pad.right} y1={py(tick)} y2={py(tick)} />
            <text className="decision-axis" x={pad.left - 8} y={py(tick) + 3} textAnchor="end">
              {tick === 0 ? '0' : axisNumber(tick)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <g key={`x-${tick}`}>
            <line className="decision-grid-line is-faint" x1={px(tick)} x2={px(tick)} y1={pad.top} y2={height - pad.bottom} />
            <text className="decision-axis" x={px(tick)} y={height - 16} textAnchor={tick === x0 ? 'start' : tick === x1 ? 'end' : 'middle'}>
              {tick === x1 && approx ? `≈${fmtDuration(tick)}` : fmtDuration(tick)}
            </text>
          </g>
        ))}
        {windows.map((window, index) => {
          const left = px(clamp(window.start, x0, x1))
          const right = px(clamp(window.end, x0, x1))
          const active = Boolean(window.id && selectedId === window.id)
          return (
            <rect
              key={window.id || `window-${index}`}
              className={`decision-chart-window tone-${window.tone || 'loss'}${active ? ' is-active' : ''}`}
              x={Math.min(left, right)}
              y={pad.top}
              width={Math.max(2, Math.abs(right - left))}
              height={plotH}
            />
          )
        })}
        <line className="decision-zero" x1={pad.left} x2={width - pad.right} y1={py(0)} y2={py(0)} />
        <path className={`decision-area${negative ? ' is-negative' : ''}`} d={area} />
        <path className={`decision-line${negative ? ' is-negative' : ''}`} d={line} />
        <circle className={`decision-dot${negative ? ' is-negative' : ''}`} cx={px(last.t)} cy={py(last.v)} r={4} />
        {events.map((event) => {
          const active = selectedId === event.id
          return (
            <g
              key={event.id}
              className={`decision-chart-event tone-${event.kind}${active ? ' is-active' : ''}`}
              role={onPickEvent ? 'button' : undefined}
              tabIndex={onPickEvent ? 0 : undefined}
              onClick={onPickEvent ? () => onPickEvent(event.id) : undefined}
              onKeyDown={onPickEvent
                ? (keyEvent) => {
                    if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
                      keyEvent.preventDefault()
                      onPickEvent(event.id)
                    }
                  }
                : undefined}
            >
              <title>{`${EVENT_KIND_LABEL[event.kind]} · ≈${fmtDuration(event.t)}${event.note ? ` · ${event.note}` : ''}`}</title>
              <rect
                className="decision-event-hit"
                x={px(clamp(event.t, x0, x1)) - 7}
                y={pad.top}
                width={14}
                height={height - pad.top - pad.bottom + 18}
              />
              <line className="decision-event-line" x1={px(clamp(event.t, x0, x1))} x2={px(clamp(event.t, x0, x1))} y1={pad.top} y2={height - pad.bottom} />
              <circle className="decision-event-dot" cx={px(clamp(event.t, x0, x1))} cy={height - pad.bottom + 9} r={active ? 5 : 3.4} />
            </g>
          )
        })}
      </svg>
      <div className="decision-chart-foot">
        <span className="decision-chart-legend">
          <i className="is-line" /> 我方视角经济差
          <i className="is-death" /> 死亡
          <i className="is-fight" /> 团战
          <i className="is-objective" /> 资源 / 建筑
        </span>
        <span>{note || (approx ? '≈ 经济点为插值，约 30 秒一个采样；时间轴为近似时间。' : '经济点按原始采样绘制。')}</span>
      </div>
    </div>
  )
}

/* ── BandChart ───────────────────────────────────────────────────── */

export interface BandPointValue {
  minute: number
  n: number
  p25: number | null
  p50: number | null
  p75: number | null
}

export interface BandSeries {
  key: string
  label: string
  tone: 'own' | 'foe' | 'accent'
  points: BandPointValue[]
}

const BAND_TONE: Record<BandSeries['tone'], string> = {
  own: 'tone-own',
  foe: 'tone-foe',
  accent: 'tone-accent'
}

function segments<T>(points: T[], valid: (point: T) => boolean): T[][] {
  const out: T[][] = []
  let current: T[] = []
  for (const point of points) {
    if (valid(point)) {
      current.push(point)
    } else if (current.length) {
      out.push(current)
      current = []
    }
  }
  if (current.length) out.push(current)
  return out
}

export function BandChart({
  series,
  height = 280,
  empty,
  note
}: {
  series: BandSeries[]
  height?: number
  empty?: string
  note?: string
}) {
  const usable = series
    .map((item) => ({
      ...item,
      points: item.points
        .filter((point) => point.n > 0 && (point.p25 !== null || point.p50 !== null || point.p75 !== null))
        .sort((a, b) => a.minute - b.minute)
    }))
    .filter((item) => item.points.length >= 2)
  if (!usable.length) {
    return <div className="decision-chart-empty">{empty || '暂无分位带：当前范围没有足够的经济采样。'}</div>
  }

  const width = 760
  const pad = { left: 58, right: 22, top: 18, bottom: 40 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const allValues = usable.flatMap((item) => item.points.flatMap((point) => [point.p25, point.p75]))
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const maxMinute = Math.max(...usable.flatMap((item) => item.points.map((point) => point.minute)), 1)
  const rawLow = Math.min(0, ...allValues)
  const rawHigh = Math.max(0, ...allValues)
  const spanY = rawHigh - rawLow || 1000
  const low = rawLow - spanY * 0.1
  const high = rawHigh + spanY * 0.1
  const px = (minute: number) => pad.left + minute / maxMinute * plotW
  const py = (value: number) => pad.top + (high - value) / (high - low) * plotH
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => low + (high - low) * ratio)
  const step = maxMinute <= 20 ? 5 : 10
  const xTicks: number[] = []
  for (let minute = 0; minute <= maxMinute; minute += step) xTicks.push(minute)
  if (xTicks[xTicks.length - 1] !== maxMinute) xTicks.push(maxMinute)

  return (
    <div className="decision-chart decision-bands">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="分位带图：胜、负与全部对局的经济差 P25–P75 与 P50">
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line className="decision-grid-line" x1={pad.left} x2={width - pad.right} y1={py(tick)} y2={py(tick)} />
            <text className="decision-axis" x={pad.left - 8} y={py(tick) + 3} textAnchor="end">
              {tick === 0 ? '0' : axisNumber(tick)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <g key={`x-${tick}`}>
            <line className="decision-grid-line is-faint" x1={px(tick)} x2={px(tick)} y1={pad.top} y2={height - pad.bottom} />
            <text className="decision-axis" x={px(tick)} y={height - 16} textAnchor="middle">{minuteLabel(tick)}</text>
          </g>
        ))}
        <line className="decision-zero" x1={pad.left} x2={width - pad.right} y1={py(0)} y2={py(0)} />
        {usable.map((item) => {
          const tone = BAND_TONE[item.tone]
          const chunks = segments(item.points, (point) => point.p25 !== null && point.p75 !== null)
          return (
            <g key={item.key} className={`decision-band ${tone}`}>
              {chunks.map((chunk, chunkIndex) => {
                const top = chunk.map((point) => `${px(point.minute).toFixed(1)},${py(point.p75 as number).toFixed(1)}`)
                const bottom = [...chunk].reverse().map((point) => `${px(point.minute).toFixed(1)},${py(point.p25 as number).toFixed(1)}`)
                return <path key={`band-${chunkIndex}`} className="decision-band-area" d={`M${top.join(' L')} L${bottom.join(' L')} Z`} />
              })}
              {segments(item.points, (point) => point.p50 !== null).map((chunk, chunkIndex) => (
                <path
                  key={`p50-${chunkIndex}`}
                  className="decision-band-line"
                  d={chunk.map((point, index) => `${index ? 'L' : 'M'}${px(point.minute).toFixed(1)},${py(point.p50 as number).toFixed(1)}`).join(' ')}
                />
              ))}
              {item.points.map((point) => (
                <circle
                  key={`${item.key}-${point.minute}`}
                  className="decision-band-hit"
                  cx={px(point.minute)}
                  cy={py(point.p50 ?? point.p25 ?? 0)}
                  r={7}
                >
                  <title>{`${item.label} · ${minuteLabel(point.minute)} · n=${point.n} · P25 ${signed(point.p25)} / P50 ${signed(point.p50)} / P75 ${signed(point.p75)}`}</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
      <div className="decision-chart-foot">
        <span className="decision-chart-legend">
          {usable.map((item) => {
            const counts = item.points.map((point) => point.n).filter((value) => value > 0)
            const minN = Math.min(...counts)
            const maxN = Math.max(...counts)
            return (
              <span className={`decision-legend-item ${BAND_TONE[item.tone]}`} key={item.key}>
                <i className="is-band" />
                {item.label} · {minN === maxN ? `n=${minN}` : `n=${minN}–${maxN}`}
              </span>
            )
          })}
        </span>
        <span>{note || '每档至少 1 局才画；经济点为近似采样。'}</span>
      </div>
    </div>
  )
}

/* ── QuadrantChart ───────────────────────────────────────────────── */

export interface QuadrantPoint {
  id: string
  x: number
  y: number
  lane?: string | null
  label: string
  hero?: string | null
  gpm?: number | null
  deaths?: number | null
  towerDamage?: number | null
  patch?: string | null
  source?: string | null
  note?: string | null
}

const LANE_CLASS: Record<string, string> = {
  对抗路: 'lane-1',
  打野: 'lane-2',
  中路: 'lane-3',
  发育路: 'lane-4',
  游走: 'lane-5',
  辅助: 'lane-5'
}

function laneClass(lane?: string | null): string {
  return LANE_CLASS[lane || ''] || 'lane-5'
}

function median(values: number[]): number {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

export function QuadrantChart({
  points,
  xLabel = '经济占比',
  yLabel = '英雄伤害占比',
  xMid,
  yMid,
  selected,
  onPick,
  note,
  height = 340,
  empty
}: {
  points: QuadrantPoint[]
  xLabel?: string
  yLabel?: string
  xMid?: number | null
  yMid?: number | null
  selected?: string | null
  onPick?: (id: string) => void
  note?: string
  height?: number
  empty?: string
}) {
  const [hover, setHover] = useState<QuadrantPoint | null>(null)
  const valid = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
  if (!valid.length) {
    return <div className="decision-chart-empty">{empty || '暂无可绘制的资源分配样本。'}</div>
  }

  const width = 760
  const pad = { left: 56, right: 24, top: 22, bottom: 44 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const xMax = Math.max(30, Math.max(...valid.map((point) => point.x)) * 1.12)
  const yMax = Math.max(30, Math.max(...valid.map((point) => point.y)) * 1.12)
  const px = (value: number) => pad.left + clamp(value / xMax, 0, 1) * plotW
  const py = (value: number) => pad.top + (1 - clamp(value / yMax, 0, 1)) * plotH
  const midX = typeof xMid === 'number' ? xMid : median(valid.map((point) => point.x))
  const midY = typeof yMid === 'number' ? yMid : median(valid.map((point) => point.y))
  const towers = valid.map((point) => point.towerDamage).filter((value): value is number => typeof value === 'number' && value > 0)
  const maxTower = towers.length ? Math.max(...towers) : 0
  const radius = (point: QuadrantPoint) => {
    if (!maxTower || typeof point.towerDamage !== 'number' || point.towerDamage <= 0) return 4.4
    return 3.2 + Math.sqrt(point.towerDamage / maxTower) * 4.6
  }
  const lanes = [...new Set(valid.map((point) => point.lane || '未标注'))]
  const hoverLeft = hover ? clamp(px(hover.x) / width * 100, 14, 86) : 0
  const hoverTop = hover ? clamp(py(hover.y) / height * 100, 16, 88) : 0

  return (
    <div className="decision-chart decision-quadrant">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${xLabel} × ${yLabel} 四象限散点`}>
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <g key={`grid-${ratio}`}>
            <line className="decision-grid-line is-faint" x1={pad.left} x2={width - pad.right} y1={pad.top + ratio * plotH} y2={pad.top + ratio * plotH} />
            <line className="decision-grid-line is-faint" x1={pad.left + ratio * plotW} x2={pad.left + ratio * plotW} y1={pad.top} y2={height - pad.bottom} />
          </g>
        ))}
        <line className="decision-quad-mid" x1={px(midX)} x2={px(midX)} y1={pad.top} y2={height - pad.bottom} />
        <line className="decision-quad-mid" x1={pad.left} x2={width - pad.right} y1={py(midY)} y2={py(midY)} />
        <text className="decision-quad-label" x={px(midX) + 6} y={pad.top + 12}>高输出</text>
        <text className="decision-quad-label" x={px(midX) - 6} y={pad.top + 12} textAnchor="end">低输出</text>
        <text className="decision-quad-label" x={pad.left + 6} y={py(midY) - 6}>低经济</text>
        <text className="decision-quad-label" x={width - pad.right - 6} y={py(midY) - 6} textAnchor="end">高经济</text>
        {valid.map((point) => {
          const active = selected === point.id
          const lane = laneClass(point.lane)
          return (
            <g
              key={point.id}
              className={`decision-quad-point ${lane}${active ? ' is-selected' : ''}`}
              onPointerEnter={() => setHover(point)}
              onPointerLeave={() => setHover(null)}
              onClick={onPick ? () => onPick(point.id) : undefined}
              role={onPick ? 'button' : undefined}
              tabIndex={onPick ? 0 : undefined}
              onKeyDown={onPick
                ? (keyEvent) => {
                    if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
                      keyEvent.preventDefault()
                      onPick(point.id)
                    }
                  }
                : undefined}
            >
              <title>{quadrantTooltip(point, xLabel, yLabel)}</title>
              <circle cx={px(point.x)} cy={py(point.y)} r={radius(point)} />
            </g>
          )
        })}
        <line className="decision-quad-axis" x1={pad.left} x2={width - pad.right} y1={height - pad.bottom} y2={height - pad.bottom} />
        <line className="decision-quad-axis" x1={pad.left} x2={pad.left} y1={pad.top} y2={height - pad.bottom} />
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <text key={`xt-${ratio}`} className="decision-axis" x={pad.left + ratio * plotW} y={height - pad.bottom + 14} textAnchor="middle">
            {number(ratio * xMax, 0)}%
          </text>
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <text key={`yt-${ratio}`} className="decision-axis" x={pad.left - 8} y={height - pad.bottom - ratio * plotH + 3} textAnchor="end">
            {number(ratio * yMax, 0)}%
          </text>
        ))}
        <text className="decision-axis is-title" x={pad.left + plotW / 2} y={height - 8} textAnchor="middle">{xLabel}（%）</text>
        <text className="decision-axis is-title" x={pad.left - 42} y={pad.top + plotH / 2} textAnchor="middle" transform={`rotate(-90 ${pad.left - 42} ${pad.top + plotH / 2})`}>
          {yLabel}（%）
        </text>
      </svg>
      {hover ? (
        <div className="decision-quad-tip" style={{ left: `${hoverLeft}%`, top: `${hoverTop}%` }}>
          <b>{hover.label}{hover.hero ? ` · ${hover.hero}` : ''}</b>
          <span>{hover.lane || '分路未标注'}{hover.patch ? ` · 补丁 ${hover.patch}` : ''}</span>
          <span>{xLabel} {percent(hover.x, 1)} · {yLabel} {percent(hover.y, 1)}</span>
          <span>GPM {number(hover.gpm, 1)} · 死亡 {number(hover.deaths)} · 推塔 {number(hover.towerDamage)}</span>
          {hover.source ? <small>{hover.source}</small> : null}
          {hover.note ? <small>{hover.note}</small> : null}
        </div>
      ) : null}
      <div className="decision-chart-foot">
        <span className="decision-chart-legend">
          {lanes.map((lane) => (
            <span className={`decision-legend-item ${laneClass(lane)}`} key={lane}>
              <i className="is-dot" />{lane}
            </span>
          ))}
          <span className="decision-legend-note">点大小＝推塔伤害</span>
        </span>
        <span>{note || '只用于发现待复核的资源分配，不评价选手。'}</span>
      </div>
      <div className="decision-visually-hidden">四象限中位线：经济占比 {percent(midX, 1)}，英雄伤害占比 {percent(midY, 1)}。</div>
    </div>
  )
}

function quadrantTooltip(point: QuadrantPoint, xLabel: string, yLabel: string): string {
  const parts = [
    `${point.label}${point.hero ? ` · ${point.hero}` : ''}`,
    point.lane || '分路未标注',
    `${xLabel} ${number(point.x, 1)}%`,
    `${yLabel} ${number(point.y, 1)}%`,
    `GPM ${number(point.gpm, 1)}`,
    `死亡 ${number(point.deaths)}`,
    `推塔伤害 ${number(point.towerDamage)}`
  ]
  if (point.patch) parts.push(`补丁 ${point.patch}`)
  if (point.source) parts.push(point.source)
  return parts.join(' · ')
}

/* ── OpeningHeat ─────────────────────────────────────────────────── */

export interface OpeningHeatCell {
  x: number
  y: number
  n: number
}

export interface OpeningHeatRoute {
  id?: string
  label: string
  lane?: string | null
  tone?: DecisionTone
  points: [number, number][]
}

const HEAT_GRID = 20
const HEAT_SIZE = 380

export function OpeningHeat({
  cells,
  max,
  routes = [],
  highlightId,
  calibrated = true,
  caption,
  empty
}: {
  cells: OpeningHeatCell[]
  max?: number
  routes?: OpeningHeatRoute[]
  highlightId?: string | null
  calibrated?: boolean
  caption?: string
  empty?: string
}) {
  const usable = cells.filter((cell) => Number.isFinite(cell.x) && Number.isFinite(cell.y) && cell.n > 0)
  if (!usable.length) {
    return <div className="decision-chart-empty">{empty || '暂无位置热区：这批对局没有可用的位置采样。'}</div>
  }
  const ceiling = Math.max(1, max || Math.max(...usable.map((cell) => cell.n)))
  const size = HEAT_SIZE
  const cell = size / HEAT_GRID
  const x = (value: number) => size * value
  const y = (value: number) => size * (1 - value)

  return (
    <div className="decision-chart decision-heat">
      <div className="decision-heat-head">
        <span className="decision-heat-scale">
          少 <i className="is-low" /><i className="is-mid" /><i className="is-high" /> 多
        </span>
        <span className="decision-heat-hint">x → 右 · y → 上</span>
        {!calibrated ? <span className="decision-sample-badge is-warn">未定标 · 相对坐标</span> : null}
      </div>
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label="开局位置热区与路线叠加">
        <rect className="decision-heat-bg" x={0} y={0} width={size} height={size} />
        {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19].map((index) => (
          <g key={`grid-${index}`}>
            <line className="decision-heat-grid" x1={index * cell} x2={index * cell} y1={0} y2={size} />
            <line className="decision-heat-grid" x1={0} x2={size} y1={index * cell} y2={index * cell} />
          </g>
        ))}
        {[1, 2].map((index) => (
          <g key={`zone-${index}`}>
            <line className="decision-heat-zone" x1={index * size / 3} x2={index * size / 3} y1={0} y2={size} />
            <line className="decision-heat-zone" x1={0} x2={size} y1={index * size / 3} y2={index * size / 3} />
          </g>
        ))}
        {usable.map((item) => (
          <rect
            key={`${item.x}-${item.y}`}
            className="decision-heat-cell"
            x={item.x * cell}
            y={(HEAT_GRID - 1 - item.y) * cell}
            width={cell}
            height={cell}
            fillOpacity={0.08 + Math.pow(item.n / ceiling, 0.65) * 0.72}
          >
            <title>{`(${item.x}, ${item.y}) · ${item.n} 个采样点`}</title>
          </rect>
        ))}
        {routes.map((route, index) => {
          if (route.points.length < 2) return null
          const dim = Boolean(highlightId && route.id && route.id !== highlightId)
          const d = route.points.map(([rx, ry], pointIndex) => `${pointIndex ? 'L' : 'M'}${x(clamp(rx, 0, 1)).toFixed(1)},${y(clamp(ry, 0, 1)).toFixed(1)}`).join(' ')
          return (
            <g key={route.id || `route-${index}`} className={`decision-heat-route tone-${route.tone || 'foe'}${dim ? ' is-dim' : ''}${highlightId && route.id === highlightId ? ' is-active' : ''}`}>
              <path d={d} />
              <title>{`${route.label}${route.lane ? ` · ${route.lane}` : ''}`}</title>
            </g>
          )
        })}
      </svg>
      <div className="decision-chart-foot">
        <span className="decision-heat-legend">
          {routes.length ? routes.map((route, index) => (
            <span className={`decision-legend-item tone-${route.tone || 'foe'}`} key={route.id || `legend-${index}`}>
              <i className="is-route" />{route.label}
            </span>
          )) : <span>当前没有可叠加的路线样本</span>}
        </span>
        <span>{caption || '方格为 20×20 位置计数；虚线为九宫格分区。'}</span>
      </div>
    </div>
  )
}

/* ── ArrivalBars ─────────────────────────────────────────────────── */

export interface ArrivalBarItem {
  id?: string
  name: string
  hero?: string | null
  lane?: string | null
  camp: 'own' | 'enemy'
  lagSec: number
  kills?: number | null
  deaths?: number | null
  assists?: number | null
}

export function ArrivalBars({
  items,
  empty,
  note
}: {
  items: ArrivalBarItem[]
  empty?: string
  note?: string
}) {
  if (!items.length) {
    return <div className="decision-chart-empty">{empty || '暂无成员到位数据。'}</div>
  }
  const own = items.filter((item) => item.camp === 'own').sort((a, b) => a.lagSec - b.lagSec)
  const enemy = items.filter((item) => item.camp !== 'own').sort((a, b) => a.lagSec - b.lagSec)
  const rows: { header?: string; item?: ArrivalBarItem }[] = [
    ...(own.length ? [{ header: `我方 · ${own.length} 人` }, ...own.map((item) => ({ item }))] : []),
    ...(enemy.length ? [{ header: `对手 · ${enemy.length} 人` }, ...enemy.map((item) => ({ item }))] : [])
  ]
  const rowHeight = 26
  const headerHeight = 22
  const labelWidth = 174
  const trackLeft = labelWidth + 10
  const trackWidth = 460
  const width = trackLeft + trackWidth + 62
  const height = 26 + rows.reduce((sum, row) => sum + (row.header ? headerHeight : rowHeight), 0) + 20
  const maxLag = Math.max(5, ...items.map((item) => Math.max(0, item.lagSec))) * 1.12
  const px = (value: number) => trackLeft + clamp(value / maxLag, 0, 1) * trackWidth
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => maxLag * ratio)
  let cursor = 22

  return (
    <div className="decision-chart decision-arrival">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="团战成员到位延迟条">
        <text className="decision-axis is-title" x={labelWidth} y={12} textAnchor="end">从开团起</text>
        {ticks.map((tick) => (
          <g key={`tick-${tick}`}>
            <line className="decision-arrival-tick" x1={px(tick)} x2={px(tick)} y1={20} y2={height - 16} />
            <text className="decision-axis" x={px(tick)} y={height - 4} textAnchor={tick === 0 ? 'start' : tick === ticks[ticks.length - 1] ? 'end' : 'middle'}>
              {tick === 0 ? '0s' : `+${tick.toFixed(tick < 10 ? 1 : 0)}s`}
            </text>
          </g>
        ))}
        {rows.map((row, index) => {
          if (row.header !== undefined) {
            const yPosition = cursor
            cursor += headerHeight
            return (
              <text key={`head-${index}`} className="decision-arrival-head" x={6} y={yPosition + 12}>{row.header}</text>
            )
          }
          const item = row.item as ArrivalBarItem
          const yPosition = cursor
          cursor += rowHeight
          const lag = Math.max(0, item.lagSec)
          const tone = item.camp === 'own' ? 'own' : 'foe'
          const barWidth = Math.max(1.5, px(lag) - px(0))
          return (
            <g key={`${item.camp}-${item.name}-${index}`} className={`decision-arrival-row tone-${tone}`}>
              <title>{`${item.name}${item.hero ? ` · ${item.hero}` : ''}${item.lane ? ` · ${item.lane}` : ''} · 到位 ${lag.toFixed(1)}s`}</title>
              <text className="decision-arrival-label" x={labelWidth} y={yPosition + 17} textAnchor="end">
                {item.name}
              </text>
              <rect className="decision-arrival-track" x={trackLeft} y={yPosition + 7} width={trackWidth} height={9} />
              <rect className="decision-arrival-bar" x={trackLeft} y={yPosition + 7} width={barWidth} height={9} />
              <circle className="decision-arrival-dot" cx={px(lag)} cy={yPosition + 11.5} r={2.4} />
              <text className="decision-arrival-value" x={trackLeft + trackWidth + 8} y={yPosition + 16}>
                +{lag.toFixed(1)}s
              </text>
            </g>
          )
        })}
      </svg>
      <p className="decision-chart-note">{note || '条长为从团战开始到该选手到位的延迟；0 秒＝开团瞬间已在场。'}</p>
    </div>
  )
}
