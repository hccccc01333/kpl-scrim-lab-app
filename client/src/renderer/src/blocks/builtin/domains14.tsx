/**
 * 上帝模式 · 第十五批注册块（教练档案 / 近期比分 / 训练组·版本战绩 / 英雄均值变体）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useCoachBoard, useHeroDetail, useMatches } from '../../lib/hooks'
import { number, percent, scoreText } from '../../lib/format'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function usePageHero(): string {
  const location = useLocation()
  return pageContextFromPath(location.pathname).hero || ''
}

/** 教练档案：每队教练与阵容。 */
function CoachRosterBlock() {
  const { baseUrl } = useConnection()
  const query = useCoachBoard(baseUrl)
  const teams = [...(query.data?.teams || [])].filter((team) => team.named).sort((a, b) => b.players.length - a.players.length)
  return (
    <AnalysisSection title="教练档案" note="块库 · 对手战队教练与阵容（已建档战队）。">
      {query.isLoading ? <Loading label="正在读取教练档案…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : teams.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>战队</th><th>教练</th><th>选手数</th><th>阵容</th></tr></thead>
                <tbody>
                  {teams.map((team) => (
                    <tr key={team.id}>
                      <td>{team.name}</td>
                      <td>{team.coach || '未录入'}</td>
                      <td className="is-num">{team.players.length}</td>
                      <td>{team.players.slice(0, 5).map((player) => `${player.name}${player.lanes?.[0] ? `(${player.lanes[0]})` : ''}`).join(' · ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有已建档的对手" />}
    </AnalysisSection>
  )
}

/** 近期比分。 */
function RecentScoresBlock() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const matches = [...(query.data || [])].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 10)
  return (
    <AnalysisSection title="近期比分" note="块库 · 最近 10 局的比分与结果。">
      {query.isLoading ? <Loading label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : matches.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>日期</th><th>对手</th><th>比分</th><th>结果</th></tr></thead>
                <tbody>
                  {matches.map((match) => (
                    <tr key={match.key}>
                      <td>{match.date}</td>
                      <td>{match.opponent || '未标注'}</td>
                      <td className="is-num">{scoreText(match.scores, match.ownCamp)}</td>
                      <td><span className={`board-tag tone-${match.result === 'win' ? 'own' : match.result === 'loss' ? 'foe' : 'muted'}`}>{match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '—'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有对局" />}
    </AnalysisSection>
  )
}

function groupByBlock(title: string, field: 'session' | 'version', empty: string) {
  return function GroupBlock() {
    const { baseUrl } = useConnection()
    const query = useMatches(baseUrl)
    const rows = new Map<string, { label: string; games: number; decided: number; wins: number }>()
    for (const match of query.data || []) {
      const label = String(match[field] || empty)
      const row = rows.get(label) || { label, games: 0, decided: 0, wins: 0 }
      row.games += 1
      if (match.result === 'win' || match.result === 'loss') { row.decided += 1; if (match.result === 'win') row.wins += 1 }
      rows.set(label, row)
    }
    const list = [...rows.values()].sort((a, b) => b.games - a.games).slice(0, 15)
    return (
      <AnalysisSection title={title} note="块库 · 按对局记录分组统计。">
        {query.isLoading ? <Loading label="正在读取对局…" />
          : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
            : list.length ? (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>{field === 'session' ? '训练组' : '版本'}</th><th>局数</th><th>胜率</th></tr></thead>
                  <tbody>
                    {list.map((row) => (
                      <tr key={row.label}><td>{row.label}</td><td className="is-num">{row.games}</td><td className="is-num">{percent(row.decided ? row.wins / row.decided * 100 : null)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <BoardEmpty title="还没有对局" />}
      </AnalysisSection>
    )
  }
}

const MatchBySessionBlock = groupByBlock('按训练组战绩', 'session', '未标注训练组')
const MatchByVersionBlock = groupByBlock('按版本战绩', 'version', '未标注版本')

/** 英雄均值对照（条形版）。 */
function HeroLeagueBarBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useHeroDetail(baseUrl, hero)
  const detail = query.data
  if (!hero) return <AnalysisSection title="均值对照 · 条形"><BoardEmpty title="这个块要放在英雄详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="均值对照 · 条形"><Loading label="正在读取均值…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="均值对照 · 条形"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = Object.entries(detail.league || {}).filter(([, value]) => value.hero !== null && value.all !== null)
  return (
    <AnalysisSection title={`${detail.hero} · 均值对照`} note="块库 · 条形版：该英雄 vs 全英雄均值。">
      {rows.length ? (
        <div className="bar-list">
          {rows.map(([key, value]) => {
            const max = Math.max(Math.abs(value.hero || 0), Math.abs(value.all || 0)) || 1
            return (
              <div className="bar-row" key={key}>
                <span>{key}</span>
                <div className="meter"><i style={{ width: `${Math.min(100, Math.abs(value.hero || 0) / max * 100)}%` }} /></div>
                <b>{number(value.hero, 1)} / {number(value.all, 1)}</b>
              </div>
            )
          })}
        </div>
      ) : <BoardEmpty title="还没有均值样本" />}
    </AnalysisSection>
  )
}

export const COACH_MATCH_MISC_BLOCKS: RegisteredBlock[] = [
  { id: 'coach.roster', base: 'coach.roster', variant: '档案', domain: 'team', title: '教练档案', question: '对手教练与阵容是谁？', filters: [], Component: CoachRosterBlock },
  { id: 'match.scores', base: 'match.scores', variant: '比分', domain: 'match', title: '近期比分', question: '最近 10 局的比分与结果？', filters: [], Component: RecentScoresBlock },
  { id: 'match.by-session', base: 'match.by-session', variant: '训练组', domain: 'match', title: '按训练组战绩', question: '每个训练组打了多少局、胜率多少？', filters: [], Component: MatchBySessionBlock },
  { id: 'match.by-version', base: 'match.by-version', variant: '版本', domain: 'match', title: '按版本战绩', question: '每个版本打了多少局、胜率多少？', filters: [], Component: MatchByVersionBlock },
  { id: 'hero.league-bar', base: 'hero.league-bar', variant: '条形', domain: 'hero', title: '均值对照 · 条形', question: '这个英雄与全英雄均值对比（条形版）？（英雄详情页）', filters: [], Component: HeroLeagueBarBlock }
]
