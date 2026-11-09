import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useBpBoard } from '../lib/hooks'
import { duration as fmtDuration, number, percent } from '../lib/format'
import { liftOf, ownBpCounts, teamBpProfile } from '../lib/analysis/teams'
import { AnalysisSection, JumpNav } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { BarList } from '../components/charts/BarList'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'

const JUMP = [
  { id: 'tb-style', label: '风格' },
  { id: 'tb-effect', label: '效果' },
  { id: 'tb-competition', label: '竞争状态' },
  { id: 'tb-picks', label: '选用榜' },
  { id: 'tb-baseline', label: '基准对照' },
  { id: 'tb-bans', label: '禁用对照' },
  { id: 'tb-combos', label: '阵容组合' },
  { id: 'tb-games', label: '逐局名单' }
]

export function TeamBpPage() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const [teamId, setTeamId] = useState('')
  const data = query.data

  if (query.isLoading) return <SkeletonPage cards={3} />
  if (query.isError || !data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const teams = [...data.teams].sort((a, b) => b.matches - a.matches)
  const currentId = teamId || teams[0]?.id || ''
  const profile = teamBpProfile(data, currentId)
  const team = profile.team
  const own = ownBpCounts(profile.games)
  const total = profile.picks.reduce((sum, row) => sum + row.count, 0)
    + profile.bans.reduce((sum, row) => sum + row.count, 0)
    + own.picks.reduce((sum, row) => sum + row.count, 0)
    + own.bans.reduce((sum, row) => sum + row.count, 0)
  const competition = [
    { label: '本队选用', count: own.picks.reduce((sum, row) => sum + row.count, 0), tone: 'own' },
    { label: '本队禁用', count: own.bans.reduce((sum, row) => sum + row.count, 0), tone: 'own-ban' },
    { label: '对手选用', count: profile.picks.reduce((sum, row) => sum + row.count, 0), tone: 'foe' },
    { label: '对手禁用', count: profile.bans.reduce((sum, row) => sum + row.count, 0), tone: 'foe-ban' }
  ].map((row) => ({ ...row, share: total ? row.count / total * 100 : 0 }))
  const topPick = profile.picks[0]
  const topBan = profile.bans[0]
  const decided = profile.wins + profile.losses
  const ourWinRate = decided ? profile.losses / decided * 100 : null

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TEAM BP"
        title={team?.name || '战队 BP'}
        subtitle="按对手战队查看选用、禁用与交手结果；不推断禁选顺序。"
        actions={<Link className="btn" to="/bp">BP 概览</Link>}
      />

      <div className="board-toolbar">
        <label className="board-muted">对手战队</label>
        <select value={currentId} onChange={(event) => setTeamId(event.target.value)} aria-label="选择战队">
          {teams.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.matches} 局</option>)}
        </select>
        <span className="board-muted">教练 {team?.coach || '未录入'} · 覆盖 {profile.games.length} 局</span>
      </div>

      <StatGrid items={[
        { label: '交手局数', value: number(profile.games.length), note: `${profile.wins} 胜 ${profile.losses} 负（对手视角）` },
        { label: '本队胜率', value: percent(ourWinRate), note: `${profile.losses} 胜 / ${decided} 决出`, tone: 'own' },
        { label: '对手选用', value: number(total ? profile.picks.reduce((sum, row) => sum + row.count, 0) : 0), note: `${profile.poolHeroes} 个英雄` },
        { label: '英雄池深度', value: number(profile.poolEffective, 1), note: `1/HHI · 最高占比 ${percent(topPick?.share)}` },
        { label: '对手禁用', value: number(profile.bans.reduce((sum, row) => sum + row.count, 0)), note: `最高 ${topBan?.hero || '—'}` },
        { label: '名单覆盖', value: `${profile.games.filter((game) => game.picks.enemy.length).length} / ${profile.games.length}`, note: '有终局名单的局' }
      ]} />

      <JumpNav items={JUMP} />

      <div className="board-grid-2" id="tb-style">
        <AnalysisSection title="风格" note="英雄池深度用 1/HHI 折算；最高占比越高越集中。">
          <div className="league-grid is-four">
            <div className="league-card"><span>选用英雄数</span><b>{profile.poolHeroes}</b><em>个</em></div>
            <div className="league-card"><span>有效英雄</span><b>{number(profile.poolEffective, 1)}</b><em>1/HHI</em></div>
            <div className="league-card"><span>最高选用占比</span><b>{percent(topPick?.share)}</b><em>{topPick?.hero || '—'}</em></div>
            <div className="league-card"><span>禁用英雄数</span><b>{profile.bans.length}</b><em>个</em></div>
          </div>
        </AnalysisSection>

        <AnalysisSection id="tb-effect" title="效果" note="对手胜率 = 对手在交手中的胜负；覆盖按有名单的局计算。">
          <div className="league-grid is-four">
            <div className="league-card"><span>交手</span><b>{profile.games.length}</b><em>局</em></div>
            <div className="league-card"><span>本队胜率</span><b>{percent(ourWinRate)}</b><em>{profile.losses} 胜 / {decided} 决出</em></div>
            <div className="league-card"><span>名单覆盖</span><b>{profile.games.filter((game) => game.picks.enemy.length).length}</b><em>局</em></div>
            <div className="league-card"><span>最近交手</span><b>{profile.games[0]?.start || '—'}</b><em>场次日期</em></div>
          </div>
        </AnalysisSection>
      </div>

      <AnalysisSection id="tb-competition" title="英雄竞争状态" note="四类名单手数占比；用来区分“被禁”“被选”与“没人碰”。">
        <div className="competition-grid">
          {competition.map((row) => (
            <div className={`competition-cell tone-${row.tone}`} key={row.label}>
              <span>{row.label}</span>
              <b>{row.count}</b>
              <small>{percent(row.share)}</small>
              <i><em style={{ width: `${row.share}%` }} /></i>
            </div>
          ))}
        </div>
      </AnalysisSection>

      <div className="board-grid-2" id="tb-picks">
        <AnalysisSection title="对手选用榜" note="前 10；胜率为对手选到该英雄时的胜率。">
          <BarList items={profile.picks.slice(0, 10).map((row) => ({ label: row.hero, value: row.count, note: `${percent(row.winRate)} · 占比 ${percent(row.share)}`, tone: 'foe' }))} digits={0} />
        </AnalysisSection>

        <AnalysisSection id="tb-baseline" title="全体基准对照" note="Lift = 该对象占比 / 全体对手基准占比；>1 表示更常出现。">
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>英雄</th><th>对象占比</th><th>基准占比</th><th>Lift</th></tr></thead>
              <tbody>
                {profile.picks.slice(0, 8).map((row) => {
                  const base = profile.baselinePicks.find((item) => item.hero === row.hero)
                  const lift = liftOf(row, profile.baselinePicks)
                  return (
                    <tr key={row.hero}>
                      <td>{row.hero}</td>
                      <td className="is-num">{percent(row.share)}</td>
                      <td className="is-num">{percent(base?.share)}</td>
                      <td className={`is-num tone-text-${(lift || 1) >= 1 ? 'own' : 'foe'}`}>{lift === null ? '—' : `${lift.toFixed(2)}×`}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </AnalysisSection>
      </div>

      <div className="board-grid-2" id="tb-bans">
        <AnalysisSection title="禁用对照" note="本队 / 对手各自前 8；不推断针对意图。">
          <div className="bp-mini-grid">
            <div><h4>本队禁用</h4><BarList items={own.bans.slice(0, 8).map((row) => ({ label: row.hero, value: row.count, tone: 'own' }))} digits={0} /></div>
            <div><h4>对手禁用</h4><BarList items={profile.bans.slice(0, 8).map((row) => ({ label: row.hero, value: row.count, tone: 'foe' }))} digits={0} /></div>
          </div>
        </AnalysisSection>

        <AnalysisSection id="tb-combos" title="对手阵容组合" note="对手双人 / 三人组；协同只在后端有基准时展示。">
          <div className="combo-mini">
            <h4>双人</h4>
            {profile.combos2.slice(0, 6).map((combo) => (
              <div className="combo-row" key={combo.heroes.join('|')}>
                <span>{combo.heroes.join(' + ')}</span><b>{combo.games} 局</b><span>{percent(combo.winRate)}</span>
              </div>
            ))}
            <h4>三人</h4>
            {profile.combos3.slice(0, 6).map((combo) => (
              <div className="combo-row" key={combo.heroes.join('|')}>
                <span>{combo.heroes.join(' + ')}</span><b>{combo.games} 局</b><span>{percent(combo.winRate)}</span>
              </div>
            ))}
            {!profile.combos2.length && !profile.combos3.length ? <p className="board-muted">暂无组合样本</p> : null}
          </div>
        </AnalysisSection>
      </div>

      <AnalysisSection id="tb-games" title="逐局 BP 名单" note="最多 8 局；选用与禁用按营地终局名单原样展示。">
        {profile.games.length ? (
          <div className="bp-game-list">
            {profile.games.slice(0, 8).map((game) => (
              <div className="bp-game" key={game.key}>
                <div className="bp-game-head">
                  <b>{game.start}</b><span>{game.side === 'blue' ? '蓝方' : '红方'}</span>
                  <span className={`board-tag tone-${game.result === 'win' ? 'own' : 'foe'}`}>{game.result === 'win' ? '本队胜' : '对手胜'}</span>
                  <small>{fmtDuration(game.duration)}</small>
                </div>
                <div className="bp-game-row">
                  <span className="is-foe">对手</span>
                  {game.picks.enemy.map((entry) => <span key={`foe-${entry.name}`}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
                  <small>禁 {game.bans.enemy.map((entry) => entry.name).join(' · ') || '—'}</small>
                </div>
                <div className="bp-game-row">
                  <span className="is-own">本队</span>
                  {game.picks.own.map((entry) => <span key={`own-${entry.name}`}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
                  <small>禁 {game.bans.own.map((entry) => entry.name).join(' · ') || '—'}</small>
                </div>
              </div>
            ))}
          </div>
        ) : <BoardEmpty title="这支战队还没有 BP 名单" />}
      </AnalysisSection>

      <div className="board-foot">BP 名单不含禁选顺序；对象战队胜率已从“本队视角”翻转成对手视角。本页使用全部营地样本，不套用首页日期筛选。{data.source}</div>
    </div>
  )
}
