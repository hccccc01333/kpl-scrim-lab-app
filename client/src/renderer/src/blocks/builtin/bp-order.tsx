/**
 * 上帝模式 · BP 顺序类注册块（下一手 / 拆解时机 / 首抢价值）
 *
 * 依赖征召模板把两侧有序名单还原成全局手序：
 * - 我方前两手组合 → 对手下一手 ban 谁；
 * - 组合在哪个阶段被拆（首轮 ban / 二轮 ban / 被抢）；
 * - 首抢（蓝方第一手选人）英雄的次数胜率。
 */
import { useBlockFilter } from '../filter-context'
import { dateInBlockRange } from '../filters'
import { buildDraftSegments, sideLabel, type DraftSide, type DraftSlot } from '../../lib/analysis/draft'
import { percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState, Portrait } from '../../components/ui'
import type { RegisteredBlock } from '../registry'
import { ownDraftSide, toDraftSource, useAnalysisBp, type AnalysisBpMatch } from './bp'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function useFilteredBpMatches(): {
  query: ReturnType<typeof useAnalysisBp>
  matches: AnalysisBpMatch[]
  ownSide: (match: AnalysisBpMatch) => DraftSide | null
} {
  const query = useAnalysisBp()
  const filters = useBlockFilter()
  const matches = (query.data?.matches || []).filter((match) => {
    if (filters.opponent && match.opponent !== filters.opponent) return false
    if (!dateInBlockRange(match.date, filters)) return false
    return true
  })
  return { query, matches, ownSide: ownDraftSide }
}

function allSlots(match: AnalysisBpMatch): DraftSlot[] {
  return buildDraftSegments(toDraftSource(match)).segments.flatMap((segment) => segment.slots).filter((slot) => slot.hero)
}

function ownPicks(match: AnalysisBpMatch): DraftSlot[] {
  const own = ownDraftSide(match)
  if (!own) return []
  return allSlots(match).filter((slot) => slot.phase === 'pick' && slot.side === own)
}

/** 拿到我方前两手组合后，对手下一手 ban 谁。 */
function BpNextBanBlock() {
  const { query, matches } = useFilteredBpMatches()
  const samples = new Map<string, number>()
  const targets = new Map<string, Map<string, number>>()
  for (const match of matches) {
    const picks = ownPicks(match)
    if (picks.length < 2) continue
    const combo = `${picks[0].hero} + ${picks[1].hero}`
    samples.set(combo, (samples.get(combo) || 0) + 1)
    const secondOrder = picks[1].order
    const nextBan = allSlots(match).find((slot) =>
      slot.order > secondOrder && slot.phase === 'ban' && slot.side !== picks[0].side)
    if (!nextBan) continue
    const map = targets.get(combo) || new Map<string, number>()
    map.set(nextBan.hero, (map.get(nextBan.hero) || 0) + 1)
    targets.set(combo, map)
  }
  const rows = [...samples.entries()].map(([combo, games]) => {
    const map = targets.get(combo)
    const top = map ? [...map.entries()].sort((a, b) => b[1] - a[1])[0] : undefined
    return { combo, games, target: top?.[0] || '', count: top?.[1] || 0 }
  }).sort((a, b) => b.games - a.games).slice(0, 10)
  return (
    <AnalysisSection title="拿到组合后，对手下一手" note="块库 · 我方前两手组合成型后，对手第一个 ban 的选择（按征召模板还原手序）。">
      {query.isLoading ? <Loading label="正在读取 BP 记录…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>我方前两手</th><th>样本局</th><th>对手下一手 ban</th><th>次数</th><th>占比</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.combo}>
                      <td>{row.combo}</td>
                      <td className="is-num">{row.games}</td>
                      <td>{row.target || '—'}</td>
                      <td className="is-num">{row.count}</td>
                      <td className="is-num">{row.games ? percent(row.count / row.games * 100) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选没有带完整手序的组合局" />}
    </AnalysisSection>
  )
}

interface PairStat {
  heroes: [string, string]
  formed: number
  broken: number
  ban1: number
  ban2: number
  stolen: number
  brokenWins: number
  brokenDecided: number
}

/** 组合在哪个阶段被拆：首轮 ban / 二轮 ban / 被抢。 */
function BpBreakTimingBlock() {
  const { query, matches } = useFilteredBpMatches()
  const formed = new Map<string, { heroes: [string, string]; count: number }>()
  for (const match of matches) {
    const picks = ownPicks(match)
    for (let i = 0; i < picks.length; i += 1) {
      for (let j = i + 1; j < picks.length; j += 1) {
        const heroes = [picks[i].hero, picks[j].hero].sort() as [string, string]
        const key = heroes.join('|')
        const row = formed.get(key) || { heroes, count: 0 }
        row.count += 1
        formed.set(key, row)
      }
    }
  }
  const top = [...formed.values()].sort((a, b) => b.count - a.count).slice(0, 8)
  const stats = new Map<string, PairStat>(top.map((item) => [item.heroes.join('|'), {
    heroes: item.heroes, formed: 0, broken: 0, ban1: 0, ban2: 0, stolen: 0, brokenWins: 0, brokenDecided: 0
  }]))
  for (const match of matches) {
    const own = ownDraftSide(match)
    if (!own) continue
    const picks = ownPicks(match)
    const slots = allSlots(match)
    const pickNames = new Set(picks.map((slot) => slot.hero))
    for (const stat of stats.values()) {
      const [a, b] = stat.heroes
      if (pickNames.has(a) && pickNames.has(b)) {
        stat.formed += 1
        continue
      }
      const action = slots.find((slot) => slot.side !== own && (slot.hero === a || slot.hero === b))
      if (!action) continue
      stat.broken += 1
      if (action.phase === 'pick') stat.stolen += 1
      else if (action.segment.includes('②')) stat.ban2 += 1
      else stat.ban1 += 1
      if (match.result === 'win' || match.result === 'loss') {
        stat.brokenDecided += 1
        if (match.result === 'win') stat.brokenWins += 1
      }
    }
  }
  const rows = [...stats.values()].filter((stat) => stat.formed || stat.broken).sort((a, b) => (b.formed + b.broken) - (a.formed + a.broken)).slice(0, 10)
  return (
    <AnalysisSection title="组合被拆时机" note="块库 · 按征召手序判断组合是在首轮 ban、二轮 ban 还是被抢拆掉的；拆解动作取该组合英雄在对手侧最早出现的一手。">
      {query.isLoading ? <Loading label="正在读取 BP 记录…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>组合</th><th>成型</th><th>被拆</th><th>首轮 ban</th><th>二轮 ban</th><th>被抢</th><th>拆后胜率</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.heroes.join('|')}>
                      <td>{row.heroes.join(' + ')}</td>
                      <td className="is-num">{row.formed}</td>
                      <td className="is-num">{row.broken}</td>
                      <td className="is-num">{row.ban1}</td>
                      <td className="is-num">{row.ban2}</td>
                      <td className="is-num">{row.stolen}</td>
                      <td className="is-num">{percent(row.brokenDecided ? row.brokenWins / row.brokenDecided * 100 : null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选没有组合样本" />}
    </AnalysisSection>
  )
}

/** 首抢价值：第一手选人的英雄次数 + 首抢方胜率。 */
function BpFirstPickBlock() {
  const { query, matches } = useFilteredBpMatches()
  const stats = new Map<string, { hero: string; games: number; blueGames: number; blueWins: number }>()
  for (const match of matches) {
    const first = allSlots(match).find((slot) => slot.phase === 'pick')
    if (!first) continue
    const row = stats.get(first.hero) || { hero: first.hero, games: 0, blueGames: 0, blueWins: 0 }
    row.games += 1
    if (match.winnerSide === 'left' || match.winnerSide === 'right') {
      row.blueGames += 1
      if (match.winnerSide === 'left') row.blueWins += 1
    }
    stats.set(first.hero, row)
  }
  const rows = [...stats.values()].sort((a, b) => b.games - a.games).slice(0, 10)
  return (
    <AnalysisSection title="首抢价值" note="块库 · 征召第一手选人（蓝方）；按模板还原手序后统计次数与蓝方胜率。">
      {query.isLoading ? <Loading label="正在读取 BP 记录…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>首抢英雄</th><th>次数</th><th>蓝方胜率</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.hero}>
                      <td><span className="hero-line"><Portrait name={row.hero} size="sm" /><span>{row.hero}</span></span></td>
                      <td className="is-num">{row.games}</td>
                      <td className="is-num">{percent(row.blueGames ? row.blueWins / row.blueGames * 100 : null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选没有完整手序的局" />}
    </AnalysisSection>
  )
}

export const BP_ORDER_BLOCKS: RegisteredBlock[] = [
  {
    id: 'bp.next-ban',
    base: 'bp.next-ban',
    variant: '下一手',
    domain: 'bp',
    title: '拿到组合后对手下一手',
    question: '我方前两手组合成型后，对手下一手最常 ban 谁？',
    filters: ['range', 'opponent'],
    Component: BpNextBanBlock
  },
  {
    id: 'bp.break-timing',
    base: 'bp.break-timing',
    variant: '拆解时机',
    domain: 'bp',
    title: '组合被拆时机',
    question: '我们的组合是在首轮 ban、二轮 ban 还是被抢拆掉的？',
    filters: ['range', 'opponent'],
    Component: BpBreakTimingBlock
  },
  {
    id: 'bp.first-pick',
    base: 'bp.first-pick',
    variant: '首抢价值',
    domain: 'bp',
    title: '首抢价值',
    question: '第一手选人的英雄，首抢方胜率如何？',
    filters: ['range', 'opponent'],
    Component: BpFirstPickBlock
  }
]
