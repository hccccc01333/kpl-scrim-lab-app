import { useEffect, useRef } from 'react'
import { GRID } from '../../lib/analysis/match'

const CELL = 14
const SIZE = GRID * CELL
const spriteCache = new Map<string, HTMLCanvasElement>()

function channelToRgb(value: string, fallback: string): string {
  const clean = value.trim()
  if (/^\d+\s*,\s*\d+\s*,\s*\d+$/.test(clean)) return clean
  const hex = clean.match(/^#([0-9a-f]{6})$/i)
  if (hex) {
    const number = parseInt(hex[1], 16)
    return `${(number >> 16) & 255}, ${(number >> 8) & 255}, ${number & 255}`
  }
  return fallback
}

function sprite(rgb: string): HTMLCanvasElement {
  const hit = spriteCache.get(rgb)
  if (hit) return hit
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (ctx) {
    const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32)
    gradient.addColorStop(0, `rgba(${rgb},1)`)
    gradient.addColorStop(0.5, `rgba(${rgb},.5)`)
    gradient.addColorStop(1, `rgba(${rgb},0)`)
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, 64, 64)
  }
  spriteCache.set(rgb, canvas)
  return canvas
}

interface HeatCanvasProps {
  counts: Uint16Array | null
  max: number
  side: 'own' | 'foe'
  label?: string
  theme?: string
}

export function HeatCanvas({ counts, max, side, label, theme }: HeatCanvasProps) {
  const ref = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, SIZE, SIZE)

    ctx.save()
    ctx.strokeStyle = 'rgba(128, 138, 132, .14)'
    ctx.lineWidth = 1
    for (let k = 1; k < 4; k++) {
      const p = Math.round((k / 4) * SIZE) + 0.5
      ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, SIZE); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(SIZE, p); ctx.stroke()
    }
    ctx.strokeStyle = 'rgba(38, 74, 96, .32)'
    ctx.lineWidth = SIZE * 0.05
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(SIZE, SIZE); ctx.stroke()
    ctx.restore()

    if (!counts) return
    const styles = getComputedStyle(document.documentElement)
    const own = channelToRgb(styles.getPropertyValue('--md-own-rgb'), '173, 125, 44')
    const foe = channelToRgb(styles.getPropertyValue('--md-foe-rgb'), '14, 101, 91')
    const image = sprite(side === 'foe' ? foe : own)
    ctx.globalCompositeOperation = 'lighter'
    for (let i = 0; i < counts.length; i++) {
      const count = counts[i]
      if (!count) continue
      const cx = ((i % GRID) + 0.5) * CELL
      const cy = (GRID - Math.floor(i / GRID) - 0.5) * CELL
      const radius = CELL * 0.82
      ctx.globalAlpha = Math.min(0.9, 0.12 + Math.pow(count / Math.max(1, max), 0.8) * 0.72)
      ctx.drawImage(image, cx - radius, cy - radius, radius * 2, radius * 2)
    }
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
  }, [counts, max, side, theme])

  return (
    <canvas
      ref={ref}
      className="md-heat-canvas"
      width={SIZE}
      height={SIZE}
      role="img"
      aria-label={label ? `${label} 位置热区` : '位置热区'}
    />
  )
}
