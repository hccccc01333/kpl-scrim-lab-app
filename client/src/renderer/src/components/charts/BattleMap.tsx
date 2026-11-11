import type { BattleMark, DeathRow } from '../../lib/analysis/match'
import type { Camp } from '../../lib/analysis/match'

interface BattleMapProps {
  marks: BattleMark[]
  rows: DeathRow[]
  ownCamp: Camp
  selectedHero?: string | null
  selectedDeath?: number | null
  onPickDeath?: (index: number | null) => void
}

const SIZE = 320
const PAD = 20
const bx = (x: number) => PAD + (x + 57) / 114 * (SIZE - PAD * 2)
const by = (y: number) => SIZE - PAD - ((y + 57) / 114) * (SIZE - PAD * 2)

export function BattleMap({ marks, rows, ownCamp, selectedHero, selectedDeath, onPickDeath }: BattleMapProps) {
  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="md-battle-svg" role="img" aria-label="团战与掉点分布">
      {[1, 2, 3].map((k) => {
        const at = PAD + (k / 4) * (SIZE - PAD * 2)
        return (
          <g key={k}>
            <line className="md-battle-grid" x1={at} y1={PAD} x2={at} y2={SIZE - PAD} />
            <line className="md-battle-grid" x1={PAD} y1={at} x2={SIZE - PAD} y2={at} />
          </g>
        )
      })}
      <line className="md-battle-river" x1={PAD} y1={PAD} x2={SIZE - PAD} y2={SIZE - PAD} />
      <g className="md-battle-bases">
        <circle className="is-blue" cx={bx(-49)} cy={by(-49)} r="3.4" />
        <circle className="is-red" cx={bx(49)} cy={by(49)} r="3.4" />
        <text className="md-battle-base-label" x={bx(-49)} y={by(-49) + 14} textAnchor="middle">蓝</text>
        <text className="md-battle-base-label" x={bx(49)} y={by(49) - 8} textAnchor="middle">红</text>
      </g>
      {marks.map((mark) => {
        const off = Boolean(selectedHero) && !mark.heroes.includes(selectedHero as string)
        const tone = mark.side === 'own' ? 'is-own' : mark.side === 'foe' ? 'is-foe' : 'is-even'
        return (
          <g key={`fight-${mark.fightIndex}`} className={`md-battle-mark ${tone}${off ? ' is-off' : ''}`}>
            <circle cx={bx(mark.x)} cy={by(mark.y)} r={5 + Math.min(9, mark.total * 0.9)} />
            <title>{`${formatClock(mark.t)} 团战 · ${mark.total} 人 · 击杀 ${mark.mine} : ${mark.theirs}`}</title>
          </g>
        )
      })}
      {rows.map((row, index) => {
        const off = Boolean(selectedHero) && row.death.hero !== selectedHero
        const tone = row.death.camp === ownCamp ? 'is-own' : 'is-foe'
        return (
          <g
            key={`death-${index}`}
            className={`md-battle-death ${tone}${off ? ' is-off' : ''}${selectedDeath === index ? ' is-on' : ''}`}
            onPointerEnter={() => onPickDeath?.(index)}
            onPointerDown={() => onPickDeath?.(index)}
            onPointerLeave={() => onPickDeath?.(null)}
          >
            <circle className="md-death-dot" cx={bx(row.death.x)} cy={by(row.death.y)} r="3.2" />
            <circle className="md-death-hit" cx={bx(row.death.x)} cy={by(row.death.y)} r="9" />
            <title>{`${formatClock(row.death.t)} ${row.death.hero || ''} 阵亡`}</title>
          </g>
        )
      })}
    </svg>
  )
}

function formatClock(seconds: number) {
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
