/**
 * 上帝模式 · 第五批注册块（单局团队数据 / 经济关键点）
 * 用页面上下文里的 matchKey 取当前单局；加到单局页自动跟局。
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useMatch } from '../../lib/hooks'
import { number, signed } from '../../lib/format'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function useCurrentMatch() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const key = pageContextFromPath(location.pathname).matchKey || ''
  const query = useMatch(baseUrl, key)
  return { key, query }
}

function sideOf(camp: string | undefined): 'left' | 'right' {
  return camp === 'red' || camp === 'right' ? 'right' : 'left'
}

/** 本局团队数据：双方击杀 / 经济 / 输出 / 承伤。 */
function MatchTeamStatsBlock() {
  const { key, query } = useCurrentMatch()
  if (!key) return <AnalysisSection title="本局团队数据"><BoardEmpty title="这个块要放在单局页">打开任意一局，再从分析库添加。</BoardEmpty></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="本局团队数据"><Loading label="正在读取本局…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="本局团队数据"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const detail = query.data
  const own = sideOf(detail.ownCamp)
  const enemy = own === 'left' ? 'right' : 'left'
  const totals = detail.teamTotals || {}
  const ownTotals = totals[own]?.totals
  const enemyTotals = totals[enemy]?.totals
  const row = (label: string, pick: (value?: { kills: number; gold: number; damage: number; taken: number }) => number | undefined) => (
    <tr><td>{label}</td><td className="is-num">{number(pick(ownTotals))}</td><td className="is-num">{number(pick(enemyTotals))}</td></tr>
  )
  return (
    <AnalysisSection title="本局团队数据" note="块库 · 用当前单局页的上下文；本队 vs 对手终局面板。">
      {ownTotals && enemyTotals ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>项目</th><th>本队</th><th>对手</th></tr></thead>
            <tbody>
              {row('击杀', (value) => value?.kills)}
              {row('总经济', (value) => value?.gold)}
              {row('对英雄输出', (value) => value?.damage)}
              {row('总承伤', (value) => value?.taken)}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="这一局没有团队终局面板" />}
    </AnalysisSection>
  )
}

/** 本局经济关键点：10 分钟经济差 + 终局金差。 */
function MatchGoldKeyBlock() {
  const { key, query } = useCurrentMatch()
  if (!key) return <AnalysisSection title="本局经济关键点"><BoardEmpty title="这个块要放在单局页">打开任意一局，再从分析库添加。</BoardEmpty></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="本局经济关键点"><Loading label="正在读取本局…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="本局经济关键点"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const detail = query.data
  const own = sideOf(detail.ownCamp)
  const timeline = detail.process?.timeline || []
  if (!timeline.length) return <AnalysisSection title="本局经济关键点"><BoardEmpty title="这一局没有官方回放经济时间轴" /></AnalysisSection>
  const diffAt = (point: { blueGold: number; redGold: number }) => {
    const raw = point.blueGold - point.redGold
    return own === 'left' ? raw : -raw
  }
  const first = timeline[0]
  const aroundTen = [...timeline].sort((a, b) => Math.abs(a.gameTime - 600) - Math.abs(b.gameTime - 600))[0]
  const last = timeline[timeline.length - 1]
  return (
    <AnalysisSection title="本局经济关键点" note="块库 · 官方回放金币采样；10 分钟点取最接近 600 秒的采样。">
      <div className="league-grid is-four">
        <div className="league-card"><span>开局</span><b>{signed(diffAt(first))}</b><em>本队领先</em></div>
        <div className="league-card"><span>10 分钟</span><b>{signed(diffAt(aroundTen))}</b><em>{Math.round(aroundTen.gameTime / 60)} 分钟点</em></div>
        <div className="league-card"><span>终局</span><b>{signed(diffAt(last))}</b><em>本队领先</em></div>
        <div className="league-card"><span>采样时长</span><b>{number(Math.round(last.gameTime / 60))}</b><em>分钟</em></div>
      </div>
    </AnalysisSection>
  )
}

export const MATCH_DETAIL_BLOCKS: RegisteredBlock[] = [
  {
    id: 'match.team-stats',
    base: 'match.team-stats',
    variant: '双方对照',
    domain: 'match',
    title: '本局团队数据',
    question: '这一局双方击杀/经济/输出/承伤差多少？（单局页）',
    filters: [],
    Component: MatchTeamStatsBlock
  },
  {
    id: 'match.gold-key',
    base: 'match.gold-key',
    variant: '关键点',
    domain: 'match',
    title: '本局经济关键点',
    question: '这一局开局、10 分钟、终局的经济差是多少？（单局页）',
    filters: [],
    Component: MatchGoldKeyBlock
  }
]
