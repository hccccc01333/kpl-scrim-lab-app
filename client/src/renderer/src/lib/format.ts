export function number(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: digits }).format(value)
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${number(value, digits)}%`
}

export function signed(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${number(value, digits)}`
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return '—'
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export function shortDate(value?: string | null): string {
  if (!value) return '日期未知'
  const text = String(value)
  return text.length >= 10 ? text.slice(5, 10) : text
}

export function fullDate(value?: string | null): string {
  if (!value) return '日期未知'
  return String(value)
}

export function resultLabel(result?: string | null): string {
  return ({ win: '胜', loss: '负', draw: '平', unknown: '未知' } as Record<string, string>)[result || ''] || '未知'
}

export function resultTone(result?: string | null): 'win' | 'loss' | 'draw' {
  if (result === 'win') return 'win'
  if (result === 'loss') return 'loss'
  return 'draw'
}

export function scoreText(scores?: Record<string, number> | null, ownCamp?: string): string {
  if (!scores) return '—'
  const own = ownCamp === 'red' || ownCamp === 'right' ? 'red' : ownCamp === 'blue' || ownCamp === 'left' ? 'blue' : null
  const ownScore = own ? scores[own] ?? scores[own === 'blue' ? 'left' : 'right'] : scores.blue ?? scores.left
  const otherScore = own ? scores[own === 'blue' ? 'red' : 'blue'] ?? scores[own === 'blue' ? 'right' : 'left'] : scores.red ?? scores.right
  if (ownScore === undefined || otherScore === undefined) return '—'
  return `${ownScore} : ${otherScore}`
}

export function sideLabel(camp?: string | null): string {
  return ({ blue: '蓝方', red: '红方', left: '蓝方', right: '红方' } as Record<string, string>)[camp || ''] || '阵营未知'
}

export function positionLabel(value?: string | null): string {
  return value || '位置待填写'
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

export function initials(value?: string | null): string {
  const text = (value || '?').trim()
  return text.slice(0, 1) || '?'
}

export function dateRange(dates: (string | undefined | null)[]): string {
  const clean = [...new Set(dates.filter(Boolean) as string[])].sort()
  if (!clean.length) return '暂无日期'
  if (clean.length === 1) return clean[0]
  return `${clean[0]} → ${clean[clean.length - 1]}`
}
