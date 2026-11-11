import { useDeferredValue, useMemo, useState } from 'react'
import { useConnection } from '../lib/app-context'
import { useMatches } from '../lib/hooks'
import { dateRange, number, percent } from '../lib/format'
import { MatchRow } from '../components/MatchRow'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

type Filter = 'all' | 'win' | 'loss'

export function MatchesPage() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search.trim().toLowerCase())

  const matches = useMemo(() => {
    const rows = query.data || []
    return rows
      .filter((match) => filter === 'all' || match.result === filter)
      .filter((match) => {
        if (!deferredSearch) return true
        return [match.opponent, match.date, match.session, match.version, ...(match.heroes || [])]
          .some((value) => String(value || '').toLowerCase().includes(deferredSearch))
      })
      .slice()
      .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
  }, [query.data, filter, deferredSearch])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const rows = query.data || []
  const wins = rows.filter((match) => match.result === 'win').length
  const losses = rows.filter((match) => match.result === 'loss').length
  const decided = wins + losses
  const range = dateRange(rows.map((match) => match.date))

  return (
    <div className="page">
      <PageHeader
        eyebrow={`MATCHES · ${range}`}
        title={<>比赛<em>{number(rows.length)} 场记录 · 胜率 {percent(decided ? (wins / decided) * 100 : null)}</em></>}
        subtitle="按日期、对手、英雄或版本查找；点任意一场进入完整复盘。"
        meta={[
          `${number(wins)} 胜`,
          `${number(losses)} 负`,
          `${number(rows.length - decided)} 场结果未计`,
          `${number(rows.filter((match) => match.hasTimeline).length)} 场有时间轴`
        ].map((text) => <span key={text}>{text}</span>)}
      />

      <div className="players-toolbar">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {([['all', '全部'], ['win', '胜利'], ['loss', '失利']] as [Filter, string][]).map(([value, label]) => (
            <button key={value} type="button" className={`chip${filter === value ? ' is-active' : ''}`} onClick={() => setFilter(value)}>
              {label}
            </button>
          ))}
        </div>
        <label className="search">
          <Icon name="search" />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索对手、日期或英雄"
            aria-label="搜索比赛"
          />
        </label>
      </div>

      <section className="card">
        <div className="card-head">
          <div><h2 className="card-title">对局记录</h2><div className="card-sub">{number(matches.length)} 场符合当前筛选 · 按时间倒序</div></div>
        </div>
        <div className="match-ledger">
          {matches.map((match) => <MatchRow key={match.key} match={match} />)}
          {!matches.length ? <div className="empty-state"><b>没有符合条件的比赛</b><p>换一个关键词或筛选条件试试。</p></div> : null}
        </div>
      </section>
    </div>
  )
}
