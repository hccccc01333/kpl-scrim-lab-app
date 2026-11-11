import type { MatchSummary } from '../types'

/** matches API 有时不填 goldDiff，但 own/enemy 五人合计已在；统一在客户端补算。 */
export function goldDiffOf(match: MatchSummary): number | null {
  if (typeof match.goldDiff === 'number' && Number.isFinite(match.goldDiff)) return match.goldDiff
  const own = match.own?.gold
  const enemy = match.enemy?.gold
  if (typeof own === 'number' && Number.isFinite(own) && typeof enemy === 'number' && Number.isFinite(enemy)) {
    return own - enemy
  }
  return null
}

/** 展示用模式名：排位赛优先，其次训练赛 / 对局。 */
export function modeLabel(match: MatchSummary): string {
  return match.mode || match.session || '对局'
}
