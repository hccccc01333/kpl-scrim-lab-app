/**
 * 上帝模式 · 第十一批注册块（节奏 / 选手状态 / 固定搭档）
 */
import { useConnection } from '../../lib/app-context'
import { usePlayerBoard, useTempo } from '../../lib/hooks'
import { number, percent, signed } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 经济检查点：按分钟点聚合平均经济差。 */
function TempoGoldCheckpointsBlock() {
  const { baseUrl } = useConnection()
  const query = useTempo(baseUrl)
  const matches = query.data?.process?.matches || []
  const buckets = new Map<string, { sum: number; n: number }>()
  for (const match of matches) {
    for (const [key, value] of Object.entries(match.diffAt || {})) {
      if (typeof value !== 'number') continue
      const bucket = buckets.get(key) || { sum: 0, n: 0 }
      bucket.sum += value
      bucket.n += 1
      buckets.set(key, bucket)
    }
  }
  const rows = [...buckets.entries()]
    .map(([label, bucket]) => ({ label, avg: bucket.sum / bucket.n, n: bucket.n }))
    .sort((a, b) => Number(a.label) - Number(b.label))
  return (
    <AnalysisSection title="经济检查点" note="块库 · 按时间检查点聚合平均经济差（正数 = 本队领先）。">
      {query.isLoading ? <Loading label="正在读取节奏数据…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>分钟点</th><th>平均经济差</th><th>样本</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.label}>
                      <td>{Math.round(Number(row.label) / 60)} 分钟</td>
                      <td className="is-num">{signed(row.avg)}</td>
                      <td className="is-num">{row.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有可用经济时间轴" />}
    </AnalysisSection>
  )
}

/** 击杀节奏：场均每分钟击杀。 */
function TempoKillsBlock() {
  const { baseUrl } = useConnection()
  const query = useTempo(baseUrl)
  const matches = (query.data?.process?.matches || []).filter((match) => typeof match.killsPerMinute === 'number')
  const avg = matches.length ? matches.reduce((sum, match) => sum + (match.killsPerMinute as number), 0) / matches.length : null
  const sorted = [...matches].sort((a, b) => (b.killsPerMinute as number) - (a.killsPerMinute as number))
  const hottest = sorted[0]
  const coolest = sorted[sorted.length - 1]
  return (
    <AnalysisSection title="击杀节奏" note="块库 · 场均每分钟击杀；只统计有节奏数据的局。">
      {query.isLoading ? <Loading label="正在读取节奏数据…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : matches.length ? (
            <div className="league-grid is-four">
              <div className="league-card"><span>场均击杀/分</span><b>{number(avg, 2)}</b><em>KPM</em></div>
              <div className="league-card"><span>样本局</span><b>{number(matches.length)}</b><em>局</em></div>
              <div className="league-card"><span>最快节奏</span><b>{number(hottest?.killsPerMinute, 2)}</b><em>{hottest?.opponent || hottest?.date || '—'}</em></div>
              <div className="league-card"><span>最慢节奏</span><b>{number(coolest?.killsPerMinute, 2)}</b><em>{coolest?.opponent || coolest?.date || '—'}</em></div>
            </div>
          ) : <BoardEmpty title="还没有击杀节奏样本" />}
    </AnalysisSection>
  )
}

/** 按对手看节奏。 */
function TempoByOpponentBlock() {
  const { baseUrl } = useConnection()
  const query = useTempo(baseUrl)
  const rows = new Map<string, { opponent: string; games: number; kpmSum: number; kpmN: number; diffSum: number; diffN: number }>()
  for (const match of query.data?.process?.matches || []) {
    const key = match.opponent || '未标注'
    const row = rows.get(key) || { opponent: key, games: 0, kpmSum: 0, kpmN: 0, diffSum: 0, diffN: 0 }
    row.games += 1
    if (typeof match.killsPerMinute === 'number') { row.kpmSum += match.killsPerMinute; row.kpmN += 1 }
    if (typeof match.finalDiff === 'number') { row.diffSum += match.finalDiff; row.diffN += 1 }
    rows.set(key, row)
  }
  const list = [...rows.values()].sort((a, b) => b.games - a.games).slice(0, 12)
  return (
    <AnalysisSection title="按对手节奏" note="块库 · 按对手汇总节奏与终局金差。">
      {query.isLoading ? <Loading label="正在读取节奏数据…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : list.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>对手</th><th>局数</th><th>击杀/分</th><th>场均金差</th></tr></thead>
                <tbody>
                  {list.map((row) => (
                    <tr key={row.opponent}>
                      <td>{row.opponent}</td>
                      <td className="is-num">{row.games}</td>
                      <td className="is-num">{row.kpmN ? number(row.kpmSum / row.kpmN, 2) : '—'}</td>
                      <td className="is-num">{row.diffN ? signed(row.diffSum / row.diffN) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有节奏样本" />}
    </AnalysisSection>
  )
}

/** 选手状态榜。 */
function PlayerFormBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayerBoard(baseUrl)
  const rows = [...(query.data?.form || [])].filter((row) => row.available).sort((a, b) => b.delta - a.delta)
  return (
    <AnalysisSection title="选手状态榜" note="块库 · 近期与基线差值；只列可计算的选手。">
      {query.isLoading ? <Loading label="正在读取选手状态…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>选手</th><th>样本</th><th>基线</th><th>近期</th><th>变化</th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.label || row.id}</td>
                      <td className="is-num">{row.samples}</td>
                      <td className="is-num">{number(row.prior, 1)}</td>
                      <td className="is-num">{number(row.recent, 1)}</td>
                      <td className={`is-num ${row.tone === 'up' ? 'tone-text-own' : row.tone === 'down' ? 'tone-text-foe' : ''}`}>{row.delta > 0 ? '+' : ''}{number(row.delta, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有可计算的选手状态" />}
    </AnalysisSection>
  )
}

/** 固定搭档。 */
function PlayerPairsBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayerBoard(baseUrl)
  const rows = [...(query.data?.pairs || [])].sort((a, b) => b.games - a.games).slice(0, 12)
  return (
    <AnalysisSection title="固定搭档" note="块库 · 同场次数与胜率；同队同时出场口径。">
      {query.isLoading ? <Loading label="正在读取搭档…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : rows.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>搭档</th><th>同场</th><th>胜率</th></tr></thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={`${row.a.id}-${row.b.id}-${index}`}>
                      <td>{row.a.label} + {row.b.label}</td>
                      <td className="is-num">{row.games}</td>
                      <td className="is-num">{percent(row.winRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="还没有固定搭档样本" />}
    </AnalysisSection>
  )
}

export const TEMPO_PLAYER_BLOCKS: RegisteredBlock[] = [
  { id: 'tempo.gold', base: 'tempo.gold', variant: '检查点', domain: 'match', title: '经济检查点', question: '各分钟点的平均经济差是多少？', filters: [], Component: TempoGoldCheckpointsBlock },
  { id: 'tempo.kills', base: 'tempo.kills', variant: '节奏', domain: 'match', title: '击杀节奏', question: '场均每分钟击杀多少？最快/最慢是哪局？', filters: [], Component: TempoKillsBlock },
  { id: 'tempo.opponent', base: 'tempo.opponent', variant: '按对手', domain: 'match', title: '按对手节奏', question: '对每个对手的节奏与金差如何？', filters: [], Component: TempoByOpponentBlock },
  { id: 'player.form', base: 'player.form', variant: '状态榜', domain: 'player', title: '选手状态榜', question: '谁近期状态在涨、谁在掉？', filters: [], Component: PlayerFormBlock },
  { id: 'player.pairs', base: 'player.pairs', variant: '搭档', domain: 'player', title: '固定搭档', question: '哪对选手同场最多、胜率多少？', filters: [], Component: PlayerPairsBlock }
]
