/**
 * 上帝模式 · 第十三批注册块（英雄对位 / 选手对位 / 跨局轨迹段 / 单局位置采样）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useCrossVectors, useLaneMatchup, usePositions } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
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

function usePagePlayer(): string {
  const location = useLocation()
  return pageContextFromPath(location.pathname).player || ''
}

/** 当前英雄的同路对位记录。 */
function HeroLaneVsBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useLaneMatchup(baseUrl)
  const rows = (query.data?.payload.heroes || []).filter((row) => row.ownHero === hero).sort((a, b) => b.n - a.n).slice(0, 12)
  return (
    <AnalysisSection title={`${hero || '当前英雄'} · 同路对位`} note="块库 · 英雄详情页上下文；同一英雄对到过的敌方英雄。">
      {!hero ? <BoardEmpty title="这个块要放在英雄详情页" />
        : query.isLoading ? <Loading label="正在读取对位…" />
          : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
            : rows.length ? (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>对方英雄</th><th>局数</th><th>经济差</th><th>领先率</th><th>胜率</th></tr></thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.enemyHero}>
                        <td>{row.enemyHero}</td>
                        <td className="is-num">{row.n}</td>
                        <td className="is-num">{row.avgGoldDiff === null ? '—' : number(row.avgGoldDiff)}</td>
                        <td className="is-num">{percent(row.aheadRate)}</td>
                        <td className="is-num">{percent(row.winRate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <BoardEmpty title="这个英雄还没有可判定的对位" />}
    </AnalysisSection>
  )
}

/** 当前选手的同路对位记录。 */
function PlayerMatchupsBlock() {
  const { baseUrl } = useConnection()
  const player = usePagePlayer()
  const query = useLaneMatchup(baseUrl)
  const rows = (query.data?.payload.players || []).filter((row) => row.ownPlayer === player).sort((a, b) => b.n - a.n).slice(0, 12)
  return (
    <AnalysisSection title={`${player || '当前选手'} · 同路对位`} note="块库 · 选手详情页上下文；同分路对过的对手选手。">
      {!player ? <BoardEmpty title="这个块要放在选手详情页" />
        : query.isLoading ? <Loading label="正在读取对位…" />
          : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
            : rows.length ? (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>分路</th><th>对手选手</th><th>局数</th><th>经济差</th><th>领先率</th><th>胜率</th></tr></thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={`${row.enemyPlayer}-${row.lane}`}>
                        <td>{row.lane}</td>
                        <td>{row.enemyPlayer}</td>
                        <td className="is-num">{row.n}</td>
                        <td className="is-num">{row.avgGoldDiff === null ? '—' : number(row.avgGoldDiff)}</td>
                        <td className="is-num">{percent(row.aheadRate)}</td>
                        <td className="is-num">{percent(row.winRate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <BoardEmpty title="这名选手还没有可判定的对位" />}
    </AnalysisSection>
  )
}

/** 跨局相对时长轨迹：每段的平均位置值。 */
function CrossSegmentsBlock() {
  const { baseUrl } = useConnection()
  const query = useCrossVectors(baseUrl)
  if (query.isLoading) return <AnalysisSection title="跨局轨迹段"><Loading label="正在读取跨局向量…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="跨局轨迹段"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const vectors = query.data.vectors || []
  const length = Math.max(0, ...vectors.map((item) => (item.s || []).length))
  const rows = Array.from({ length }, (_, index) => {
    const values = vectors.map((item) => (item.s || [])[index]).filter((value): value is number => typeof value === 'number')
    return { index, avg: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null, n: values.length }
  })
  return (
    <AnalysisSection title="跨局轨迹段" note={`块库 · 相对对局时长的 ${length} 段轨迹均值；每段按全批最长局动态生成。`}>
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>段</th><th>平均轨迹值</th><th>样本</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.index}>
                  <td>第 {row.index + 1} 段</td>
                  <td className="is-num">{row.avg === null ? '—' : number(row.avg)}</td>
                  <td className="is-num">{row.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有跨局轨迹样本" />}
    </AnalysisSection>
  )
}

/** 本局位置采样概览。 */
function MatchPositionsBlock() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const key = pageContextFromPath(location.pathname).matchKey || ''
  const query = usePositions(baseUrl, key)
  const data = query.data
  if (!key) return <AnalysisSection title="本局位置采样"><BoardEmpty title="这个块要放在单局页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="本局位置采样"><Loading label="正在读取位置…" /></AnalysisSection>
  if (query.isError || !data) return <AnalysisSection title="本局位置采样"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const players = data.players || []
  const points = players.reduce((sum, player) => sum + (player.points || []).length, 0)
  return (
    <AnalysisSection title="本局位置采样" note="块库 · 官方回放逐秒位置；热区/阵线等页面专属图还在原页。">
      <div className="league-grid is-four">
        <div className="league-card"><span>采样时长</span><b>{number(Math.round((data.duration || 0) / 60))}</b><em>分钟</em></div>
        <div className="league-card"><span>采样间隔</span><b>{number(data.step || 0)}</b><em>秒</em></div>
        <div className="league-card"><span>有位置人数</span><b>{number(players.length)}</b><em>人</em></div>
        <div className="league-card"><span>位置点</span><b>{number(points)}</b><em>个</em></div>
      </div>
    </AnalysisSection>
  )
}

export const MATCHUP_CROSS_BLOCKS: RegisteredBlock[] = [
  { id: 'hero.lane-vs', base: 'hero.lane-vs', variant: '对位记录', domain: 'hero', title: '英雄同路对位', question: '这个英雄对到过谁、占优吗？（英雄详情页）', filters: [], Component: HeroLaneVsBlock },
  { id: 'player.matchups', base: 'player.matchups', variant: '对位记录', domain: 'player', title: '选手同路对位', question: '这名选手对过谁、占优吗？（选手详情页）', filters: [], Component: PlayerMatchupsBlock },
  { id: 'cross.segments', base: 'cross.segments', variant: '轨迹段', domain: 'match', title: '跨局轨迹段', question: '跨局相对时长轨迹各段平均在哪？', filters: [], Component: CrossSegmentsBlock },
  { id: 'match.positions', base: 'match.positions', variant: '采样概览', domain: 'match', title: '本局位置采样', question: '这一局的位置数据覆盖多少？（单局页）', filters: [], Component: MatchPositionsBlock }
]
