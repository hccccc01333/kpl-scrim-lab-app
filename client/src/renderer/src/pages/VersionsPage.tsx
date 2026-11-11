import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useMatches } from '../lib/hooks'
import { duration as fmtDuration, number, percent, signed } from '../lib/format'
import { goldDiffOf } from '../lib/analysis/matches'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import type { MatchSummary } from '../lib/types'

type Dim = 'version' | 'session'

export function VersionsPage() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const [dim, setDim] = useState<Dim>('version')
  const matches = query.data || []
  const covered = matches.filter((match) => match.version).length
  const active: Dim = covered ? dim : 'session'
  const groups = useMemo(() => groupMatches(matches, active), [matches, active])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }
  const maxGames = Math.max(1, ...groups.map((group) => group.games))
  const sessions = new Set(matches.map((match) => match.session).filter(Boolean)).size
  const versions = new Set(matches.map((match) => match.version).filter(Boolean)).size
  const note = covered ? '' : `${matches.length} 局都还没有记录版本，先按训练组看；在单局里补录版本后，这里会自动按版本分组。`

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="VERSION COMPARE"
        title="版本对比"
        subtitle="按版本或训练组，看局数、胜率与平均节奏。"
        actions={<Link className="btn" to="/matches/records">训练纪录</Link>}
      />

      <StatGrid items={[
        { label: '对局', value: number(matches.length), note: `${matches.filter((match) => match.result === 'win').length} 胜` },
        { label: '版本覆盖', value: `${covered} / ${matches.length}`, note: `${versions} 个版本` },
        { label: '训练组', value: number(active === 'session' ? groups.length : sessions), note: '按对局记录' },
        { label: '当前分组', value: active === 'version' ? '按版本' : '按训练组', note: note || '有版本时默认按版本' }
      ]} />

      <div className="board-toolbar">
        <div className="segmented">
          <button type="button" className={active === 'version' ? 'is-active' : ''} disabled={!covered} onClick={() => setDim('version')}>版本</button>
          <button type="button" className={active === 'session' ? 'is-active' : ''} onClick={() => setDim('session')}>训练组</button>
        </div>
        <span className="board-muted">胜率只以有胜负的对局为分母；平均金差为本队减对手。</span>
      </div>

      {note ? <div className="board-banner">{note}</div> : null}

      <AnalysisSection title={active === 'version' ? '按版本对比' : '按训练组对比'} note={`${groups.length} 组 · ${matches.length} 局`}>
        {groups.length ? (
          <div className="version-list">
            <div className="version-row is-head"><span>分组</span><span>局数</span><span>胜率</span><span>平均时长</span><span>平均金差</span><span /></div>
            {groups.map((group) => (
              <div className="version-row" key={group.name}>
                <span className="version-name"><b>{group.name}</b><small>{group.decided} 局有胜负</small></span>
                <span className="version-count"><b>{group.games}</b><i><em style={{ width: `${group.games / maxGames * 100}%` }} /></i></span>
                <span className="is-num">{percent(group.winRate)}</span>
                <span className="is-num">{fmtDuration(group.avgDuration)}</span>
                <span className={`is-num ${(group.avgGold || 0) >= 0 ? 'tone-text-own' : 'tone-text-foe'}`}>{signed(group.avgGold)}</span>
                <span className="version-link">{group.keys[0] ? <Link to={`/matches/${encodeURIComponent(group.keys[0])}`}>看一局 →</Link> : null}</span>
              </div>
            ))}
          </div>
        ) : <BoardEmpty title="当前没有可分组的数据" />}
      </AnalysisSection>

      <div className="board-foot">版本按数字段排序（S42 → S41 → …），避免字典序把 S9 排在 S40 前面；训练组按局数排序。</div>
    </div>
  )
}

function groupMatches(matches: MatchSummary[], dim: Dim) {
  const map = new Map<string, { name: string; games: number; wins: number; decided: number; seconds: number; durationN: number; gold: number; goldN: number; keys: string[] }>()
  for (const match of matches) {
    const name = dim === 'version' ? (match.version || '未记录版本') : (match.session || '未标注训练组')
    const group = map.get(name) || { name, games: 0, wins: 0, decided: 0, seconds: 0, durationN: 0, gold: 0, goldN: 0, keys: [] }
    group.games += 1
    if (match.result === 'win' || match.result === 'loss') {
      group.decided += 1
      if (match.result === 'win') group.wins += 1
    }
    if (typeof match.duration === 'number' && match.duration > 0) {
      group.seconds += match.duration
      group.durationN += 1
    }
    const diff = goldDiffOf(match)
    if (typeof diff === 'number') {
      group.gold += diff
      group.goldN += 1
    }
    if (group.keys.length < 1) group.keys.push(match.key)
    map.set(name, group)
  }
  return [...map.values()]
    .sort((a, b) => dim === 'version' ? versionCompare(b.name, a.name) || b.games - a.games : b.games - a.games)
    .map((group) => ({
      ...group,
      winRate: group.decided ? group.wins / group.decided * 100 : null,
      avgDuration: group.durationN ? group.seconds / group.durationN : null,
      avgGold: group.goldN ? group.gold / group.goldN : null
    }))
}

function versionCompare(a: string, b: string) {
  const rank = (raw: string) => {
    const text = String(raw || '').toUpperCase()
    const hit = /^S(\d+)$/.exec(text)
    if (hit) return [2, Number(hit[1])]
    const numbers = text.match(/\d+/g)
    return numbers ? [1, ...numbers.map(Number)] : [0]
  }
  const left = rank(a), right = rank(b)
  for (let index = 0; index < Math.max(left.length, right.length); index++) {
    const delta = (left[index] || 0) - (right[index] || 0)
    if (delta) return delta
  }
  return String(a).localeCompare(String(b), 'zh')
}
