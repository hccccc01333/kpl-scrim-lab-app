/**
 * 上帝模式 · 第十二批注册块（英雄搭档 / 选手英雄池 / 选手名单 / 对手 BP 偏好）
 */
import { useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useCampPartners, usePlayer, usePlayerBoard, useTeamBp } from '../../lib/hooks'
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

/** 英雄搭档：常用搭档与协同。 */
function HeroPartnersBlock() {
  const { baseUrl } = useConnection()
  const hero = usePageHero()
  const query = useCampPartners(baseUrl, hero)
  const data = query.data
  if (!hero) return <AnalysisSection title="常用搭档"><BoardEmpty title="这个块要放在英雄详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="常用搭档"><Loading label="正在读取搭档…" /></AnalysisSection>
  if (query.isError || !data) return <AnalysisSection title="常用搭档"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = (data.partners || []).slice(0, 10)
  return (
    <AnalysisSection title={`${data.hero} · 常用搭档`} note="块库 · 同阵营同局共现；协同 = 组合胜率 − 成员单英雄均值。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>搭档</th><th>同场</th><th>组合胜率</th><th>协同</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.partner}>
                  <td>{row.partner}</td>
                  <td className="is-num">{row.games}</td>
                  <td className="is-num">{percent(row.winRate)}</td>
                  <td className="is-num">{row.synergy === null || row.synergy === undefined ? '—' : `${row.synergy > 0 ? '+' : ''}${row.synergy.toFixed(1)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有达到样本门槛的搭档" />}
    </AnalysisSection>
  )
}

/** 选手英雄池。 */
function PlayerHeroPoolBlock() {
  const { baseUrl } = useConnection()
  const player = usePagePlayer()
  const query = usePlayer(baseUrl, player)
  const stats = query.data?.stats
  if (!player) return <AnalysisSection title="选手英雄池"><BoardEmpty title="这个块要放在选手详情页" /></AnalysisSection>
  if (query.isLoading) return <AnalysisSection title="选手英雄池"><Loading label="正在读取选手…" /></AnalysisSection>
  if (query.isError) return <AnalysisSection title="选手英雄池"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = [...(stats?.heroes || [])].sort((a, b) => b.matches - a.matches).slice(0, 12)
  return (
    <AnalysisSection title={`${stats?.label || player} · 英雄池`} note="块库 · 这名选手用过的英雄与场次。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>英雄</th><th>场次</th></tr></thead>
            <tbody>
              {rows.map((row) => <tr key={row.hero}><td>{row.hero}</td><td className="is-num">{row.matches}</td></tr>)}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有英雄池样本" />}
    </AnalysisSection>
  )
}

/** 选手名单（全部）。 */
function PlayerRosterTableBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayerBoard(baseUrl)
  const rows = [...(query.data?.roster || [])].sort((a, b) => b.games - a.games).slice(0, 20)
  return (
    <AnalysisSection title="选手名单" note="块库 · 已认领选手的局数、胜率、KDA 与分均经济。">
      {query.isLoading ? <Loading label="正在读取选手名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>选手</th><th>位置</th><th>局数</th><th>胜率</th><th>KDA</th><th>分均经济</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.label}</td>
                      <td>{row.position || '—'}</td>
                      <td className="is-num">{row.games}</td>
                      <td className="is-num">{percent(row.winRate)}</td>
                      <td className="is-num">{number(row.kda, 2)}</td>
                      <td className="is-num">{number(row.gpm)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有选手名单" />}
    </AnalysisSection>
  )
}

/** 对手 BP 偏好：每队常用选/禁。 */
function TeamBpTendencyBlock() {
  const { baseUrl } = useConnection()
  const query = useTeamBp(baseUrl)
  const rows = [...(query.data || [])].sort((a, b) => b.games - a.games).slice(0, 12)
  return (
    <AnalysisSection title="对手 BP 偏好" note="块库 · 每支对手的选用/禁用前 3（按战队 BP 数据）。">
      {query.isLoading ? <Loading label="正在读取战队 BP…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>局数</th><th>常用选</th><th>常用禁</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.name}</td>
                      <td className="is-num">{row.games}</td>
                      <td>{(row.picks || []).slice(0, 3).map((item) => `${item.hero} ${item.count}`).join(' · ') || '—'}</td>
                      <td>{(row.bans || []).slice(0, 3).map((item) => `${item.hero} ${item.count}`).join(' · ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有战队 BP 样本" />}
    </AnalysisSection>
  )
}

export const PARTNER_ROSTER_BLOCKS: RegisteredBlock[] = [
  { id: 'hero.partners', base: 'hero.partners', variant: '搭档', domain: 'hero', title: '常用搭档', question: '这个英雄和谁一起拿最多、协同多少？（英雄详情页）', filters: [], Component: HeroPartnersBlock },
  { id: 'player.hero-pool', base: 'player.hero-pool', variant: '英雄池', domain: 'player', title: '选手英雄池', question: '这名选手用过哪些英雄？（选手详情页）', filters: [], Component: PlayerHeroPoolBlock },
  { id: 'player.roster-full', base: 'player.roster-full', variant: '名单', domain: 'player', title: '选手名单（认领）', question: '已认领选手的局数、胜率与产出？', filters: [], Component: PlayerRosterTableBlock },
  { id: 'bp.team-tendency', base: 'bp.team-tendency', variant: '偏好', domain: 'bp', title: '对手 BP 偏好', question: '每支对手最常选/禁什么？', filters: [], Component: TeamBpTendencyBlock }
]
