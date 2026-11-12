/**
 * 上帝模式 · 第七批注册块（资源 / 推塔 / 节奏 / 英雄出场）
 */
import { useConnection } from '../../lib/app-context'
import { useBpBoard, useCampCompare, useMatches } from '../../lib/hooks'
import { duration as fmtDuration, number, percent } from '../../lib/format'
import { heroRows } from '../../lib/analysis/heroes'
import { goldDiffOf } from '../../lib/analysis/matches'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function stat(value: unknown): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : 0
}

function WeatherTable({ rows }: { rows: { label: string; own: string; enemy: string }[] }) {
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead><tr><th>项目</th><th>本队</th><th>对手</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}><td>{row.label}</td><td className="is-num">{row.own}</td><td className="is-num">{row.enemy}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 推塔数：绝对数值，场均与总。 */
function BpTowersBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const games = query.data?.games || []
  let own = 0, enemy = 0, n = 0
  for (const game of games) {
    if (game.duration) n += 1
    own += stat(game.stats.own.towerCnt)
    enemy += stat(game.stats.enemy.towerCnt)
  }
  return (
    <AnalysisSection title="推塔数" note="块库 · 绝对数值（不换算占比）；营地终局面板 towerCnt。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : games.length ? (
            <WeatherTable rows={[
              { label: '总推塔', own: number(own), enemy: number(enemy) },
              { label: '场均推塔', own: n ? number(own / n, 1) : '—', enemy: n ? number(enemy / n, 1) : '—' },
              { label: '样本局', own: number(games.length), enemy: number(games.length) }
            ]} />
          ) : <BoardEmpty title="还没有 BP 样本" />}
    </AnalysisSection>
  )
}

/** 分均经济：终局经济 ÷ 对局分钟。 */
function BpGpmBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const games = query.data?.games || []
  let own = 0, enemy = 0, n = 0
  for (const game of games) {
    const minutes = (game.duration || 0) / 60
    if (!minutes) continue
    own += stat(game.stats.own.money) / minutes
    enemy += stat(game.stats.enemy.money) / minutes
    n += 1
  }
  return (
    <AnalysisSection title="分均经济" note="块库 · 终局总经济 ÷ 对局分钟；只统计有时长的局。">
      {query.isLoading ? <Loading label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : n ? (
            <WeatherTable rows={[
              { label: '分均经济', own: number(own / n), enemy: number(enemy / n) },
              { label: '分均经济差', own: number(own / n - enemy / n), enemy: '—' },
              { label: '样本局', own: number(n), enemy: number(n) }
            ]} />
          ) : <BoardEmpty title="还没有有时长的局" />}
    </AnalysisSection>
  )
}

/** 对局时长分布。 */
function MatchDurationBlock() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const buckets = [
    { label: '12 分钟内', test: (m: number) => m < 12 },
    { label: '12–16 分钟', test: (m: number) => m >= 12 && m < 16 },
    { label: '16–20 分钟', test: (m: number) => m >= 16 && m < 20 },
    { label: '20 分钟以上', test: (m: number) => m >= 20 }
  ]
  const matches = (query.data || []).filter((match) => (match.duration || 0) > 0)
  return (
    <AnalysisSection title="对局时长" note="块库 · 按营地记录时长分箱；括号里是胜率。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : matches.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>时长区间</th><th>局数</th><th>胜率</th></tr></thead>
                <tbody>
                  {buckets.map((bucket) => {
                    const list = matches.filter((match) => bucket.test((match.duration || 0) / 60))
                    const decided = list.filter((match) => match.result === 'win' || match.result === 'loss')
                    const wins = decided.filter((match) => match.result === 'win').length
                    return (
                      <tr key={bucket.label}>
                        <td>{bucket.label}</td>
                        <td className="is-num">{list.length}</td>
                        <td className="is-num">{percent(decided.length ? wins / decided.length * 100 : null)}</td>
                      </tr>
                    )
                  })}
                  <tr><td>场均时长</td><td className="is-num">{fmtDuration(matches.reduce((sum, match) => sum + (match.duration || 0), 0) / matches.length)}</td><td /></tr>
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有有时长的对局" />}
    </AnalysisSection>
  )
}

/** 金差分布：按终局金差分箱。 */
function MatchGoldBlock() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const buckets = [
    { label: '领先 8k+', test: (diff: number) => diff >= 8000 },
    { label: '领先 0–8k', test: (diff: number) => diff >= 0 && diff < 8000 },
    { label: '落后 0–8k', test: (diff: number) => diff < 0 && diff > -8000 },
    { label: '落后 8k+', test: (diff: number) => diff <= -8000 }
  ]
  const matches = (query.data || []).filter((match) => typeof goldDiffOf(match) === 'number')
  return (
    <AnalysisSection title="终局金差分布" note="块库 · 按终局经济差分箱；括号里是胜率。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : matches.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>金差区间</th><th>局数</th><th>胜率</th></tr></thead>
                <tbody>
                  {buckets.map((bucket) => {
                    const list = matches.filter((match) => bucket.test(goldDiffOf(match) as number))
                    const decided = list.filter((match) => match.result === 'win' || match.result === 'loss')
                    const wins = decided.filter((match) => match.result === 'win').length
                    return (
                      <tr key={bucket.label}>
                        <td>{bucket.label}</td>
                        <td className="is-num">{list.length}</td>
                        <td className="is-num">{percent(decided.length ? wins / decided.length * 100 : null)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有金差数据" />}
    </AnalysisSection>
  )
}

/** 英雄出场分布：按出场人次排。 */
function HeroAppearBlock() {
  const { baseUrl } = useConnection()
  const query = useCampCompare(baseUrl)
  if (query.isLoading) return <AnalysisSection title="英雄出场分布"><Loading label="正在读取英雄…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="英雄出场分布"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = heroRows(query.data, 'own').filter((row) => row.games > 0).sort((a, b) => b.games - a.games).slice(0, 12)
  return (
    <AnalysisSection title="英雄出场分布" note="块库 · 本队英雄出场人次与胜率；按出场排序。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>英雄</th><th>分路</th><th>出场</th><th>胜率</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.hero}-${row.lane}`}>
                  <td>{row.hero}</td>
                  <td>{row.lane || '—'}</td>
                  <td className="is-num">{row.games}</td>
                  <td className="is-num">{percent(row.winRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有英雄出场样本" />}
    </AnalysisSection>
  )
}

export const RESOURCE_BLOCKS: RegisteredBlock[] = [
  { id: 'bp.towers', base: 'bp.towers', variant: '绝对数', domain: 'bp', title: '推塔数', question: '本队和对手的推塔总数、场均是多少？', filters: [], Component: BpTowersBlock },
  { id: 'bp.gpm', base: 'bp.gpm', variant: '分均', domain: 'bp', title: '分均经济', question: '本队和对手的分均经济差多少？', filters: [], Component: BpGpmBlock },
  { id: 'match.duration', base: 'match.duration', variant: '分布', domain: 'match', title: '对局时长', question: '各时长区间的局数与胜率？', filters: [], Component: MatchDurationBlock },
  { id: 'match.gold-dist', base: 'match.gold-dist', variant: '分布', domain: 'match', title: '终局金差分布', question: '赢的局和金差的局各在哪个区间？', filters: [], Component: MatchGoldBlock },
  { id: 'hero.appear', base: 'hero.appear', variant: '出场榜', domain: 'hero', title: '英雄出场分布', question: '本队英雄出场人次排行与胜率？', filters: [], Component: HeroAppearBlock }
]
