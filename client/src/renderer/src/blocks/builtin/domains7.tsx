/**
 * 上帝模式 · 第八批注册块（英雄详情 / 出装 / 同路对位）
 * 英雄类块用页面上下文（英雄详情页自动跟当前英雄）；对位块用全量数据。
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useHeroDetail, useLaneMatchup } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { pageContextFromPath } from '../page-context'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState, Portrait } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function usePageHero(): string {
  const location = useLocation()
  return pageContextFromPath(location.pathname).hero || ''
}

function HeroGamesBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useHeroDetail(baseUrl, hero)
  const detail = query.data
  if (!hero) return <AnalysisSection title="当前英雄 · 使用概况"><BoardEmpty title="这个块要放在英雄详情页">打开某个英雄页再从分析库添加。</BoardEmpty></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="当前英雄 · 使用概况"><Loading label="正在读取英雄…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="当前英雄 · 使用概况"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const players = detail.players.slice(0, 10)
  return (
    <AnalysisSection title={`${detail.hero} · 使用概况`} note="块库 · 用当前英雄详情页的上下文；选手使用与胜率。">
      <div className="league-grid is-four">
        <div className="league-card"><span>局数</span><b>{number(detail.games)}</b><em>局</em></div>
        <div className="league-card"><span>使用选手</span><b>{number(detail.players.length)}</b><em>人</em></div>
        <div className="league-card"><span>使用战队</span><b>{number(detail.teams.length)}</b><em>支</em></div>
        <div className="league-card"><span>曲线样本</span><b>{number(detail.curveGames)}</b><em>局</em></div>
      </div>
      {players.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>选手</th><th>局数</th><th>胜率</th><th>KDA</th><th>分均经济</th></tr></thead>
            <tbody>
              {players.map((row) => (
                <tr key={row.name}>
                  <td><span className="hero-line"><Portrait name={row.name} size="sm" /><span>{row.name}</span></span></td>
                  <td className="is-num">{row.games}</td>
                  <td className="is-num">{percent(row.winRate)}</td>
                  <td className="is-num">{number(row.kda, 2)}</td>
                  <td className="is-num">{number(row.gpm)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </AnalysisSection>
  )
}

function HeroBuildsBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useHeroDetail(baseUrl, hero)
  const detail = query.data
  if (!hero) return <AnalysisSection title="常见出装"><BoardEmpty title="这个块要放在英雄详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="常见出装"><Loading label="正在读取出装…" /></AnalysisSection>
  if (query.isError || !detail) return <AnalysisSection title="常见出装"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const builds = detail.playerBuilds.slice(0, 10)
  return (
    <AnalysisSection title={`${detail.hero} · 常见出装`} note="块库 · 按选手出装分组；装备是出现次数。">
      {builds.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>出装</th><th>局数</th><th>胜率</th><th>常见装备</th></tr></thead>
            <tbody>
              {builds.map((build) => (
                <tr key={build.name}>
                  <td>{build.name}</td>
                  <td className="is-num">{build.games}</td>
                  <td className="is-num">{percent(build.winRate)}</td>
                  <td>{build.equips.slice(0, 3).map((item) => `${item.name}×${item.count}`).join(' · ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有出装样本" />}
    </AnalysisSection>
  )
}

function LaneSummaryBlock() {
  const { baseUrl } = useConnection()
  const query = useLaneMatchup(baseUrl)
  const payload = query.data?.payload
  return (
    <AnalysisSection title="同路对位" note="块库 · 同分路双方各一人的局；经济差 = 我方 − 对方。">
      {query.isLoading ? <Loading label="正在读取对位…" />
        : query.isError || !payload ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : payload.lanes.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>分路</th><th>局数</th><th>场均经济差</th><th>领先率</th><th>胜率</th></tr></thead>
                <tbody>
                  {payload.lanes.map((lane) => (
                    <tr key={lane.lane}>
                      <td>{lane.lane}</td>
                      <td className="is-num">{lane.n}</td>
                      <td className="is-num">{lane.avgGoldDiff === null ? '—' : number(lane.avgGoldDiff)}</td>
                      <td className="is-num">{percent(lane.aheadRate)}</td>
                      <td className="is-num">{percent(lane.winRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="没有可判定的同路对位" />}
    </AnalysisSection>
  )
}

function LaneHeroPairsBlock() {
  const { baseUrl } = useConnection()
  const query = useLaneMatchup(baseUrl)
  const rows = (query.data?.payload.heroes || []).slice(0, 12)
  return (
    <AnalysisSection title="对位英雄" note="块库 · 同分路英雄对英雄的局数、经济差、领先率与胜率。">
      {query.isLoading ? <Loading label="正在读取对位…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>我方英雄</th><th>对方英雄</th><th>局数</th><th>经济差</th><th>领先率</th><th>胜率</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={`${row.ownHero}-${row.enemyHero}`}>
                      <td>{row.ownHero}</td>
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
          ) : <BoardEmpty title="没有可用的英雄对位" />}
    </AnalysisSection>
  )
}

function LanePlayerPairsBlock() {
  const { baseUrl } = useConnection()
  const query = useLaneMatchup(baseUrl)
  const rows = (query.data?.payload.players || []).slice(0, 12)
  return (
    <AnalysisSection title="选手对位" note="块库 · 同分路的选手对选手：局数、经济差、领先率与胜率。">
      {query.isLoading ? <Loading label="正在读取对位…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>分路</th><th>本队选手</th><th>对手选手</th><th>局数</th><th>经济差</th><th>胜率</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={`${row.ownPlayer}-${row.enemyPlayer}`}>
                      <td>{row.lane}</td>
                      <td>{row.ownPlayer}</td>
                      <td>{row.enemyPlayer}</td>
                      <td className="is-num">{row.n}</td>
                      <td className="is-num">{row.avgGoldDiff === null ? '—' : number(row.avgGoldDiff)}</td>
                      <td className="is-num">{percent(row.winRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="没有可用的选手对位" />}
    </AnalysisSection>
  )
}

export const HERO_LANE_BLOCKS: RegisteredBlock[] = [
  { id: 'hero.games', base: 'hero.games', variant: '使用概况', domain: 'hero', title: '当前英雄 · 使用概况', question: '这个英雄被哪些选手用、胜率多少？（英雄详情页）', filters: [], Component: HeroGamesBlock },
  { id: 'hero.builds', base: 'hero.builds', variant: '出装', domain: 'hero', title: '常见出装', question: '这个英雄常见出装与胜率？（英雄详情页）', filters: [], Component: HeroBuildsBlock },
  { id: 'lane.summary', base: 'lane.summary', variant: '分路', domain: 'lane', title: '同路对位', question: '五条路的对位经济差、领先率与胜率？', filters: [], Component: LaneSummaryBlock },
  { id: 'lane.hero-pairs', base: 'lane.hero-pairs', variant: '英雄对位', domain: 'lane', title: '对位英雄', question: '哪组英雄对位我们占优？', filters: [], Component: LaneHeroPairsBlock },
  { id: 'lane.player-pairs', base: 'lane.player-pairs', variant: '选手对位', domain: 'lane', title: '选手对位', question: '哪组选手对位我们占优？', filters: [], Component: LanePlayerPairsBlock }
]
