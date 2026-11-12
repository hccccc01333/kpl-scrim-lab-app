/**
 * 上帝模式 · 第十批注册块（选手详情 + 跨局总览）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useCrossVectors, usePlayer } from '../../lib/hooks'
import { number, percent, signed } from '../../lib/format'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function usePagePlayer(): string {
  const location = useLocation()
  return pageContextFromPath(location.pathname).player || ''
}

/** 选手概览：局数/胜率/产出/参团。 */
function PlayerStatsBlock() {
  const { baseUrl } = useConnection()
  const player = usePagePlayer()
  const query = usePlayer(baseUrl, player)
  const stats = query.data?.stats
  if (!player) return <AnalysisSection title="选手概览"><BoardEmpty title="这个块要放在选手详情页">打开某个选手页再从分析库添加。</BoardEmpty></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="选手概览"><Loading label="正在读取选手…" /></AnalysisSection>
  if (query.isError) return <AnalysisSection title="选手概览"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  if (!stats) return <AnalysisSection title="选手概览"><BoardEmpty title="这名选手还没有可用样本" /></AnalysisSection>
  return (
    <AnalysisSection title={`${stats.label} · 选手概览`} note="块库 · 用当前选手详情页的上下文；营地十人面板口径。">
      <div className="league-grid is-four">
        <div className="league-card"><span>局数</span><b>{number(stats.matches)}</b><em>局</em></div>
        <div className="league-card"><span>胜率</span><b>{percent(stats.winRate)}</b><em>{stats.wins} 胜 / {stats.decided} 局</em></div>
        <div className="league-card"><span>KDA</span><b>{number(stats.kda, 2)}</b><em>{stats.kills}/{stats.deaths}/{stats.assists}</em></div>
        <div className="league-card"><span>参团</span><b>{percent(stats.participation)}</b><em>参团率</em></div>
        <div className="league-card"><span>分均经济</span><b>{number(stats.gpm)}</b><em>GPM</em></div>
        <div className="league-card"><span>分均输出</span><b>{number(stats.dpm)}</b><em>DPM</em></div>
        <div className="league-card"><span>经济占比</span><b>{percent(stats.goldShare)}</b><em>队内</em></div>
        <div className="league-card"><span>输出占比</span><b>{percent(stats.damageShare)}</b><em>队内</em></div>
      </div>
    </AnalysisSection>
  )
}

/** 选手最近对局。 */
function PlayerRecentBlock() {
  const { baseUrl } = useConnection()
  const player = usePagePlayer()
  const query = usePlayer(baseUrl, player)
  if (!player) return <AnalysisSection title="最近对局"><BoardEmpty title="这个块要放在选手详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="最近对局"><Loading label="正在读取选手…" /></AnalysisSection>
  if (query.isError) return <AnalysisSection title="最近对局"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = [...(query.data?.points || [])].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 10)
  return (
    <AnalysisSection title={`${query.data?.label || player} · 最近对局`} note="块库 · 最近 10 局逐局数据。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>日期</th><th>对手</th><th>英雄</th><th>结果</th><th>KDA</th><th>分均经济</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.matchKey}>
                  <td>{row.date}</td>
                  <td>{row.opponent || '未标注'}</td>
                  <td>{row.hero}</td>
                  <td><span className={`board-tag tone-${row.result === 'win' ? 'own' : row.result === 'loss' ? 'foe' : 'muted'}`}>{row.result === 'win' ? '胜' : row.result === 'loss' ? '负' : '—'}</span></td>
                  <td className="is-num">{number(row.kda, 2)}</td>
                  <td className="is-num">{number(row.gpm)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有逐局样本" />}
    </AnalysisSection>
  )
}

/** 跨局总览。 */
function CrossOverviewBlock() {
  const { baseUrl } = useConnection()
  const query = useCrossVectors(baseUrl)
  const data = query.data
  if (query.isLoading) return <AnalysisSection title="跨局总览"><Loading label="正在读取跨局向量…" /></AnalysisSection>
  if (query.isError || !data) return <AnalysisSection title="跨局总览"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const vectors = data.vectors || []
  const withDiff = vectors.filter((item) => typeof item.finalDiff === 'number')
  const withAt10 = vectors.filter((item) => typeof item.at10 === 'number')
  const avg = (list: number[]) => list.length ? list.reduce((sum, value) => sum + value, 0) / list.length : null
  const decided = vectors.filter((item) => item.result === 'win' || item.result === 'loss')
  const wins = decided.filter((item) => item.result === 'win').length
  return (
    <AnalysisSection title="跨局总览" note="块库 · 基于全量跨局向量；终局金差与 10 分钟经济差。">
      <div className="league-grid is-four">
        <div className="league-card"><span>样本局</span><b>{number(data.total)}</b><em>局</em></div>
        <div className="league-card"><span>胜率</span><b>{percent(decided.length ? wins / decided.length * 100 : null)}</b><em>{wins} 胜 / {decided.length} 局</em></div>
        <div className="league-card"><span>场均终局金差</span><b>{signed(avg(withDiff.map((item) => item.finalDiff as number)))}</b><em>{withDiff.length} 局</em></div>
        <div className="league-card"><span>场均 10 分钟差</span><b>{signed(avg(withAt10.map((item) => item.at10 as number)))}</b><em>{withAt10.length} 局</em></div>
      </div>
    </AnalysisSection>
  )
}

/** 跨局按对手。 */
function CrossOpponentBlock() {
  const { baseUrl } = useConnection()
  const query = useCrossVectors(baseUrl)
  const rows = new Map<string, { opponent: string; games: number; decided: number; wins: number; diffSum: number; diffN: number }>()
  for (const item of query.data?.vectors || []) {
    const key = item.opponent || '未标注'
    const row = rows.get(key) || { opponent: key, games: 0, decided: 0, wins: 0, diffSum: 0, diffN: 0 }
    row.games += 1
    if (item.result === 'win' || item.result === 'loss') { row.decided += 1; if (item.result === 'win') row.wins += 1 }
    if (typeof item.finalDiff === 'number') { row.diffSum += item.finalDiff; row.diffN += 1 }
    rows.set(key, row)
  }
  const list = [...rows.values()].sort((a, b) => b.games - a.games).slice(0, 12)
  return (
    <AnalysisSection title="跨局按对手" note="块库 · 按对手汇总跨局向量。">
      {query.isLoading ? <Loading label="正在读取跨局向量…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : list.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>局数</th><th>胜率</th><th>场均金差</th></tr></thead>
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
          ) : <BoardEmpty title="还没有跨局样本" />}
    </AnalysisSection>
  )
}

/** 领先转化：10 分钟领先时胜率。 */
function CrossEarlyLeadBlock() {
  const { baseUrl } = useConnection()
  const query = useCrossVectors(baseUrl)
  const vectors = (query.data?.vectors || []).filter((item) => typeof item.at10 === 'number' && (item.result === 'win' || item.result === 'loss'))
  const ahead = vectors.filter((item) => (item.at10 as number) > 0)
  const behind = vectors.filter((item) => (item.at10 as number) < 0)
  const rate = (list: typeof vectors) => list.length ? list.filter((item) => item.result === 'win').length / list.length * 100 : null
  return (
    <AnalysisSection title="领先转化" note="块库 · 10 分钟经济差领先/落后时各自的胜率（时间关联，非因果）。">
      {query.isLoading ? <Loading label="正在读取跨局向量…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : vectors.length ? (
            <div className="league-grid is-four">
              <div className="league-card"><span>10 分钟领先</span><b>{number(ahead.length)}</b><em>局 · 胜率 {percent(rate(ahead))}</em></div>
              <div className="league-card"><span>10 分钟落后</span><b>{number(behind.length)}</b><em>局 · 胜率 {percent(rate(behind))}</em></div>
              <div className="league-card"><span>样本</span><b>{number(vectors.length)}</b><em>有胜负的局</em></div>
              <div className="league-card"><span>窗口</span><b>{number(query.data?.windowMin || 0)}</b><em>分钟</em></div>
            </div>
          ) : <BoardEmpty title="还没有可用的跨局样本" />}
    </AnalysisSection>
  )
}

export const PLAYER_CROSS_BLOCKS: RegisteredBlock[] = [
  { id: 'player.stats', base: 'player.stats', variant: '概览', domain: 'player', title: '选手概览', question: '这名选手的局数/胜率/产出/参团？（选手详情页）', filters: [], Component: PlayerStatsBlock },
  { id: 'player.recent', base: 'player.recent', variant: '最近对局', domain: 'player', title: '选手最近对局', question: '这名选手最近 10 局打得怎么样？（选手详情页）', filters: [], Component: PlayerRecentBlock },
  { id: 'cross.overview', base: 'cross.overview', variant: '总览', domain: 'match', title: '跨局总览', question: '跨局样本的胜率、终局金差、10 分钟差是多少？', filters: [], Component: CrossOverviewBlock },
  { id: 'cross.by-opponent', base: 'cross.by-opponent', variant: '按对手', domain: 'match', title: '跨局按对手', question: '按对手看跨局胜率与金差？', filters: [], Component: CrossOpponentBlock },
  { id: 'cross.early-lead', base: 'cross.early-lead', variant: '领先转化', domain: 'match', title: '领先转化', question: '10 分钟领先/落后时各自胜率多少？', filters: [], Component: CrossEarlyLeadBlock }
]
