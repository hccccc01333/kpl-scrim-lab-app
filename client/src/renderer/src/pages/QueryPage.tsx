import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useMatches } from '../lib/hooks'
import { duration as fmtDuration, number, percent, signed } from '../lib/format'
import { matchPath } from '../lib/routes'
import { goldDiffOf } from '../lib/analysis/matches'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'

type SortKey = 'new' | 'old' | 'duration' | 'gold'

export function QueryPage() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const [opponent, setOpponent] = useState('')
  const [hero, setHero] = useState('')
  const [result, setResult] = useState('')
  const [sort, setSort] = useState<SortKey>('new')

  const matches = query.data || []
  const index = useMemo(() => {
    const ordered = [...matches].sort((a, b) => String(a.date).localeCompare(String(b.date)))
    return new Map(ordered.map((match, position) => [match.key, position + 1]))
  }, [matches])
  const sessions = [...new Set(matches.map((match) => match.session).filter(Boolean))]
  const foes = [...new Set(matches.map((match) => match.opponent).filter((value): value is string => Boolean(value)))].sort()
  const heroes = [...new Set(matches.flatMap((match) => match.heroes || []))].sort()
  const decided = matches.filter((match) => match.result === 'win' || match.result === 'loss')
  const wins = matches.filter((match) => match.result === 'win').length
  const unlabeled = matches.filter((match) => !match.opponent).length
  const dayCount = new Set(matches.map((match) => match.date).filter(Boolean)).size
  const avgDuration = matches.length
    ? matches.reduce((sum, match) => sum + (match.duration || 0), 0) / matches.length
    : null
  const rows = useMemo(() => {
    const keyword = opponent.trim().toLowerCase()
    const heroKeyword = hero.trim()
    return matches
      .filter((match) => {
        if (keyword && !`${match.opponent || ''} ${match.title || ''} ${match.date || ''}`.toLowerCase().includes(keyword)) return false
        if (heroKeyword && !(match.heroes || []).includes(heroKeyword)) return false
        if (result && match.result !== result) return false
        return true
      })
      .sort((a, b) => {
        if (sort === 'old') return String(a.date).localeCompare(String(b.date))
        if (sort === 'duration') return (b.duration || 0) - (a.duration || 0)
        if (sort === 'gold') return Math.abs(goldDiffOf(b) || 0) - Math.abs(goldDiffOf(a) || 0)
        return String(b.date).localeCompare(String(a.date))
      })
  }, [matches, opponent, hero, result, sort])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="MATCH QUERY"
        title="智能找局"
        subtitle="按对手、英雄、结果与排序，挑出要复盘的那一局。"
        actions={<Link className="btn" to="/matches/cross">跨局分析</Link>}
      />

      <StatGrid items={[
        { label: '当前范围', value: number(matches.length), note: sessions.length ? `${sessions.length} 个训练组` : `${dayCount} 个对局日` },
        { label: '对手', value: foes.length ? number(foes.length) : '未标注', note: unlabeled ? `${unlabeled} 局未标注` : '全部已标注' },
        { label: '胜率', value: percent(decided.length ? wins / decided.length * 100 : null), note: `${wins} 胜 / ${decided.length} 局有胜负` },
        { label: '平均时长', value: fmtDuration(avgDuration), note: '按营地记录' },
        { label: '命中', value: number(rows.length), note: '随筛选变化' }
      ]} />

      <div className="board-toolbar">
        <input
          className="board-search"
          list="query-foes"
          value={opponent}
          onChange={(event) => setOpponent(event.target.value)}
          placeholder="输入对手或日期"
          aria-label="对手"
        />
        <datalist id="query-foes">{foes.map((item) => <option value={item} key={item} />)}</datalist>
        <input
          className="board-search"
          list="query-heroes"
          value={hero}
          onChange={(event) => setHero(event.target.value)}
          placeholder="输入英雄"
          aria-label="英雄"
        />
        <datalist id="query-heroes">{heroes.map((item) => <option value={item} key={item} />)}</datalist>
        <div className="segmented">
          {['', 'win', 'loss'].map((value) => (
            <button type="button" key={value || 'all'} className={result === value ? 'is-active' : ''} onClick={() => setResult(value)}>
              {value === '' ? '全部' : value === 'win' ? '胜' : '负'}
            </button>
          ))}
        </div>
        <select value={sort} onChange={(event) => setSort(event.target.value as SortKey)} aria-label="排序">
          <option value="new">最新在前</option>
          <option value="old">最早在前</option>
          <option value="duration">时长最长</option>
          <option value="gold">金差最大</option>
        </select>
        <span className="board-muted">共 {rows.length} 局</span>
      </div>

      <AnalysisSection title={`对局列表 · ${rows.length} 局`} note="筛选与排序只影响当前视图，不改变数据口径。">
        {rows.length ? (
          <div className="query-list">
            {rows.map((match) => (
              <Link to={matchPath(match.key)} className="query-row" key={match.key}>
                <span className="query-index">第 {index.get(match.key)} 局</span>
                <span className="query-main">
                  <b>{match.opponent ? `对阵 ${match.opponent}` : '对手未标注'}</b>
                  <small>{match.date} · {match.session || match.mode || '对局'} · {match.version || '版本未记录'}</small>
                </span>
                <span className={`board-tag tone-${match.result === 'win' ? 'own' : match.result === 'loss' ? 'foe' : 'muted'}`}>
                  {match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '—'}
                </span>
                <span className="query-metric"><small>时长</small>{fmtDuration(match.duration)}</span>
                <span className="query-metric"><small>终局金差</small>{signed(goldDiffOf(match))}</span>
                <span className="query-heroes">{(match.heroes || []).slice(0, 5).map((item) => <Portrait name={item} size="sm" key={item} />)}</span>
                <span className="query-go">→</span>
              </Link>
            ))}
          </div>
        ) : <BoardEmpty title="没有符合当前条件的对局">清空筛选再试。</BoardEmpty>}
      </AnalysisSection>

      <div className="board-foot">搜索与排序只作用于当前列表；所有对局仍来自同一份已确认样本。</div>
    </div>
  )
}
