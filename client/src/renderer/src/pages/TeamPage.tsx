import { Link, useParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useBpBoard, useCampCompare, useTeams } from '../lib/hooks'
import { duration as fmtDuration, number, percent, signed } from '../lib/format'
import { teamPath } from '../lib/routes'
import {
  axisTone,
  durationBuckets,
  lanePressure,
  liftOf,
  metricText,
  percentileOf,
  resourceShares,
  rosterStability,
  teamAxes,
  teamBpProfile,
  teamContrast,
  teamMetric,
  teamScore,
  teamTier,
  TEAM_METRICS
} from '../lib/analysis/teams'
import { JumpNav, AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, PercentBar, StatGrid, TierBadge } from '../components/analysis/BoardBits'
import { PercentileRadar } from '../components/charts/PercentileRadar'
import { StackedBars } from '../components/charts/StackedBars'
import { VersusBars } from '../components/charts/VersusBars'
import { ScatterChart } from '../components/charts/ScatterChart'
import { BarList } from '../components/charts/BarList'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'

const JUMP = [
  { id: 'tm-score', label: '得分构成' },
  { id: 'tm-resource', label: '分路资源' },
  { id: 'tm-heroes', label: '英雄与 BP' },
  { id: 'tm-combos', label: '阵容组合' },
  { id: 'tm-rhythm', label: '节奏终结' },
  { id: 'tm-quadrant', label: '风格象限' }
]

export function TeamPage() {
  const { baseUrl } = useConnection()
  const { id = '' } = useParams()
  const teamsQuery = useTeams(baseUrl)
  const compareQuery = useCampCompare(baseUrl, id)
  const bpQuery = useBpBoard(baseUrl)
  const data = teamsQuery.data
  const team = data?.teams.find((item) => item.id === id)

  if (teamsQuery.isLoading) return <SkeletonPage cards={3} />
  if (teamsQuery.isError || !data) {
    return <div className="page"><ErrorState error={teamsQuery.error} onRetry={() => void teamsQuery.refetch()} /></div>
  }
  if (!team) {
    return (
      <div className="page">
        <PageHeader title="战队详情" eyebrow="TEAM" actions={<Link className="btn" to="/teams">战队档案</Link>} />
        <BoardEmpty title="找不到这支战队">可能已被合并或改名。</BoardEmpty>
      </div>
    )
  }

  const compare = compareQuery.data
  const profile = bpQuery.data ? teamBpProfile(bpQuery.data, id) : null
  const score = teamScore(team.percentiles)
  const tier = teamTier(score)
  const axes = teamAxes(team.percentiles)
  const contrast = teamContrast(team, data.own)
  const resourceOpponent = resourceShares(compare, 'enemy')
  const resourceOwn = resourceShares(compare, 'own')
  const pressure = lanePressure(compare)
  const buckets = durationBuckets(team.games)
  const ownTeamWins = team.losses
  const ownTeamLosses = team.wins
  const heroRows = [...(compare?.heroes.enemy || [])].sort((a, b) => b.games - a.games).slice(0, 8)
  const pickRows = profile?.picks.slice(0, 6) || []
  const banRows = profile?.bans.slice(0, 6) || []
  const combos2 = compare?.combos?.enemy?.combos?.slice(0, 4) || []
  const combos3 = compare?.combos3?.enemy?.combos?.slice(0, 4) || []
  const stability = rosterStability(team.roster)
  const conversionValues = data.teams.map((item) => {
    const gpm = item.metrics.gpm
    const dpm = item.metrics.dpm
    return typeof gpm === 'number' && typeof dpm === 'number' && gpm > 0 ? dpm / gpm : null
  }).filter((value): value is number => value !== null)
  const teamConversion = typeof team.metrics.gpm === 'number' && typeof team.metrics.dpm === 'number' && team.metrics.gpm > 0
    ? team.metrics.dpm / team.metrics.gpm
    : null
  const scatter = data.teams.map((item) => {
    const gpm = item.metrics.gpm
    const dpm = item.metrics.dpm
    const conversion = typeof gpm === 'number' && typeof dpm === 'number' && gpm > 0 ? dpm / gpm : null
    return {
      x: item.percentiles.gpm ?? null,
      y: percentileOf(conversion, conversionValues),
      label: item.displayName,
      tone: item.id === team.id ? 'own' as const : 'muted' as const,
      note: `分均经济 ${number(gpm)} · 转化 ${number(conversion, 2)}`
    }
  })
  const strongest = [...axes].filter((axis) => axis.value !== null).sort((a, b) => (b.value || 0) - (a.value || 0))[0]
  const weakest = [...axes].filter((axis) => axis.value !== null).sort((a, b) => (a.value || 0) - (b.value || 0))[0]
  const pressureLane = [...pressure].sort((a, b) => (b.diff || 0) - (a.diff || 0))[0]

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TEAM"
        title={<>{team.displayName}<em>{[team.named ? `教练 ${team.coach || '未录入'}` : '营地阵容聚类', team.firstSeen ? `首次 ${team.firstSeen}` : '', team.lastSeen ? `最近 ${team.lastSeen}` : ''].filter(Boolean).join(' · ')}</em></>}
        actions={<>
          <Link className="btn" to="/teams">战队档案</Link>
          <Link className="btn" to="/teams/roster">阵容</Link>
          <Link className="btn" to="/bp/team">BP</Link>
        </>}
      />

      <StatGrid items={[
        { label: '评分', value: <>{score ?? '—'} <TierBadge tier={tier} /></>, note: '同池权重分', tone: 'accent' },
        { label: '交手', value: number(team.matches), note: `${team.games?.length || 0} 局有明细` },
        { label: '本队战绩', value: `${ownTeamWins} 胜 ${ownTeamLosses} 负`, note: `对手胜率 ${percent(team.winRate)}`, tone: ownTeamWins >= ownTeamLosses ? 'own' : 'foe' },
        { label: '分均经济', value: number(teamMetric(team, 'gpm')), note: `分均输出 ${number(teamMetric(team, 'dpm'))}` },
        { label: '场均时长', value: fmtDuration(teamMetric(team, 'duration')), note: `${number(teamMetric(team, 'towerPerGame'), 1)} 座塔 / 局` },
        { label: '阵容稳定', value: stability === null ? '—' : `${Math.round(stability)}%`, note: '最大五人组占总局数' }
      ]} />

      <JumpNav items={JUMP} />

      <div className="board-grid-2" id="tm-score">
        <AnalysisSection title="得分构成" note="胜率 30% / 分均经济 20% / KDA 20% / 分均输出 15% / 场均推塔 15%，按同池分位加权。">
          <div className="score-panel">
            <div className="score-big"><strong>{score ?? '—'}</strong><span>/ 100</span><TierBadge tier={tier} /></div>
            <div className="pct-list">
              {[
                ['winRate', '胜率'],
                ['gpm', '分均经济'],
                ['kda', 'KDA'],
                ['dpm', '分均输出'],
                ['towerPerGame', '场均推塔']
              ].map(([key, label]) => (
                <div className="pct-row" key={key}>
                  <span>{label}</span>
                  <PercentBar value={team.percentiles[key]} />
                </div>
              ))}
            </div>
          </div>
          <div className="team-radar-wrap">
            <PercentileRadar
              axes={['胜率', '经济', 'KDA', '输出', '推塔', '时长']}
              series={[{
                label: team.displayName,
                tone: 'own',
                values: ['winRate', 'gpm', 'kda', 'dpm', 'towerPerGame', 'duration'].map((key) => team.percentiles[key] ?? null)
              }]}
              size={200}
            />
          </div>
        </AnalysisSection>

        <AnalysisSection title="数据对照" note="本队与对手的绝对值并列；差值为对手 − 本队。">
          <VersusBars
            rows={contrast.map((row) => ({
              label: row.label,
              own: row.own,
              foe: row.foe,
              digits: row.digits,
              suffix: row.suffix
            }))}
            ownTitle={team.displayName}
            foeTitle={data.own.name}
          />
        </AnalysisSection>
      </div>

      <AnalysisSection
        id="tm-resource"
        title="位置资源结构"
        note="按分路统计经济 / 输出 / 承伤的 100% 堆叠；上为对手，下为本队，左右对照看倾斜。"
      >
        <div className="stacked-compare">
          <div>
            <h4>{team.displayName} · 对手</h4>
            <StackedBars rows={[
              { label: '经济', segments: resourceOpponent.map((row) => ({ key: row.lane, label: row.lane, value: row.gold, tone: 'foe' })) },
              { label: '输出', segments: resourceOpponent.map((row) => ({ key: row.lane, label: row.lane, value: row.damage, tone: 'foe' })) },
              { label: '承伤', segments: resourceOpponent.map((row) => ({ key: row.lane, label: row.lane, value: row.taken, tone: 'foe' })) }
            ]} />
          </div>
          <div>
            <h4>{data.own.name} · 本队</h4>
            <StackedBars rows={[
              { label: '经济', segments: resourceOwn.map((row) => ({ key: row.lane, label: row.lane, value: row.gold, tone: 'own' })) },
              { label: '输出', segments: resourceOwn.map((row) => ({ key: row.lane, label: row.lane, value: row.damage, tone: 'own' })) },
              { label: '承伤', segments: resourceOwn.map((row) => ({ key: row.lane, label: row.lane, value: row.taken, tone: 'own' })) }
            ]} />
          </div>
        </div>
      </AnalysisSection>

      <AnalysisSection title="分路对位" note="同分路双方选手的 KDA 与分均经济；只统计能判定分边的局。">
        {pressure.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>分路</th><th>对手选手</th><th>对手 KDA</th><th>对手分均经济</th><th>本队选手</th><th>本队分均经济</th><th>经济差（本队−对手）</th></tr></thead>
              <tbody>
                {pressure.map((row) => (
                  <tr key={row.lane}>
                    <td>{row.lane}</td>
                    <td>{row.enemyName || '—'}</td>
                    <td className="is-num">{number(row.enemyKda, 2)}</td>
                    <td className="is-num">{number(row.enemyGpm)}</td>
                    <td>{row.ownName || '—'}</td>
                    <td className="is-num">{number(row.ownGpm)}</td>
                    <td className={`is-num ${(row.diff || 0) >= 0 ? 'tone-text-own' : 'tone-text-foe'}`}>{signed(row.diff)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="没有可判定的分路对位" />}
      </AnalysisSection>

      <div className="board-grid-2" id="tm-heroes">
        <AnalysisSection title="英雄池" note="按交手局数排序；对手胜率与个人 KDA 只描述这批样本。">
          {heroRows.length ? (
            <div className="hero-pool-list">
              {heroRows.map((row) => (
                <div className="hero-pool-row" key={row.hero}>
                  <Portrait name={row.hero} size="sm" />
                  <Link to={`/heroes/${encodeURIComponent(row.hero)}`}>{row.hero}</Link>
                  <span>{row.games} 局</span>
                  <span>{percent(row.winRate)}</span>
                  <b>{number(row.kda, 2)}</b>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有英雄样本" />}
        </AnalysisSection>

        <AnalysisSection title="BP 偏好" note="营地终局名单口径，不推断禁选顺序；只统计有名单的交手。">
          {profile ? (
            <>
              <div className="bp-mini-grid">
                <div><h4>常选</h4><BarList items={pickRows.map((row) => ({ label: row.hero, value: row.count, note: percent(row.winRate), tone: 'foe' }))} digits={0} /></div>
                <div><h4>常禁</h4><BarList items={banRows.map((row) => ({ label: row.hero, value: row.count, tone: 'muted' }))} digits={0} /></div>
              </div>
              <p className="board-note">覆盖 {profile.games.length} 局 · 池深 {profile.poolHeroes} 个英雄 · 有效英雄 {number(profile.poolEffective, 1)}（1/HHI）。</p>
            </>
          ) : <BoardEmpty title="还没有 BP 名单" />}
        </AnalysisSection>
      </div>

      <div className="board-grid-2" id="tm-combos">
        <AnalysisSection title="阵容组合" note="对手双人 / 三人组合；协同是与单英雄基准的差值，小样本仅供观察。">
          <div className="combo-mini">
            <h4>双人</h4>
            {combos2.length ? combos2.map((combo) => (
              <div className="combo-row" key={combo.heroes.join('|')}>
                <span>{combo.heroes.join(' + ')}</span>
                <b>{combo.games} 局</b>
                <span>{percent(combo.winRate)}</span>
                <small>{combo.synergy === null ? '—' : `${combo.synergy > 0 ? '+' : ''}${combo.synergy.toFixed(1)} pp`}</small>
              </div>
            )) : <p className="board-muted">暂无三人样本</p>}
            <h4>三人</h4>
            {combos3.length ? combos3.map((combo) => (
              <div className="combo-row" key={combo.heroes.join('|')}>
                <span>{combo.heroes.join(' + ')}</span>
                <b>{combo.games} 局</b>
                <span>{percent(combo.winRate)}</span>
                <small>{combo.synergy === null ? '—' : `${combo.synergy > 0 ? '+' : ''}${combo.synergy.toFixed(1)} pp`}</small>
              </div>
            )) : <p className="board-muted">暂无三人样本</p>}
          </div>
        </AnalysisSection>

        <AnalysisSection title="节奏与终结" note="时长分桶与连胜/连败；样本不足时只作观察。">
          <div className="rhythm-list">
            {buckets.map((bucket) => (
              <div className="rhythm-row" key={bucket.label}>
                <span>{bucket.label}</span>
                <i><em style={{ width: `${bucket.games ? bucket.wins / bucket.games * 100 : 0}%` }} /></i>
                <b>{bucket.games} 局 · {bucket.wins} 胜</b>
              </div>
            ))}
          </div>
          <div className="style-notes">
            <span><small>最强轴</small><b>{strongest ? `${strongest.label} ${Math.round(strongest.value || 0)}` : '—'}</b></span>
            <span><small>最弱轴</small><b>{weakest ? `${weakest.label} ${Math.round(weakest.value || 0)}` : '—'}</b></span>
            <span><small>压力路</small><b>{pressureLane ? `${pressureLane.lane} · ${number(pressureLane.diff, 0)} 金` : '—'}</b></span>
          </div>
        </AnalysisSection>
      </div>

      <div className="board-grid-2" id="tm-quadrant">
        <AnalysisSection title="赛前洞察" note="只从分位与分路差提炼，不给因果判断。">
          <div className="insight-list">
            <div><b>强项</b><span>{strongest ? `${strongest.label}处于同池第 ${Math.round(strongest.value || 0)} 分位` : '样本不足'}</span></div>
            <div><b>短板</b><span>{weakest ? `${weakest.label}处于同池第 ${Math.round(weakest.value || 0)} 分位` : '样本不足'}</span></div>
            <div><b>对位压力</b><span>{pressureLane?.diff != null ? `${pressureLane.lane} 对手场均领先 ${number(Math.max(0, pressureLane.diff), 0)} 金` : '无可用对位'}</span></div>
            <div><b>比赛计划</b><span>{team.winRate !== null && team.winRate >= 50 ? '对手胜率偏高，优先压前期资源与视野。' : '对手胜率一般，按正常节奏打分路优势。'}</span></div>
          </div>
        </AnalysisSection>

        <AnalysisSection title="团队风格四象限" note="横轴分均经济分位，纵轴伤害/经济转化分位；点大小在当前版本不编码。">
          <ScatterChart
            points={scatter}
            xLabel="分均经济分位"
            yLabel="伤害转化分位"
            selected={team.displayName}
            height={240}
          />
        </AnalysisSection>
      </div>

      <AnalysisSection title="交手走势" note="最近 10 局；胜负为对手视角，时长与地图来自营地。">
        {team.games?.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>日期</th><th>地图</th><th>结果</th><th>时长</th></tr></thead>
              <tbody>
                {[...(team.games || [])].slice(-10).reverse().map((game) => (
                  <tr key={game.seq}>
                    <td>{game.start}</td>
                    <td>{game.map || '—'}</td>
                    <td><span className={`board-tag tone-${game.win ? 'foe' : 'own'}`}>{game.win ? '对手胜' : '本队胜'}</span></td>
                    <td className="is-num">{fmtDuration(game.duration)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="没有交手明细" />}
      </AnalysisSection>

      <div className="board-foot">对比与分位只作横向读法；待命名战队可在工作台改名，客户端只读。{compareQuery.isError ? ' 分路与英雄数据读取失败。' : ''}</div>
    </div>
  )
}
