import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useConnection, useSettings } from '../lib/app-context'
import { useMatch, usePositions, useReplay } from '../lib/hooks'
import {
  duration as fmtDuration,
  number,
  percent,
  resultLabel,
  resultTone,
  scoreText,
  sideLabel,
  signed
} from '../lib/format'
import { useAppMeta } from '../lib/meta-context'
import { pushToast } from '../lib/toast'
import type { Draft, HeroPick, MatchPlayer } from '../lib/types'
import {
  DEEP,
  HALF,
  HEAT_WINDOW,
  LANES,
  buildBattle,
  buildMetrics,
  buildSeries,
  biggestTurn,
  clamp,
  duelDepth,
  duelPairs,
  foeCampOf,
  frontline,
  heatCounts,
  invadeSummary,
  invasionOf,
  invasionStats,
  isNum,
  keyNodes,
  laneOf,
  ownCampOf,
  phaseRows,
  playerKey,
  prepareHeat,
  proximity,
  teamMetricRows,
  totalRows,
  type Camp,
  type DeathRow,
  type Lane,
  type ProximityStat
} from '../lib/analysis/match'
import { AnalysisSection, JumpNav, ScopeNote } from '../components/analysis/AnalysisSection'
import { PulseChart } from '../components/charts/PulseChart'
import { RadarChart } from '../components/charts/RadarChart'
import { FrontlineChart } from '../components/charts/FrontlineChart'
import { HeatCanvas } from '../components/charts/HeatCanvas'
import { BattleMap } from '../components/charts/BattleMap'
import { EmptyState, ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

const JUMP_ITEMS = [
  { id: 'match-verdict', label: '结论' },
  { id: 'match-totals', label: '总量' },
  { id: 'match-phases', label: '阶段' },
  { id: 'match-pulse', label: '脉搏' },
  { id: 'match-nodes', label: '节点' },
  { id: 'match-profiles', label: '十人' },
  { id: 'match-cohesion', label: '联动' },
  { id: 'match-battle', label: '战斗' },
  { id: 'match-front', label: '阵线' },
  { id: 'match-heat', label: '热区' },
  { id: 'match-depth', label: '纵深' },
  { id: 'match-bp', label: 'BP' }
]

const clock = (seconds?: number | null) => (isNum(seconds) ? fmtDuration(seconds) : '—')

export function MatchPage() {
  const { baseUrl } = useConnection()
  const { settings } = useSettings()
  const { key = '' } = useParams()
  const navigate = useNavigate()
  const { teamName } = useAppMeta()
  const query = useMatch(baseUrl, key)
  const replayQuery = useReplay(baseUrl, key)
  const positionsQuery = usePositions(baseUrl, key)

  const [panelMode, setPanelMode] = useState<'duel' | 'team'>('duel')
  const [depthMode, setDepthMode] = useState<'deep' | 'half'>('deep')
  const [heatLane, setHeatLane] = useState<Lane>(LANES[0])
  const [heatTime, setHeatTime] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [selectedHero, setSelectedHero] = useState('')
  const [hoverDeath, setHoverDeath] = useState<number | null>(null)

  useEffect(() => {
    setHeatTime(null)
    setPlaying(false)
    setSelectedHero('')
    setHoverDeath(null)
    setPanelMode('duel')
    setDepthMode('deep')
    setHeatLane(LANES[0])
  }, [key])

  const derived = useMemo(() => {
    const match = query.data
    if (!match) return null
    const ownCamp = ownCampOf(match.ownCamp)
    const enemyCamp = foeCampOf(ownCamp)
    const players = [...(match.players || [])].sort((a, b) => {
      const ownA = a.camp === ownCamp ? 0 : 1
      const ownB = b.camp === ownCamp ? 0 : 1
      return ownA - ownB || a.slot - b.slot
    })
    const duration = match.duration || 0
    const stored = match.process?.timeline || []
    // 工作台旧数据可能只有官方回放金币；单局接口已返回 gold.points 时直接兜底。
    const timeline = stored.length ? stored : (replayQuery.data?.gold?.points || []).map((point) => ({
      gameTime: point.t, blueGold: point.blue, redGold: point.red
    }))
    const series = buildSeries(timeline, ownCamp, duration)
    const finalDiff = series.length ? series[series.length - 1].diff : null
    const eventList = replayQuery.data?.events || []
    const positions = positionsQuery.data
    const invasion = positions && players.length ? invasionStats(positions, players, duration) : null
    const invasionByCamp = invadeSummary(invasion, eventList, replayQuery.data?.kills)
    const prox: Map<Camp, ProximityStat> = positions && players.length ? proximity(positions, players) : new Map()
    const heat = positions ? prepareHeat(positions, players, duration) : null
    const battle = buildBattle({
      positions,
      players,
      ownCamp,
      duration,
      series: series.map((point) => [point.t, point.diff] as [number, number]),
      replay: replayQuery.data
    })
    const front = frontline(positions, players, ownCamp, duration)
    const phases = phaseRows(timeline, eventList, positions, duration, ownCamp)
    const metrics = buildMetrics(invasion)
    const pairs = duelPairs(players, ownCamp)
    const teamAgg = (camp: Camp) => {
      const list = players.filter((player) => player.camp === camp)
      if (!list.length) return { gold: null, kills: null, damage: null, taken: null }
      const sum = (field: keyof MatchPlayer) =>
        list.reduce((total, player) => total + (isNum(player[field]) ? (player[field] as number) : 0), 0)
      return {
        gold: sum('gold'),
        kills: sum('kills'),
        damage: sum('damage'),
        taken: sum('taken')
      }
    }
    return {
      match,
      ownCamp,
      enemyCamp,
      players,
      duration,
      series,
      finalDiff,
      events: eventList,
      positions,
      invasion,
      invasionByCamp,
      prox,
      heat,
      battle,
      front,
      phases,
      metrics,
      pairs,
      totals: totalRows(teamAgg(ownCamp), teamAgg(enemyCamp)),
      nodes: keyNodes(series, eventList, match.result),
      turn: biggestTurn(series)
    }
  }, [query.data, replayQuery.data, positionsQuery.data])

  const depth = useMemo(() => {
    if (!derived?.positions) return []
    return duelDepth(
      derived.positions,
      derived.players,
      derived.ownCamp,
      derived.duration,
      depthMode === 'deep' ? DEEP : HALF
    )
  }, [derived, depthMode])

  const heat = derived?.heat || null
  const heatAt = heat ? clamp(heatTime ?? heat.duration, 0, heat.duration) : 0

  useEffect(() => {
    if (!playing || !heat) return
    if (heatAt >= heat.duration) {
      setPlaying(false)
      return
    }
    const timer = window.setTimeout(
      () => setHeatTime(Math.min(heat.duration, heatAt + heat.step * 3)),
      200
    )
    return () => window.clearTimeout(timer)
  }, [playing, heat, heatAt])

  const heatFrame = useMemo(() => {
    if (!heat) return null
    const from = Math.max(0, heatAt - HEAT_WINDOW)
    const i0 = Math.max(0, Math.ceil(from / heat.step))
    const i1 = Math.max(i0, Math.floor(heatAt / heat.step))
    return heatCounts(heat.list, i0, i1)
  }, [heat, heatAt])

  if (query.isLoading) return <SkeletonPage cards={3} />
  if (query.isError || !derived) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const {
    match,
    ownCamp,
    enemyCamp,
    players,
    duration,
    series,
    finalDiff,
    events,
    positions,
    invasion,
    invasionByCamp,
    prox,
    battle,
    front,
    phases,
    metrics,
    pairs,
    totals,
    nodes,
    turn
  } = derived

  const positionsMissing = positionsQuery.isLoading
    ? '正在读取营地的逐秒位置…'
    : '这一局没有逐秒位置数据（需要官方回放）。热区、阵线、对位纵深、中野辅集结需要营地位置。'
  const replayMissing = replayQuery.isLoading
    ? '正在读取官方回放事件…'
    : '这一局没有官方回放事件（需要营地回放）。团战、掉点与资源建筑标记不可用。'
  const ownScore = scoreText(match.scores, match.ownCamp).split(' : ')
  const warnings = Array.isArray(match.warnings) ? match.warnings : []
  const outcome = match.result === 'win' ? '收下这一局' : match.result === 'loss' ? '交出这一局' : '结束这一局'
  const score = scoreText(match.scores, match.ownCamp)
  const heroClaim = series.length >= 2 && turn
    ? `${clock(turn.t)} 一波 ${signed(turn.delta)} 后经济差${(finalDiff ?? 0) >= 0 ? '再没回落' : '始终没能翻正'}`
    : `本队 ${clock(duration)} 以 ${score} ${outcome}`
  const heroFact = series.length >= 2 && turn
    ? `本队 ${clock(duration)} 以 ${score} ${outcome}`
    : events.length
      ? `回放记录 ${events.length} 条事件`
      : '没有回放事件'
  const draft = match.draft as Draft | null
  const ownSideKey: 'left' | 'right' = ownCamp === 'blue' ? 'left' : 'right'
  const enemySideKey = ownSideKey === 'left' ? 'right' : 'left'
  const focusCamp = selectedHero
    ? (battle.playerCamps.get(selectedHero) as Camp | undefined) || ownCamp
    : ownCamp
  const heroOptions = players.filter((player) => player.hero)

  const openWebCompare = async () => {
    try {
      const result = await window.kpl.openWorkbenchPage({
        baseUrl,
        route: `#match/${encodeURIComponent(key)}`
      })
      if (!result.ok) pushToast(result.error || '网页版没有打开', 'error')
    } catch (error) {
      pushToast(error instanceof Error ? error.message : '网页版没有打开', 'error')
    }
  }

  return (
    <div className="page md-page">
      <PageHeader
        eyebrow="MATCH DEEP"
        title={<>对阵 {match.opponent || '未标注'}<em>{[match.date, match.session || match.mode, fmtDuration(match.duration)].filter(Boolean).join(' · ')}</em></>}
        actions={<>
          <button type="button" className="btn" onClick={() => navigate(-1)}><Icon name="back" />返回</button>
          <button type="button" className="btn" onClick={() => void openWebCompare()} title="在独立窗口打开 v3 网页版，便于并排比对"><Icon name="external" />网页版</button>
          <button type="button" className="btn" onClick={() => window.print()}><Icon name="printer" />打印</button>
          <Link className="btn" to="/matches">全部比赛</Link>
        </>}
      />

      <article className="ink-card match-hero" id="match-verdict">
        <div className="match-hero-head">
          <span className="ink-kicker">本局结论</span>
          <span className="match-hero-meta">{[match.date, match.session || match.mode, match.version].filter(Boolean).map((text) => <i key={text}>{text}</i>)}</span>
        </div>
        <div className="md-verdict">
          <h2>{heroClaim}</h2>
          <p>{heroFact}</p>
        </div>
        <div className="match-hero-score">
          <div className="match-hero-team">
            <small>本队 · {sideLabel(ownCamp)}</small>
            <b>{teamName}</b>
            <span>本队</span>
          </div>
          <div className="match-hero-middle">
            <strong>{ownScore[0] || '—'}<span>:</span>{ownScore[1] || '—'}</strong>
            <em className={resultTone(match.result) === 'loss' ? 'is-loss' : ''}>{resultLabel(match.result)}</em>
          </div>
          <div className="match-hero-team is-away">
            <small>对手 · {sideLabel(enemyCamp)}</small>
            <b>{match.opponent || '未标注'}</b>
            <span>对方战队</span>
          </div>
        </div>
        <div className="match-hero-foot">
          <span>终局经济差 <b>{signed(finalDiff)}</b> · 本队视角</span>
          <span>{fmtDuration(duration)} · {number(players.length)} 人记录 · {series.length ? `${series.length} 个经济采样点` : '无经济时间轴'}</span>
        </div>
      </article>

      <JumpNav items={JUMP_ITEMS} />

      <section className="md-totals-band" id="match-totals">
        <div className="md-totals-head">
          <span>总量 · {teamName} vs {match.opponent || '对手'}</span>
          <small>营地十人面板五人合计；金色为本队，青色为对手</small>
        </div>
        <div className="md-totals">
          {totals.map((row) => (
            <div className="md-total" key={row.label}>
              <span>{row.label}</span>
              <div className="md-total-pair">
                <b>{number(row.own)}</b><i>:</i><b className="is-foe">{number(row.foe)}</b>
              </div>
              <div className="md-total-bar"><i style={{ width: `${row.share.toFixed(1)}%` }} /></div>
            </div>
          ))}
        </div>
      </section>

      <AnalysisSection
        id="match-phases"
        title="阶段对比"
        note="经济差与阶段变化按营地采样；资源 / 建筑是回放事件计数；入侵是本队五人合计进入对侧半区的时间占比"
      >
        <div className="md-phase-table">
          <div className="md-phase-row is-head">
            <span>阶段</span><span>本队增长</span><span>对手增长</span><span>净差</span><span>资源</span><span>建筑</span><span>入侵</span>
          </div>
          {phases.map((row) => (
            <div className="md-phase-row" key={row.label}>
              <span className="md-phase-tag">{row.label}<small>{clock(row.start)}–{clock(row.end)}</small></span>
              <span className="md-phase-gain is-own"><b>{signed(row.ownGain)}</b><i><em style={{ width: `${(row.ownPct * 100).toFixed(1)}%` }} /></i></span>
              <span className="md-phase-gain is-foe"><b>{signed(row.foeGain)}</b><i><em style={{ width: `${(row.foePct * 100).toFixed(1)}%` }} /></i></span>
              <span className={`md-phase-net ${(row.net ?? 0) >= 0 ? 'is-own' : 'is-foe'}`}>{signed(row.net)}</span>
              <span className="md-phase-duo"><b>{number(row.res.own)}</b><i>:</i><b className="is-foe">{number(row.res.foe)}</b></span>
              <span className="md-phase-duo"><b>{number(row.struct.own)}</b><i>:</i><b className="is-foe">{number(row.struct.foe)}</b></span>
              <span className="md-phase-invade">{row.invade === null ? '—' : percent(row.invade)}</span>
            </div>
          ))}
        </div>
      </AnalysisSection>

      <AnalysisSection
        id="match-pulse"
        title="比赛脉搏"
        note={series.length
          ? `经济差与本队视角一致 · ${series.length} 个采样点；菱形＝资源、方块＝建筑，拖动或点按查看任意时刻`
          : '这一局没有经济采样时间轴；阶段表里的经济增长会显示为「—」'}
        action={series.length ? <div className="md-legend"><span className="is-own">本队领先</span><span className="is-foe">对手领先</span><span className="md-shape is-diamond">资源</span><span className="md-shape is-square">建筑</span></div> : undefined}
      >
        {series.length
          ? <PulseChart series={series} events={events} duration={duration} ownName={teamName} foeName={match.opponent || '对手'} />
          : <EmptyState title="没有可用的经济时间轴">这一局缺少营地经济采样，无法绘制比赛脉搏。阶段表里的经济增长也会显示为「—」。</EmptyState>}
        <ScopeNote>口径：营地面板经济采样（约 30 秒一点）与回放事件；金差为本队减对手，不做跨局推断。</ScopeNote>
      </AnalysisSection>

      <AnalysisSection
        id="match-nodes"
        title="关键节点"
        note="按时间排列，每个数字都能回到具体分钟；波动取绝对值最大的几次"
      >
        {nodes.length ? (
          <div className="md-node-table">
            <div className="md-node-row is-head"><span>时间</span><span>关键节点</span><span>金差变化</span><span>当时金差</span><span>方向 / 来源</span></div>
            {nodes.map((node, index) => (
              <div className="md-node-row" key={`${node.t}-${index}`}>
                <span className="md-node-time">{clock(node.t)}</span>
                <b>{node.event}</b>
                <span className="md-node-num">{node.delta === null ? '—' : signed(node.delta)}</span>
                <span className="md-node-num">{signed(node.value)}</span>
                <span className={`md-node-dir ${node.dir === '利于本队' ? 'is-own' : node.dir === '利于对手' ? 'is-foe' : 'is-event'}`}>{node.dir}</span>
              </div>
            ))}
          </div>
        ) : <EmptyState title="没有可定位的关键节点">这一局既没有经济采样波动，也没有回放事件。</EmptyState>}
      </AnalysisSection>

      <AnalysisSection
        id="match-profiles"
        title="十人面板"
        note="对位比较按同分路两人归一，条形为本队占两人的比重；同队比较看队内份额。有位置数据时多一列「入侵」＝在对方半区的停留占比"
        action={<div className="segmented">
          <button type="button" className={panelMode === 'duel' ? 'is-active' : ''} onClick={() => setPanelMode('duel')}>对位比较</button>
          <button type="button" className={panelMode === 'team' ? 'is-active' : ''} onClick={() => setPanelMode('team')}>同队比较</button>
        </div>}
      >
        {!players.length
          ? <EmptyState title="没有十人面板数据">这一局还没有营地十人结算。</EmptyState>
          : panelMode === 'duel' ? (
            <div className="md-duels">
              {pairs.map((pair) => (
                <article className="md-duel" key={pair.lane}>
                  <div className="md-duel-head">
                    <span className="md-duel-lane">{pair.lane}</span>
                    <PlayerIdentity player={pair.own} side="own" />
                    <PlayerIdentity player={pair.foe} side="foe" />
                  </div>
                  <div className="md-duel-body">
                    <RadarChart metrics={metrics} own={pair.own} foe={pair.foe} ownLabel={teamName} foeLabel={match.opponent || '对手'} />
                    <div className="md-duel-metrics">
                      {metrics.map((metric) => {
                        const ownValue = metric.get(pair.own)
                        const foeValue = metric.get(pair.foe)
                        const sum = (ownValue || 0) + (foeValue || 0)
                        const share = sum > 0 ? (ownValue || 0) / sum * 100 : 50
                        const lead = (ownValue || 0) > (foeValue || 0) ? 'own' : (ownValue || 0) < (foeValue || 0) ? 'foe' : 'tie'
                        return (
                          <div className="md-duel-metric" data-lead={lead} key={metric.key}>
                            <span className="md-duel-label">{metric.label}</span>
                            <b className="md-duel-num is-own">{isNum(ownValue) ? (metric.rate ? percent(ownValue) : number(ownValue)) : '—'}</b>
                            <span className="md-duel-track"><i style={{ width: `${share.toFixed(1)}%` }} /></span>
                            <b className="md-duel-num is-foe">{isNum(foeValue) ? (metric.rate ? percent(foeValue) : number(foeValue)) : '—'}</b>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="md-teams">
              <TeamShareTable camp={ownCamp} label={`本队 · ${sideLabel(ownCamp)}`} side="own" players={players} metrics={metrics} invasion={invasion} teamName={teamName} />
              <TeamShareTable camp={enemyCamp} label={`对手 · ${sideLabel(enemyCamp)}`} side="foe" players={players} metrics={metrics} invasion={invasion} teamName={match.opponent || '对手'} />
            </div>
          )}
        <ScopeNote>{invasion
          ? '对位看同分路两人的形状差；同队看资源分配。入侵 = 进入对侧半区的时间占比，悬停可看次数与首次时间。'
          : '对位看同分路两人的形状差；同队看资源在本队内部的分配（本局没有位置数据，入侵列缺省）。'}</ScopeNote>
      </AnalysisSection>

      <AnalysisSection
        id="match-cohesion"
        title="中野辅与入侵"
        note="集结＝中/野/辅三人两两距离 ≤ 22.5（对角线 15%）且持续 ≥ 5 秒；入侵结果按团战账本的击杀与官方事件里的资源/建筑归因，不插值经济"
      >
        {!positions ? <EmptyState title="缺少逐秒位置">{positionsMissing}</EmptyState> : (
          <div className="md-coh-grid">
            {([ownCamp, enemyCamp] as Camp[]).map((camp) => {
              const item = prox.get(camp)
              const invade = invasionByCamp.get(camp)
              const title = `${camp === ownCamp ? '本队' : '对手'} · ${sideLabel(camp)}`
              if (!item) {
                return (
                  <article className={`md-coh is-${camp === ownCamp ? 'own' : 'foe'}`} key={camp}>
                    <header><b>{title}</b><span>中野辅</span></header>
                    <p className="md-coh-empty">缺少中 / 野 / 辅位置数据</p>
                  </article>
                )
              }
              return (
                <article className={`md-coh is-${camp === ownCamp ? 'own' : 'foe'}`} key={camp}>
                  <header><b>{title}</b><span>中野辅集结</span></header>
                  <div className="md-coh-nums">
                    <span><small>集结率</small><b>{percent(item.rate)}</b></span>
                    <span><small>集结次数</small><b>{number(item.count)}</b></span>
                    <span><small>最长集结</small><b>{item.longest ? `${number(item.longest)} 秒` : '—'}</b></span>
                    <span><small>平均间距</small><b>{isNum(item.gap) ? number(item.gap, 1) : '—'}</b></span>
                  </div>
                  <p className="md-coh-invade">
                    入侵 {number(invade?.episodes ?? 0)} 次 · 期间击杀 {number(invade?.kills ?? 0)} / 阵亡 {number(invade?.lost ?? 0)} · 资源·建筑 {number(invade?.objects ?? 0)}
                  </p>
                </article>
              )
            })}
          </div>
        )}
      </AnalysisSection>

      <AnalysisSection
        id="match-battle"
        title="团战与掉点"
        note="团战点大小＝参战人数，颜色＝本队（金）/ 对手（青）；掉点损失＝死前 120 秒金差走势外推到复活时刻的差额，已扣掉自然涨跌"
        action={battle.rows.length || battle.hasFightData ? (
          <select className="md-hero-pick" value={selectedHero} onChange={(event) => setSelectedHero(event.target.value)} aria-label="只看某个选手">
            <option value="">全部选手</option>
            <optgroup label="本队">
              {heroOptions.filter((player) => player.camp === ownCamp).map((player) => (
                <option value={player.hero} key={`own-${player.slot}`}>{player.label || player.hero} · {player.hero}</option>
              ))}
            </optgroup>
            <optgroup label="对手">
              {heroOptions.filter((player) => player.camp === enemyCamp).map((player) => (
                <option value={player.hero} key={`foe-${player.slot}`}>{player.label || player.hero} · {player.hero}</option>
              ))}
            </optgroup>
          </select>
        ) : undefined}
      >
        {!battle.rows.length && !battle.hasFightData ? (
          <EmptyState title="这局没有团战或掉点数据">{replayMissing}</EmptyState>
        ) : (
          <div className="md-battle">
            <div className="md-battle-map">
              <BattleMap
                marks={battle.marks}
                rows={battle.rows}
                ownCamp={ownCamp}
                selectedHero={selectedHero || null}
                selectedDeath={hoverDeath}
                onPickDeath={setHoverDeath}
              />
              <p className="md-battle-legend">
                <span className="is-own"><i className="is-fight" />本队团战</span>
                <span className="is-foe"><i className="is-fight" />对手团战</span>
                <span><i className="is-death" />阵亡</span>
              </p>
              {hoverDeath !== null && battle.rows[hoverDeath] ? (
                <DeathDetail row={battle.rows[hoverDeath]} />
              ) : null}
            </div>
            <div className="md-battle-block">
              <h4>团战贡献 <small>伤害占该队该团战</small></h4>
              {battle.hasFightData ? (
                <div className="md-contrib" style={{ gridTemplateColumns: `92px repeat(5, minmax(0, 1fr))` }}>
                  <span className="is-head">选手</span><span className="is-head">参战</span><span className="is-head">伤害</span><span className="is-head">承伤</span><span className="is-head">控制/秒</span><span className="is-head">均占比</span>
                  {battle.contributions[focusCamp].map((row) => (
                    <div className={`md-contrib-row${selectedHero && row.player.hero !== selectedHero ? ' is-dim' : ''}`} key={row.player.slot}
                      style={{ display: 'contents' }}>
                      <span className="md-contrib-name" title={row.player.label}>{row.player.hero || row.player.label}</span>
                      <span>{number(row.joined)}</span>
                      <span>{number(row.hurt)}</span>
                      <span>{number(row.taken)}</span>
                      <span>{number(row.ctrl)}</span>
                      <span className="md-contrib-share" style={isNum(row.share) ? { background: `color-mix(in srgb, var(--md-own) ${Math.min(34, (row.share / 45) * 34).toFixed(1)}%, transparent)` } : undefined}>
                        {isNum(row.share) ? percent(row.share) : '—'}
                      </span>
                    </div>
                  ))}
                </div>
              ) : <p className="md-board-empty">这局回放没有团战账本。</p>}
            </div>
            <div className="md-battle-block">
              <h4>掉点 <small>负数为亏 · 悬停看细节</small></h4>
              {battle.rows.length ? (
                <div className="md-drop-list">
                  {battle.rows.map((row, index) => {
                    if (selectedHero && row.death.hero !== selectedHero) return null
                    if (!selectedHero && index >= 8) return null
                    const loss = isNum(row.loss) ? -(row.loss as number) : null
                    return (
                      <button
                        type="button"
                        className={`md-drop${hoverDeath === index ? ' is-on' : ''}`}
                        key={`${row.death.t}-${index}`}
                        onPointerEnter={() => setHoverDeath(index)}
                        onFocus={() => setHoverDeath(index)}
                        onClick={() => setHoverDeath(index)}
                      >
                        <span className="md-drop-time">{clock(row.death.t)}</span>
                        <span className="md-drop-hero">{row.death.hero || '—'}</span>
                        <span className={`md-drop-loss ${isNum(loss) && loss < 0 ? 'is-down' : 'is-up'}`}>
                          {isNum(loss) ? signed(loss) : '—'}
                        </span>
                      </button>
                    )
                  })}
                  {selectedHero && !battle.rows.some((row) => row.death.hero === selectedHero)
                    ? <p className="md-board-empty">该选手这局没有掉点。</p>
                    : null}
                </div>
              ) : <p className="md-board-empty">这局没有死亡坐标。</p>}
            </div>
          </div>
        )}
      </AnalysisSection>

      <AnalysisSection
        id="match-front"
        title="阵线"
        note="五人平均推进进度：0 是己方基地、100% 是对方基地；线越过中线说明压过去了。竖带是前中后三期分界"
      >
        {front ? (
          <div className="md-front">
            <FrontlineChart data={front} />
            <div className="md-front-foot">
              <div className="md-front-legend"><span className="is-own"><i />本队</span><span className="is-foe"><i />对手</span></div>
              <div className="md-front-stats">
                <span><small>本队平均阵线</small><b>{isNum(front.avg) ? `${Math.round((front.avg as number) * 100)}%` : '—'}</b></span>
                <span><small>压过中线的时间</small><b>{isNum(front.ahead) ? `${Math.round(front.ahead as number)}%` : '—'}</b></span>
                <span><small>口径</small><b>五人平均推进 · 3 点平滑</b></span>
              </div>
            </div>
          </div>
        ) : <EmptyState title="缺少逐秒位置">{positionsMissing}</EmptyState>}
      </AnalysisSection>

      <AnalysisSection
        id="match-heat"
        title="对位热区"
        note="选一路，看这一路两个人在 90 秒窗口里怎么移动；可拖动时间轴或点播放。金为本队、青为对手"
      >
        {!heat ? <EmptyState title="缺少逐秒位置">{positionsMissing}</EmptyState> : (
          <div className="md-heat">
            <div className="md-heat-controls">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  if (playing) {
                    setPlaying(false)
                    return
                  }
                  if (heatAt >= heat.duration - heat.step) setHeatTime(0)
                  setPlaying(true)
                }}
              >
                <Icon name={playing ? 'clock' : 'play'} />{playing ? '暂停' : '播放'}
              </button>
              <input
                type="range"
                min="0"
                max={Math.round(heat.duration)}
                step={heat.step}
                value={Math.round(heatAt)}
                onChange={(event) => {
                  setPlaying(false)
                  setHeatTime(Number(event.target.value))
                }}
                aria-label="热区时间轴"
              />
              <span className="md-heat-clock">{clock(Math.max(0, heatAt - HEAT_WINDOW))} – {clock(heatAt)}</span>
              <label className="md-heat-lane-pick">
                <span>分路</span>
                <select value={heatLane} onChange={(event) => setHeatLane(event.target.value as Lane)} aria-label="选择分路">
                  {LANES.map((lane) => <option value={lane} key={lane}>{lane}</option>)}
                </select>
              </label>
            </div>
            <div className="md-heat-lanes">
              {[ownCamp, enemyCamp].map((camp) => {
                const entry = heat.list.find((player) => player.camp === camp && laneOf(player.info) === heatLane)
                if (!entry) {
                  return <div className="md-heat-side is-empty" key={camp}>这一路没有{camp === ownCamp ? '本队' : '对手'}位置数据</div>
                }
                const data = heatFrame?.out.get(playerKey(entry.camp, entry.slot))
                return (
                  <div className={`md-heat-side is-${camp === ownCamp ? 'own' : 'foe'}`} key={camp}>
                    <div className="md-heat-head">
                      <i className={`is-${camp === ownCamp ? 'own' : 'foe'}`} />
                      <b>{entry.info.label || entry.info.hero || '—'}</b>
                      <span>{entry.info.hero || ''}</span>
                    </div>
                    <HeatCanvas
                      counts={data?.counts || null}
                      max={heatFrame?.max || 1}
                      side={camp === ownCamp ? 'own' : 'foe'}
                      label={entry.info.label || entry.info.hero || ''}
                      theme={settings.theme}
                    />
                    <div className="md-heat-meta">
                      <span>
                        <b>{percent(data && data.total ? data.enemy / data.total * 100 : 0)}</b>
                        <small>在对侧半区</small>
                      </span>
                      <span>
                        <b>{number(data?.total ?? 0)}</b>
                        <small>窗口内有效样本</small>
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
            <ScopeNote>窗口 {HEAT_WINDOW} 秒随指针滚动；静止 ≥12 秒的样本已剔除。同一路的两个人并排，金为本队、青为对手。</ScopeNote>
          </div>
        )}
      </AnalysisSection>

      <AnalysisSection
        id="match-depth"
        title="对位纵深"
        note="同一张表两种口径：深区＝推进进度 > 66%，半区＝> 50%（即入侵）；方块数表示停留时长，每格约 10 秒，最多 10 格"
        action={positions ? <div className="segmented">
          <button type="button" className={depthMode === 'deep' ? 'is-active' : ''} onClick={() => setDepthMode('deep')}>深区 &gt;66%</button>
          <button type="button" className={depthMode === 'half' ? 'is-active' : ''} onClick={() => setDepthMode('half')}>半区 &gt;50%（入侵）</button>
        </div> : undefined}
      >
        {!positions ? <EmptyState title="缺少逐秒位置">{positionsMissing}</EmptyState> : (
          <div className="md-depth">
            <div className="md-depth-head">
              <span />
              <span className="is-own">{depthMode === 'deep' ? '本队 · 推进到对侧深区' : '本队 · 进入对侧半区'}</span>
              <span className="is-foe">{depthMode === 'deep' ? '对手 · 推进到本队深区' : '对手 · 进入本队半区'}</span>
            </div>
            <div className="md-depth-phases">
              <span />
              <span className="is-own"><i>前期</i><i>中期</i><i>后期</i></span>
              <span className="is-foe"><i>前期</i><i>中期</i><i>后期</i></span>
            </div>
            {depth.map((row) => (
              <div className="md-depth-row" key={row.lane}>
                <span className="md-depth-lane">{row.lane}</span>
                <div className="md-depth-side is-own">
                  {row.own ? row.own.seconds.map((seconds, index) => <DepthCell seconds={seconds} side="own" key={index} />) : <span className="md-depth-cell is-empty">—</span>}
                </div>
                <div className="md-depth-side is-foe">
                  {row.foe ? row.foe.seconds.map((seconds, index) => <DepthCell seconds={seconds} side="foe" key={index} />) : <span className="md-depth-cell is-empty">—</span>}
                </div>
              </div>
            ))}
            <ScopeNote>静止 ≥12 秒的样本（阵亡停留等）已剔除，与全景页同口径。</ScopeNote>
          </div>
        )}
      </AnalysisSection>

      <AnalysisSection
        id="match-bp"
        title="本局 BP"
        note={`营地终局名单 · 禁用固定 5 位，空位标为空 BAN；选用按 pickHeros 原样展示${draft?.pickOrderKnown ? '（已人工校对选用顺序）' : ''}`}
      >
        {draft ? (
          <div className="md-bp">
            <div className="md-bp-head"><span>阵容</span><span>选用 · 按序号</span><span>禁用 · 固定 5 位</span></div>
            <BpRow title={`本队 · ${sideLabel(ownCamp)}`} side="own" picks={draft.picks?.[ownSideKey]} bans={draft.bans?.[ownSideKey]} />
            <BpRow title={`对手 · ${sideLabel(enemyCamp)}`} side="foe" picks={draft.picks?.[enemySideKey]} bans={draft.bans?.[enemySideKey]} />
          </div>
        ) : <EmptyState title="暂无禁选记录">这一局没有营地禁选名单；可在工作台补录。</EmptyState>}
      </AnalysisSection>

      {warnings.length ? (
        <div className="match-warning"><Icon name="alert" size={15} /><span>{warnings.join(' · ')}</span></div>
      ) : null}

      <div className="overview-foot">
        <span>SOURCE · 营地十人面板 / 官方回放 / 营地逐秒位置</span>
        <span>{series.length ? '经济时间轴可追溯' : '缺少经济时间轴'} · {positions ? '位置样本已剔除静止段' : '无位置样本'} · {events.length ? `${events.length} 条回放事件` : '无回放事件'}</span>
      </div>
    </div>
  )
}

function PlayerIdentity({ player, side }: { player: MatchPlayer | null; side: 'own' | 'foe' }) {
  if (!player) return <span className={`md-vs-id is-${side} is-empty`}>未匹配</span>
  return (
    <span className={`md-vs-id is-${side}`}>
      <Portrait name={player.hero} size="sm" />
      <span><b>{player.label || player.hero || '—'}</b><small>{player.hero || '—'}</small></span>
    </span>
  )
}

function TeamShareTable({
  camp,
  label,
  side,
  players,
  metrics,
  invasion,
  teamName
}: {
  camp: Camp
  label: string
  side: 'own' | 'foe'
  players: MatchPlayer[]
  metrics: ReturnType<typeof buildMetrics>
  invasion: ReturnType<typeof invasionStats> | null
  teamName: string
}) {
  const { team, rows, scale } = teamMetricRows(players, camp, metrics)
  if (!team.length) return null
  const rates = invasion
    ? team.map((player) => invasionOf(invasion, player)?.rate).filter((value): value is number => isNum(value))
    : []
  const episodes = invasion
    ? team.reduce((sum, player) => sum + (invasionOf(invasion, player)?.episodes || 0), 0)
    : 0
  const firsts = invasion
    ? team.map((player) => invasionOf(invasion, player)?.first).filter((value): value is number => isNum(value))
    : []
  let note = invasion
    ? '经济 / 输出 / 承伤 / 发育为队内份额，参团、入侵为比率'
    : '经济 / 输出 / 承伤 / 发育为队内份额，参团为参团率'
  if (rates.length) {
    note += ` · 全队入侵 ${percent(rates.reduce((a, b) => a + b, 0) / rates.length)}`
    if (episodes) note += `，共 ${number(episodes)} 次`
    if (firsts.length) note += `，首次 ${clock(Math.min(...firsts))}`
  }
  return (
    <div className={`md-team is-${side}`}>
      <div className="md-team-top"><b>{label}</b><span>{team.length} 人</span></div>
      <div className="md-team-grid" style={{ gridTemplateColumns: `92px repeat(${metrics.length}, minmax(0, 1fr))` }}>
        <span className="is-head">选手</span>
        {metrics.map((metric) => <span className="is-head" key={metric.key}>{metric.label}</span>)}
        {rows.map((row) => (
          <div className="md-team-row" key={row.player.slot} style={{ display: 'contents' }}>
            <span className="md-team-who"><b>{row.player.label || row.player.hero || '—'}</b><small>{row.player.hero || '—'}</small></span>
            {row.values.map((value, index) => {
              const stat = invasionOf(invasion, row.player)
              const title = metrics[index].key === 'invade' && stat
                ? `前 ${percent(stat.phases[0])} / 中 ${percent(stat.phases[1])} / 后 ${percent(stat.phases[2])} · ${stat.episodes} 次 · 首次 ${clock(stat.first)} · 最长 ${number(stat.longest)} 秒 · 纵深峰值 ${percent(stat.peak)}`
                : undefined
              return (
                <span className={`md-team-cell${value === null ? ' is-empty' : ''}`} key={metrics[index].key} title={title}>
                  {value === null ? '—' : <>
                    <i><em style={{ width: `${clamp(value / scale[index] * 100, 0, 100).toFixed(1)}%` }} /></i>
                    <b>{percent(value)}</b>
                  </>}
                </span>
              )
            })}
          </div>
        ))}
      </div>
      <p className="md-team-note">{note.replace('全队入侵', `${teamName} 全队入侵`)}</p>
    </div>
  )
}

function DeathDetail({ row }: { row: DeathRow }) {
  const loss = isNum(row.loss) ? -(row.loss as number) : null
  const tone = !isNum(loss) ? '' : loss < 0 ? 'is-foe' : 'is-own'
  return (
    <div className="md-death-card">
      <div className="md-death-head">
        <b>{clock(row.death.t)}</b>
        <span>{row.death.hero || '—'} 阵亡</span>
        {row.shared ? <i className="md-death-tag" title="与队友同时掉点，队级汇总会重复计入">†</i> : null}
      </div>
      <div className={`md-death-loss ${tone}`}>{isNum(loss) ? signed(loss) : '—'}<small>修正损失</small></div>
      <div className="md-death-rows">
        <span>窗口 <b>{Math.round(row.t1 - row.death.t)} 秒</b></span>
        <span>金差变化 <b>{signed(row.raw)}</b></span>
      </div>
      <p>死前 120 秒金差走势外推到复活时刻的差额{row.confident ? '' : ' · 低置信'}</p>
    </div>
  )
}

function DepthCell({ seconds, side }: { seconds: number; side: 'own' | 'foe' }) {
  const blocks = clamp(Math.round(seconds / 10), 0, 10)
  return (
    <span className={`md-depth-cell is-${side}`}>
      <b>{number(seconds)}<small>秒</small></b>
      <span className="md-vox">
        {blocks ? Array.from({ length: blocks }).map((_, index) => <i key={index} />) : <i className="is-zero" />}
      </span>
    </span>
  )
}

function BpRow({
  title,
  side,
  picks,
  bans
}: {
  title: string
  side: 'own' | 'foe'
  picks?: HeroPick[]
  bans?: HeroPick[]
}) {
  const pickList = picks || []
  const banList = bans || []
  return (
    <div className={`md-bp-row is-${side}`}>
      <b>{title}</b>
      <div className="md-bp-slots">
        {Array.from({ length: 5 }).map((_, index) => {
          const hero = pickList[index]
          return hero ? (
            <span className="md-bp-slot" key={`pick-${index}`}>
              <em>{index + 1}</em>
              <Portrait name={hero.name} size="sm" />
              <span>{hero.name}</span>
            </span>
          ) : <span className="md-bp-slot is-empty" key={`pick-${index}`}><em>{index + 1}</em>空位</span>
        })}
      </div>
      <div className="md-bp-slots is-bans">
        {Array.from({ length: 5 }).map((_, index) => {
          const hero = banList[index]
          return hero ? (
            <span className="md-bp-slot is-ban" key={`ban-${index}`}>
              <Portrait name={hero.name} size="sm" />
              <span>{hero.name}</span>
            </span>
          ) : <span className="md-bp-slot is-empty" key={`ban-${index}`}>空 BAN</span>
        })}
      </div>
    </div>
  )
}
