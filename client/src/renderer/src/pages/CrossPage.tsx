import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useCrossVectors, useMatches, useTempo } from '../lib/hooks'
import { duration as fmtDuration, number, percent, signed } from '../lib/format'
import { matchPath } from '../lib/routes'
import { analyzeCohort } from '../lib/analysis/cross'
import { PLAYER_LANES } from '../lib/analysis/players'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { BarList } from '../components/charts/BarList'
import { HeatMatrix } from '../components/charts/HeatMatrix'
import { MiniLine } from '../components/analysis/BoardBits'
import { Sparkline } from '../components/charts/Sparkline'
import { StackedBars } from '../components/charts/StackedBars'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'
import type { CrossVector } from '../lib/types'

const EMPTY = { version: '', session: '', opponent: '', result: '' }

export function CrossPage() {
  const { baseUrl } = useConnection()
  const vectorsQuery = useCrossVectors(baseUrl)
  const tempoQuery = useTempo(baseUrl)
  const matchesQuery = useMatches(baseUrl)
  const [filters, setFilters] = useState({ ...EMPTY })
  const [scopeKeys, setScopeKeys] = useState<Set<string> | null>(null)
  const [focusKey, setFocusKey] = useState('')

  const vectors = vectorsQuery.data?.vectors || []
  const filtered = useMemo(() => vectors.filter((vector) => {
    if (filters.version && (vector.version || '') !== filters.version) return false
    if (filters.session && (vector.session || '') !== filters.session) return false
    if (filters.opponent && (vector.opponent || '') !== filters.opponent) return false
    if (filters.result && vector.result !== filters.result) return false
    return true
  }), [vectors, filters])
  const cohort = useMemo(() => analyzeCohort(filtered), [filtered])
  const matches = matchesQuery.data || []
  const matchByKey = useMemo(() => new Map(matches.map((match) => [match.key, match])), [matches])
  const tempoMatches = tempoQuery.data?.process.matches || []
  const tempoByKey = useMemo(() => new Map(tempoMatches.map((match) => [match.key, match])), [tempoMatches])
  const ordered = useMemo(() => [...filtered].sort((a, b) => String(b.order).localeCompare(String(a.order))), [filtered])
  const scoped = scopeKeys ? ordered.filter((vector) => scopeKeys.has(vector.key)) : ordered

  if (vectorsQuery.isLoading) return <SkeletonPage cards={3} />
  if (vectorsQuery.isError || !vectorsQuery.data) {
    return <div className="page"><ErrorState error={vectorsQuery.error} onRetry={() => void vectorsQuery.refetch()} /></div>
  }
  if (!vectors.length) {
    return (
      <div className="page board-page">
        <PageHeader eyebrow="CROSS MATCH" title="跨局分析" actions={<Link className="btn" to="/matches">对局档案</Link>} />
        <BoardEmpty title="还没有已确认的对局">先到对局档案完成一局归档，跨局对照会自动排开。</BoardEmpty>
      </div>
    )
  }

  const wins = filtered.filter((vector) => vector.result === 'win').length
  const decided = filtered.filter((vector) => vector.result === 'win' || vector.result === 'loss').length
  const values = (key: keyof CrossVector) => filtered.map((vector) => vector[key]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const median = (list: number[]) => {
    if (!list.length) return null
    const sorted = [...list].sort((a, b) => a - b)
    return sorted[Math.floor(sorted.length / 2)]
  }
  const at10Med = median(values('at10'))
  const finalMed = median(values('finalDiff'))
  const durations = values('duration')
  const avgDuration = durations.length ? durations.reduce((sum, value) => sum + value, 0) / durations.length : null
  const versions = [...new Set(vectors.map((vector) => vector.version).filter((value): value is string => Boolean(value)))].sort()
  const sessions = [...new Set(vectors.map((vector) => vector.session).filter((value): value is string => Boolean(value)))].sort()
  const opponents = [...new Set(vectors.map((vector) => vector.opponent).filter((value): value is string => Boolean(value)))].sort()
  const focus = ordered.find((vector) => vector.key === focusKey) || ordered[0]
  const focusTempo = focus ? tempoByKey.get(focus.key) : null
  const focusPoints = (focusTempo?.points || []).filter((point) => Array.isArray(point) && Number.isFinite(point[0]) && Number.isFinite(point[1])) as [number, number][]
  const scope = (keys: string[]) => setScopeKeys(new Set(keys))
  const patch = (value: Partial<typeof EMPTY>) => setFilters((current) => ({ ...current, ...value }))
  const activeFilter = Object.values(filters).some(Boolean)

  const exportCsv = () => {
    const header = ['对局', '日期', '对手', '训练组', '版本', '结果', '时长', '10分钟金差', '终局金差', '本队击杀', '对手击杀']
    const rows = scoped.map((vector) => [
      vector.key, vector.date, vector.opponent || '', vector.session || '', vector.version || '',
      vector.result || '', vector.duration || '', vector.at10 ?? '', vector.finalDiff ?? '',
      vector.killsOwn ?? '', vector.killsFoe ?? ''
    ])
    const text = [header, ...rows].map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\r\n')
    const blob = new Blob([`\ufeff${text}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '跨局分析.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="CROSS MATCH"
        title="跨局分析"
        subtitle="全量向量算总体，逐局明细做对照。结论不依赖分页，也不从某一局讲故事。"
        actions={<>
          <button type="button" className="btn" onClick={exportCsv}><Icon name="copy" />导出 CSV</button>
          <Link className="btn" to="/matches">对局档案</Link>
        </>}
      />

      <StatGrid items={[
        { label: '当前范围', value: number(filtered.length), note: `全量 ${vectors.length} 局` },
        { label: '胜 / 负', value: `${wins} : ${decided - wins}`, note: `胜率 ${percent(decided ? wins / decided * 100 : null)}`, tone: 'own' },
        { label: '10 分钟金差中位', value: signed(at10Med), note: '本队减对手', tone: (at10Med || 0) >= 0 ? 'own' : 'foe' },
        { label: '终局金差中位', value: signed(finalMed), note: '本队减对手', tone: (finalMed || 0) >= 0 ? 'own' : 'foe' },
        { label: '平均时长', value: fmtDuration(avgDuration), note: versions.length || sessions.length ? `${versions.length} 个版本 / ${sessions.length} 个训练组` : '版本 / 训练组未记录' },
        { label: '证据充分卡', value: number(cohort.audit?.strong ?? 0), note: `10 张结论卡 · 前后半一致 ${cohort.audit?.held ?? 0}/${cohort.audit?.checked ?? 0}` }
      ]} />

      <div className="board-toolbar">
        {versions.length ? <select value={filters.version} onChange={(event) => patch({ version: event.target.value })} aria-label="版本">
          <option value="">全部版本</option>
          {versions.map((item) => <option value={item} key={item}>{item}</option>)}
        </select> : null}
        {sessions.length ? <select value={filters.session} onChange={(event) => patch({ session: event.target.value })} aria-label="训练组">
          <option value="">全部训练组</option>
          {sessions.map((item) => <option value={item} key={item}>{item}</option>)}
        </select> : null}
        <select value={filters.opponent} onChange={(event) => patch({ opponent: event.target.value })} aria-label="对手">
          <option value="">全部对手</option>
          {opponents.map((item) => <option value={item} key={item}>{item}</option>)}
        </select>
        <select value={filters.result} onChange={(event) => patch({ result: event.target.value })} aria-label="结果">
          <option value="">全部结果</option>
          <option value="win">胜</option>
          <option value="loss">负</option>
        </select>
        {activeFilter ? <button type="button" className="btn btn-sm" onClick={() => setFilters({ ...EMPTY })}>清除筛选</button> : null}
        <span className="board-muted">结论按当前范围重算</span>
      </div>

      {!filtered.length ? <div className="board-banner">当前筛选没有对局；清除筛选或换一个版本 / 训练组 / 对手。</div> : null}

      <section className="cross-cards">
        {(cohort.cards || []).map((card: any) => (
          <CrossCard
            key={card.id}
            card={card}
            onScope={() => scope(card.actKeys || [])}
          />
        ))}
      </section>

      <AnalysisSection title="分路对位" note="同分路本队减对手，按局时长折算成每分钟；方块/条长表示差距大小。">
        <LaneBoard vectors={filtered} />
      </AnalysisSection>

      <AnalysisSection
        title={scopeKeys ? `逐局对照 · 已圈定 ${scoped.length} 局` : '逐局对照'}
        note="金差走势＝本队减对手；10 分钟与终局读数来自营地采样。点一行设为参照。"
        action={scopeKeys ? <button type="button" className="btn btn-sm" onClick={() => setScopeKeys(null)}>清除圈定</button> : undefined}
      >
        <div className="cross-board">
          <div className="cross-board-list">
            {scoped.length ? scoped.map((vector) => {
              const tempo = tempoByKey.get(vector.key)
              const points = (tempo?.points || []).filter((point) => Array.isArray(point) && Number.isFinite(point[0]) && Number.isFinite(point[1])) as [number, number][]
              const match = matchByKey.get(vector.key)
              return (
                <button
                  type="button"
                  key={vector.key}
                  className={`cross-row${focus?.key === vector.key ? ' is-focus' : ''}`}
                  onClick={() => setFocusKey(vector.key)}
                >
                  <span className="cross-row-main">
                    <b>{match?.opponent || vector.opponent || '对手未标注'}</b>
                    <small>{vector.date || '—'} · {match?.mode || vector.session || '对局'} · {vector.version || '版本未记录'}</small>
                  </span>
                  <span className={`cross-row-result tone-${vector.result === 'win' ? 'own' : 'foe'}`}>
                    {vector.result === 'win' ? '胜' : vector.result === 'loss' ? '负' : '—'}
                  </span>
                  <span className="cross-row-duration">{fmtDuration(vector.duration)}</span>
                  <span className="cross-row-spark"><Sparkline points={points} duration={vector.duration} markAt={600} /></span>
                  <span className="cross-row-metric"><small>10′</small><b>{signed(vector.at10)}</b></span>
                  <span className="cross-row-metric"><small>终局</small><b>{signed(vector.finalDiff)}</b></span>
                  <Link className="cross-row-link" to={matchPath(vector.key)} onClick={(event) => event.stopPropagation()}>复盘 →</Link>
                </button>
              )
            }) : <BoardEmpty title="当前范围没有对局">换一个筛选条件再试。</BoardEmpty>}
          </div>
          <aside className="cross-ref">
            <h3>本批参照</h3>
            <p>{focus ? `聚焦 ${focus.date || ''} ${focus.opponent || ''}` : '选择一局查看它在分布里的位置'}</p>
            <Distribution label="10 分钟金差" values={values('at10')} active={focus?.at10} />
            <Distribution label="终局金差" values={values('finalDiff')} active={focus?.finalDiff} />
            <Distribution label="时长（分）" values={values('duration').map((value) => value / 60)} active={focus ? focus.duration / 60 : null} />
            {focus && focusPoints.length ? (
              <div className="cross-ref-spark">
                <span>聚焦局金差走势</span>
                <Sparkline points={focusPoints} width={220} height={70} duration={focus.duration} markAt={600} />
              </div>
            ) : null}
          </aside>
        </div>
      </AnalysisSection>

      <div className="board-foot">口径：营地十人面板与官方回放事件；金差一律为本队减对手。当前库官方回放 {number(vectors.length)} 局向量中可读时间轴 {number(tempoMatches.length)} 局；缺时间轴的局只看终局读数。</div>
    </div>
  )
}

function EmText({ text }: { text: string }) {
  const parts = String(text || '').split(/<em>|<\/em>/)
  return <>{parts.map((part, index) => index % 2 ? <em key={index}>{part}</em> : <span key={index}>{part}</span>)}</>
}

function CrossCard({ card, onScope }: { card: any; onScope: () => void }) {
  const count = (card.actKeys || []).length
  const empty = crossEmpty(card.chart)
  return (
    <article className="cross-card" id={`cx-analysis-${card.id}`}>
      <div className="cross-card-top">
        <span>{card.id} / {card.group}</span>
        <span className={`cross-grade is-${card.grade?.level ?? 0}`}>{card.grade?.label}</span>
        {card.repro === true ? <span className="cross-repro is-ok">前后半可复现</span> : null}
        {card.repro === false ? <span className="cross-repro is-no">前后半未复现</span> : null}
      </div>
      <div className="cross-card-name">{card.name} · <span>{card.ask}</span></div>
      <h3>{crossEmpty(card.chart) || <EmText text={card.title} />}</h3>
      <p className="cross-card-plain">{empty ? '当前库缺少这类样本；先补齐对应数据，其他卡片仍按当前范围计算。' : card.plain}</p>
      <CardChart chart={card.chart} />
      <div className="cross-card-foot">
        <div><span>训练安排</span><p>{empty ? '先补齐对应采样，再看训练建议。' : card.train}</p></div>
        <button type="button" className="btn btn-sm" onClick={onScope} disabled={!count}>{card.review} · {count} 局</button>
      </div>
      <details className="cross-method">
        <summary>怎么算的</summary>
        <p>{card.method}</p>
      </details>
    </article>
  )
}


function crossEmpty(chart: any): string | null {
  if (!chart) return '暂无可视化数据'
  if (chart.type === 'bands' && chart.p50 === null) return '这批局缺少 10 分钟经济差样本，先看终局与分路'
  if (chart.type === 'segments') {
    const total = (chart.items || []).reduce((sum: number, item: any) => sum + (item.n || 0), 0)
    if (!chart.items?.length || total < 3) return '10 分钟样本不足 3 局，暂不判断训练效应'
  }
  if (chart.type === 'rolling' && (!chart.points?.length || chart.points.every((point: any) => point.v === null))) return '时间轴不足，暂时看不出水平变点'
  if (chart.type === 'matrix' && (!chart.cells?.length || chart.cells.flat().every((cell: any) => !cell.n))) return '没有足够的体系 × 条件交叉样本'
  if (chart.type === 'contrib' && (!chart.windows?.length || chart.windows.every((item: any) => item.value === null))) return '没有 5 分钟窗口样本，暂不归因'
  if (chart.type === 'trans' && (!chart.m?.length || chart.m.flat().every((value: number) => !value))) return '没有足够的领先/落后样本'
  if (chart.type === 'types' && !chart.items?.length) return '这批局没有明显成类的反常局'
  if (chart.type === 'systems' && !chart.items?.length) return '当前局数还不足以分型'
  return null
}

function CardChart({ chart }: { chart: any }) {
  if (!chart) return null
  if (chart.type === 'bands') {
    const { lo, p25, p50, p75, hi, strata } = chart
    const values = [lo, p25, p50, p75, hi].filter((value) => typeof value === 'number')
    if (!values.length) return <BoardEmpty title="暂无 10 分钟经济差样本" />
    const low = Math.min(...values), high = Math.max(...values)
    const span = high - low || 1
    const pos = (value: number) => `${Math.max(0, Math.min(100, (value - low) / span * 100)).toFixed(1)}%`
    return (
      <div className="cx-bands">
        <div className="cx-band-track">
          <i className="cx-band-outer" style={{ left: pos(lo ?? low), width: `${(Number(pos(hi ?? high).replace('%', '')) - Number(pos(lo ?? low).replace('%', '')))}%` }} />
          <i className="cx-band-inner" style={{ left: pos(p25 ?? low), width: `${(Number(pos(p75 ?? high).replace('%', '')) - Number(pos(p25 ?? low).replace('%', '')))}%` }} />
          <b className="cx-band-med" style={{ left: pos(p50 ?? low) }} />
        </div>
        <div className="cx-band-labels"><span>P10 {signed(lo)}</span><span>典型 {signed(p50)}</span><span>P90 {signed(hi)}</span></div>
        {strata?.length ? (
          <div className="cx-strata">
            {strata.map((stratum: any) => (
              <div key={stratum.label}><span>{stratum.label}</span><b>{signed(stratum.p50)}</b><small>{stratum.n} 局</small></div>
            ))}
          </div>
        ) : <p className="board-muted">分层不足 2 个，不拆版本/对手/训练组。</p>}
      </div>
    )
  }
  if (chart.type === 'stack') {
    return <StackedBars rows={[{ label: '波动来源', segments: (chart.parts || []).map((part: any) => ({ key: part.label, label: part.label, value: Math.round(part.share * 100), tone: 'own' })) }]} />
  }
  if (chart.type === 'range') {
    const items = chart.items || []
    const peak = Math.max(1, ...items.map((item: any) => Math.abs(item.p90 || 0) + Math.abs(item.p10 || 0)))
    return (
      <div className="cx-range">
        {items.map((item: any) => (
          <div className="cx-range-row" key={item.label}>
            <span>{item.label}</span>
            <i><em style={{ left: `${(Math.abs(item.p10 || 0) / peak * 50).toFixed(1)}%`, width: `${(Math.abs((item.p90 || 0) - (item.p10 || 0)) / peak * 100).toFixed(1)}%` }} /><b style={{ left: `${(Math.abs(item.p50 || 0) / peak * 50).toFixed(1)}%` }} /></i>
            <small>P10 {signed(item.p10)} · P50 {signed(item.p50)} · P90 {signed(item.p90)}</small>
          </div>
        ))}
      </div>
    )
  }
  if (chart.type === 'segments') {
    return <BarList items={(chart.items || []).map((item: any) => ({ label: `${item.label}${item.from ? ` · ${item.from}` : ''}`, value: item.value, note: `${item.n} 局` }))} digits={0} />
  }
  if (chart.type === 'rolling') {
    const points = (chart.points || []).map((point: any, index: number) => ({ x: index, y: point.v }))
    return <MiniLine values={points} width={520} height={150} label="水平走势" />
  }
  if (chart.type === 'systems') {
    return (
      <div className="cx-systems">
        {(chart.items || []).map((item: any) => (
          <div className="cx-system" key={item.name}>
            <div><b>{item.name}</b><span>{percent((item.pct || 0) * 100)} · {item.n} 局</span></div>
            <MiniLine values={(item.curve || []).map((value: number, index: number) => ({ x: index, y: value }))} width={260} height={70} />
            <small>下限 {signed(item.floor)} · 中位 {signed(item.final)}</small>
          </div>
        ))}
      </div>
    )
  }
  if (chart.type === 'matrix') {
    const rows = chart.rows || []
    const cols = chart.cols || []
    const values = (chart.cells || []).map((row: any[]) => row.map((cell) => cell.v))
    return <HeatMatrix rows={rows} cols={cols} values={values} unit=" 金" />
  }
  if (chart.type === 'contrib') {
    return (
      <div className="board-grid-2">
        <BarList items={(chart.windows || []).map((item: any) => ({ label: item.label, value: item.value, note: `${item.n} 局`, tone: (item.value || 0) >= 0 ? 'own' : 'foe' }))} digits={0} />
        <BarList items={(chart.lanes || []).map((item: any) => ({ label: item.label, value: Math.round((item.pct || 0) * 100), note: `${item.n} 局`, tone: 'accent' }))} digits={0} suffix="%" />
      </div>
    )
  }
  if (chart.type === 'trans') {
    const states = chart.states || []
    const matrix = chart.m || []
    return (
      <div className="cx-trans">
        <div className="cx-trans-row is-head"><span />{states.map((state: string) => <span key={state}>{state}</span>)}</div>
        {states.map((state: string, index: number) => (
          <div className="cx-trans-row" key={state}><span>{state}</span>{(matrix[index] || []).map((value: number, col: number) => <b key={col}>{value}</b>)}</div>
        ))}
      </div>
    )
  }
  if (chart.type === 'types') {
    return <BarList items={(chart.items || []).map((item: any) => ({ label: item.name, value: item.n, note: `${percent((item.pct || 0) * 100)} · ${item.trait || ''}` }))} digits={0} />
  }
  return null
}

function Distribution({ label, values, active }: { label: string; values: number[]; active?: number | null }) {
  if (!values.length) return null
  const low = Math.min(...values)
  const high = Math.max(...values)
  const span = high - low || 1
  const pos = (value: number) => `${Math.max(0, Math.min(100, (value - low) / span * 100)).toFixed(1)}%`
  return (
    <div className="cx-dist">
      <div className="cx-dist-head"><span>{label}</span><b>{active === null || active === undefined ? '—' : signed(active)}</b></div>
      <div className="cx-dist-track">
        {values.map((value, index) => <i key={index} style={{ left: pos(value) }} />)}
        {active !== null && active !== undefined ? <b style={{ left: pos(active) }} /> : null}
      </div>
      <div className="cx-dist-foot"><span>{signed(low)}</span><span>{signed(high)}</span></div>
    </div>
  )
}

function LaneBoard({ vectors }: { vectors: CrossVector[] }) {
  const metrics = [
    ['gold', '分均经济差'],
    ['damage', '分均输出差'],
    ['taken', '分均承伤差']
  ] as const
  const rows = PLAYER_LANES.map((lane) => ({
    lane,
    values: metrics.map(([key]) => {
      const list = vectors.map((vector) => vector.lanes?.[lane]?.[key]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
      return list.length ? list.reduce((sum, value) => sum + value, 0) / list.length : null
    })
  }))
  const peaks = metrics.map((_, index) => Math.max(1, ...rows.map((row) => Math.abs(row.values[index] || 0))))
  return (
    <div className="cx-lane-board">
      <div className="cx-lane-row is-head"><span>位置</span>{metrics.map(([, label]) => <span key={label}>{label}</span>)}</div>
      {rows.map((row) => (
        <div className="cx-lane-row" key={row.lane}>
          <span className="cx-lane-name">{row.lane}</span>
          {row.values.map((value, index) => (
            <span className={`cx-lane-cell ${value === null ? 'is-empty' : (value >= 0 ? 'is-own' : 'is-foe')}`} key={index}>
              <b>{signed(value)}</b>
              <i><em style={{ width: `${value === null ? 0 : Math.abs(value) / peaks[index] * 100}%` }} /></i>
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}
