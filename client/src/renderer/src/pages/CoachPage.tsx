import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useBpBoard, useCoachBoard } from '../lib/hooks'
import { duration as fmtDuration, number, percent } from '../lib/format'
import { coachProfile, coachRecords } from '../lib/analysis/bp'
import { AnalysisSection, JumpNav } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { BarList } from '../components/charts/BarList'
import { ScatterChart } from '../components/charts/ScatterChart'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'

const JUMP = [
  { id: 'co-record', label: '带队战绩' },
  { id: 'co-side', label: '边位偏好' },
  { id: 'co-bans', label: '禁用策略' },
  { id: 'co-pool', label: '英雄池' },
  { id: 'co-lineup', label: '阵容对位' },
  { id: 'co-profile', label: '教练画像' }
]

export function CoachPage() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const coachQuery = useCoachBoard(baseUrl)
  const [coach, setCoach] = useState('')
  const data = query.data

  const records = useMemo(() => (data ? coachRecords(data) : []), [data])
  const currentCoach = coach || records.find((row) => row.games > 0)?.coach || records[0]?.coach || ''
  const profile = useMemo(() => (data ? coachProfile(data, currentCoach) : null), [data, currentCoach])

  if (query.isLoading) return <SkeletonPage cards={3} />
  if (query.isError || !data || !profile) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const record = profile.record
  const peers = [...records].sort((a, b) => (b.winRate || 0) - (a.winRate || 0) || b.games - a.games)
  const rank = record ? peers.findIndex((row) => row.coach === record.coach && row.teamId === record.teamId) + 1 : null
  const latest = profile.latest
  const latestRate = latest ? (latest.bans.enemy.length ? profile.banHits / latest.bans.enemy.length * 100 : null) : null
  const lanes = [...new Set(profile.lanePicks.map((row) => row.lane))]
  const scatter = profile.scatter.map((row) => ({
    x: row.pickHeat,
    y: row.banHeat,
    label: row.coach,
    tone: row.coach === currentCoach ? 'own' as const : 'muted' as const,
    note: `选用热度 ${row.pickHeat.toFixed(2)} · 禁用热度 ${row.banHeat.toFixed(2)}`
  }))
  const ownCoach = coachQuery.data?.own.coach

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="COACH"
        title="教练档案"
        subtitle="只看执教与 BP：战绩、边位、禁用、英雄池、阵容对位。"
        actions={<>
          <Link className="btn" to="/bp">BP 概览</Link>
          <Link className="btn" to="/bp/team">战队 BP</Link>
        </>}
      />

      <div className="board-toolbar">
        <label className="board-muted">对手教练</label>
        <select value={currentCoach} onChange={(event) => setCoach(event.target.value)} aria-label="选择教练">
          {records.map((row) => <option value={row.coach} key={`${row.teamId}-${row.coach}`}>{row.coach} · {row.teamName}</option>)}
        </select>
        <span className="board-muted">执教 {record?.games ?? 0} 局 · 本队教练 {ownCoach || '未录入'}</span>
      </div>

      <StatGrid items={[
        { label: '战队', value: record?.teamName || '—', note: currentCoach },
        { label: '执教战绩', value: record ? `${record.wins} 胜 ${record.losses} 负` : '—', note: `胜率 ${percent(record?.winRate)}`, tone: 'accent' },
        { label: '执教局数', value: number(record?.games), note: '有 BP 名单的交手' },
        { label: '同侪排名', value: rank ? `第 ${rank} / ${peers.length}` : '—', note: '按对手胜率' },
        { label: '禁用命中', value: latestRate === null ? '—' : `${profile.banHits}/${profile.banCount}`, note: latest ? `最近一局 · ${percent(latestRate)}` : '无最近一局' },
        { label: '常用英雄', value: profile.picks[0]?.hero || '—', note: profile.picks[0] ? `${profile.picks[0].count} 次` : '' }
      ]} />

      <JumpNav items={JUMP} />

      <div className="board-grid-2" id="co-record">
        <AnalysisSection title="带队战绩" note="对手视角的胜负；同侪站位按胜率排序，样本少会靠后。">
          <div className="record-panel">
            <div className="record-big">
              <strong>{record?.wins ?? 0}<i>:</i>{record?.losses ?? 0}</strong>
              <span>胜 : 负 · {percent(record?.winRate)}</span>
            </div>
            <div className="coach-seats">
              {peers.slice(0, 8).map((row, index) => (
                <button type="button" key={`${row.teamId}-${row.coach}`} className={`coach-seat${row.coach === currentCoach ? ' is-active' : ''}`} onClick={() => setCoach(row.coach)}>
                  <span>{index + 1}</span><b>{row.coach}</b><small>{percent(row.winRate)}</small>
                </button>
              ))}
            </div>
          </div>
        </AnalysisSection>

        <AnalysisSection id="co-side" title="边位偏好" note="教练所在战队的蓝 / 红方战绩；本队视角已翻转。">
          <div className="side-preference">
            {profile.sides.map((side) => (
              <div className="side-pref-card" key={side.side}>
                <span>{side.label}</span>
                <strong>{percent(side.winRate)}</strong>
                <small>{side.games} 局 · {side.wins} 胜</small>
                <i><em style={{ width: `${side.winRate ?? 0}%` }} /></i>
              </div>
            ))}
          </div>
          <p className="board-note">边位只是对手视角的出场分布；样本少时不做“更擅长哪边”的结论。</p>
        </AnalysisSection>
      </div>

      <div className="board-grid-2" id="co-bans">
        <AnalysisSection title="禁用策略" note="全场禁用热度前 10；最近一局的禁准率 = 命中本方常用英雄数 / 禁用数。">
          <BarList items={profile.bans.slice(0, 10).map((row) => ({ label: row.hero, value: row.count, tone: 'muted' }))} digits={0} />
          <div className="league-grid is-four">
            <div className="league-card"><span>最近禁用</span><b>{latest?.bans.enemy.length ?? 0}</b><em>手</em></div>
            <div className="league-card"><span>命中常用</span><b>{profile.banHits}</b><em>手</em></div>
            <div className="league-card"><span>禁准率</span><b>{percent(latestRate)}</b><em>只描述最近一局</em></div>
          </div>
        </AnalysisSection>

        <AnalysisSection id="co-pool" title="英雄池" note="五个分路各取最常选英雄；右侧为最近一局实际五人。">
          <div className="coach-pool">
            {lanes.map((lane) => {
              const rows = profile.lanePicks.filter((row) => row.lane === lane).slice(0, 3)
              return (
                <div className="coach-pool-lane" key={lane}>
                  <b>{lane}</b>
                  {rows.map((row) => <span key={row.hero}>{row.hero}<small>{row.count} 次</small></span>)}
                </div>
              )
            })}
          </div>
          {latest ? (
            <div className="latest-picks">
              <b>最近一局 · {latest.start}</b>
              <span>{latest.picks.enemy.map((entry) => entry.name).join(' · ')}</span>
            </div>
          ) : <BoardEmpty title="没有最近一局" />}
        </AnalysisSection>
      </div>

      <AnalysisSection id="co-lineup" title="阵容对位" note="最近一局五路对照；热度差为正表示教练一方拿到更常用的英雄。">
        {profile.laneMatchup.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>分路</th><th>教练一方</th><th>本队</th><th>教练热度</th><th>本队热度</th><th>热度差</th></tr></thead>
              <tbody>
                {profile.laneMatchup.map((row) => (
                  <tr key={row.lane}>
                    <td>{row.lane}</td>
                    <td>{row.coachHero}</td>
                    <td>{row.ownHero}</td>
                    <td className="is-num">{number(row.heatCoach)}</td>
                    <td className="is-num">{number(row.heatOwn)}</td>
                    <td className={`is-num tone-text-${row.diff >= 0 ? 'foe' : 'own'}`}>{row.diff > 0 ? '+' : ''}{number(row.diff)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="最近一局没有可用的分路名单" />}
      </AnalysisSection>

      <AnalysisSection id="co-profile" title="教练画像" note="横轴选用热度、纵轴禁用热度；点选其他教练切换档案。">
        {scatter.length ? (
          <ScatterChart
            points={scatter}
            xLabel="选用热度"
            yLabel="禁用热度"
            selected={currentCoach}
            onPick={(label) => setCoach(label)}
            height={280}
          />
        ) : <BoardEmpty title="没有教练样本" />}
        <div className="league-grid is-four">
          <div className="league-card"><span>选用排名</span><b>{profile.pickRank ?? '—'}</b><em>最常用英雄在全体中的热度排名</em></div>
          <div className="league-card"><span>禁用排名</span><b>{profile.banRank ?? '—'}</b><em>最常禁英雄在全体中的热度排名</em></div>
          <div className="league-card"><span>分路覆盖</span><b>{lanes.length} / 5</b><em>最近名单涉及分路</em></div>
          <div className="league-card"><span>最近边位</span><b>{latest ? (latest.side === 'blue' ? '蓝方' : '红方') : '—'}</b><em>本队视角</em></div>
        </div>
      </AnalysisSection>

      <div className="board-foot">教练姓名与录入仍在工作台完成；客户端只读展示。最近一局禁准率只描述单局，不推断能力。本页使用全部营地样本。</div>
    </div>
  )
}
