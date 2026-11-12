/**
 * 上帝模式 · 第三批注册块（比赛 / 战队）
 * 全部自带数据，可加到任意页面。
 */
import { useConnection } from '../../lib/app-context'
import { useMatches, useTeams } from '../../lib/hooks'
import { number, percent, signed } from '../../lib/format'
import { goldDiffOf } from '../../lib/analysis/matches'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 近期走势：最近 10 局胜负与胜率。 */
function MatchFormBlock() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const matches = query.data || []
  const recent = [...matches].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 10)
  const decided = matches.filter((match) => match.result === 'win' || match.result === 'loss')
  const wins = decided.filter((match) => match.result === 'win').length
  return (
    <AnalysisSection title="近期走势" note="块库 · 最近 10 局走势与当前样本胜率。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : recent.length ? (
            <>
              <div className="board-muted" style={{ marginBottom: 8 }}>
                {recent.length} 局内 {recent.filter((match) => match.result === 'win').length} 胜 · 全样本胜率 {percent(decided.length ? wins / decided.length * 100 : null)}
              </div>
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>日期</th><th>对手</th><th>结果</th><th>金差</th></tr></thead>
                  <tbody>
                    {recent.map((match) => (
                      <tr key={match.key}>
                        <td>{match.date}</td>
                        <td>{match.opponent || '未标注'}</td>
                        <td><span className={`board-tag tone-${match.result === 'win' ? 'own' : match.result === 'loss' ? 'foe' : 'muted'}`}>{match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '—'}</span></td>
                        <td className="is-num">{signed(goldDiffOf(match))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : <BoardEmpty title="还没有对局" />}
    </AnalysisSection>
  )
}

/** 按对手战绩：交手局数、胜率、场均金差。 */
function MatchByOpponentBlock() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const rows = new Map<string, { opponent: string; games: number; decided: number; wins: number; diffSum: number; diffN: number }>()
  for (const match of query.data || []) {
    const key = match.opponent || '未标注'
    const row = rows.get(key) || { opponent: key, games: 0, decided: 0, wins: 0, diffSum: 0, diffN: 0 }
    row.games += 1
    if (match.result === 'win' || match.result === 'loss') {
      row.decided += 1
      if (match.result === 'win') row.wins += 1
    }
    const diff = goldDiffOf(match)
    if (typeof diff === 'number' && Number.isFinite(diff)) {
      row.diffSum += diff
      row.diffN += 1
    }
    rows.set(key, row)
  }
  const list = [...rows.values()].sort((a, b) => b.games - a.games)
  return (
    <AnalysisSection title="按对手战绩" note="块库 · 交手局数、胜率与场均金差；只统计有胜负的局。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : list.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>交手</th><th>胜率</th><th>场均金差</th></tr></thead>
                <tbody>
                  {list.map((row) => (
                    <tr key={row.opponent}>
                      <td>{row.opponent}</td>
                      <td className="is-num">{row.games}</td>
                      <td className="is-num">{percent(row.decided ? row.wins / row.decided * 100 : null)}</td>
                      <td className="is-num">{row.diffN ? signed(row.diffSum / row.diffN) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有对局" />}
    </AnalysisSection>
  )
}

/** 战队名册：局数、胜率、最近交手。 */
function TeamRosterBlock() {
  const { baseUrl } = useConnection()
  const query = useTeams(baseUrl)
  const teams = [...(query.data?.teams || [])].sort((a, b) => (b.matches || 0) - (a.matches || 0))
  return (
    <AnalysisSection title="战队名册" note="块库 · 已覆盖的对手战队、交手局数与胜率。">
      {query.isLoading ? <Loading label="正在读取战队…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : teams.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>战队</th><th>局数</th><th>胜率</th><th>最近交手</th></tr></thead>
                <tbody>
                  {teams.map((team) => (
                    <tr key={team.id}>
                      <td>{team.displayName || team.name}</td>
                      <td className="is-num">{number(team.matches)}</td>
                      <td className="is-num">{percent(team.winRate)}</td>
                      <td>{team.lastSeen || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有战队样本" />}
    </AnalysisSection>
  )
}

export const MATCH_TEAM_BLOCKS: RegisteredBlock[] = [
  {
    id: 'match.form',
    base: 'match.form',
    variant: '近10局',
    domain: 'match',
    title: '近期走势',
    question: '最近 10 局赢得怎么样？当前样本胜率多少？',
    filters: [],
    Component: MatchFormBlock
  },
  {
    id: 'match.by-opponent',
    base: 'match.by-opponent',
    variant: '按对手',
    domain: 'match',
    title: '按对手战绩',
    question: '对每个对手交手多少局、胜率多少？',
    filters: [],
    Component: MatchByOpponentBlock
  },
  {
    id: 'team.roster',
    base: 'team.roster',
    variant: '名册',
    domain: 'team',
    title: '战队名册',
    question: '覆盖了哪些对手战队？交手多少局？',
    filters: [],
    Component: TeamRosterBlock
  }
]
