import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useBpBoard } from '../lib/hooks'
import { duration as fmtDuration, number, percent } from '../lib/format'
import {
  EMPTY_FILTERS,
  comboRows,
  dayBuckets,
  filterGames,
  heroLens,
  pickBanCounts,
  sideResult,
  type BpFilters
} from '../lib/analysis/bp'
import { AnalysisSection, JumpNav } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { BarList } from '../components/charts/BarList'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

const JUMP = [
  { id: 'bp-profile', label: '条件画像' },
  { id: 'bp-picks', label: '选用榜' },
  { id: 'bp-bans', label: '禁用资源' },
  { id: 'bp-lens', label: '英雄透镜' },
  { id: 'bp-combos', label: '阵容组合' },
  { id: 'bp-sides', label: '阵营赛果' },
  { id: 'bp-games', label: '逐局名单' },
  { id: 'bp-days', label: '对局日' }
]

export function BpPage() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const [filters, setFilters] = useState<BpFilters>(EMPTY_FILTERS)
  const [lensHero, setLensHero] = useState('')
  const data = query.data

  const games = useMemo(() => (data ? filterGames(data.games, filters) : []), [data, filters])
  const counts = useMemo(() => pickBanCounts(games), [games])
  const lens = useMemo(() => heroLens(games, lensHero), [games, lensHero])
  const combos2 = useMemo(() => comboRows(games, 'own', 2), [games])
  const combos3 = useMemo(() => comboRows(games, 'own', 3), [games])
  const sides = useMemo(() => sideResult(games), [games])
  const days = useMemo(() => dayBuckets(games), [games])

  if (query.isLoading) return <SkeletonPage cards={3} />
  if (query.isError || !data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const decided = games.filter((game) => game.result === 'win' || game.result === 'loss')
  const wins = decided.filter((game) => game.result === 'win').length
  const winRate = decided.length ? wins / decided.length * 100 : null
  const opponents = [...new Set(data.games.map((game) => game.opponent))].sort()
  const dayOptions = [...new Set(data.games.map((game) => game.day))].sort().reverse()
  const heroes = Object.keys(data.heroMeta).sort()
  const heroOptions = [...new Set([...heroes, ...data.games.flatMap((game) => [...game.picks.own, ...game.picks.enemy, ...game.bans.own, ...game.bans.enemy].map((entry) => entry.name))])].sort()
  const patch = (value: Partial<BpFilters>) => setFilters((current) => ({ ...current, ...value }))

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="BP BOARD"
        title="BP 概览"
        subtitle="选用、禁用、针对 ban 与逐局名单，按对局对象维度交叉查看；营地不含禁选顺序。"
        actions={<>
          <Link className="btn" to="/bp/team">战队 BP</Link>
          <Link className="btn" to="/bp/coach">教练档案</Link>
        </>}
      />

      <StatGrid items={[
        { label: '命中对局', value: number(games.length), note: `全部 ${data.games.length} 局` },
        { label: '本队胜率', value: percent(winRate), note: `${wins} 胜 / ${decided.length} 决出`, tone: 'own' },
        { label: '本队选用', value: number(counts.ownPicks.reduce((sum, row) => sum + row.count, 0)), note: `${counts.ownPicks.length} 个英雄` },
        { label: '本队禁用', value: number(counts.ownBans.reduce((sum, row) => sum + row.count, 0)), note: `${counts.ownBans.length} 个英雄` },
        { label: '对手选用', value: number(counts.enemyPicks.reduce((sum, row) => sum + row.count, 0)), note: `${counts.enemyPicks.length} 个英雄` },
        { label: '覆盖对手', value: number(opponents.length), note: `${dayOptions.length} 个对局日` }
      ]} />

      <div className="board-toolbar bp-filter-bar">
        <select value={filters.opponent} onChange={(event) => patch({ opponent: event.target.value })} aria-label="对手">
          <option value="">全部对手</option>
          {opponents.map((item) => <option value={item} key={item}>{item}</option>)}
        </select>
        <select value={filters.day} onChange={(event) => patch({ day: event.target.value })} aria-label="对局日">
          <option value="">全部日期</option>
          {dayOptions.map((item) => <option value={item} key={item}>{item}</option>)}
        </select>
        <select value={filters.side} onChange={(event) => patch({ side: event.target.value })} aria-label="阵营">
          <option value="all">全部阵营</option>
          <option value="blue">蓝方</option>
          <option value="red">红方</option>
        </select>
        <select value={filters.result} onChange={(event) => patch({ result: event.target.value })} aria-label="赛果">
          <option value="all">全部赛果</option>
          <option value="win">胜</option>
          <option value="loss">负</option>
        </select>
        <select value={filters.hero} onChange={(event) => patch({ hero: event.target.value })} aria-label="英雄">
          <option value="">全部英雄</option>
          {heroOptions.map((item) => <option value={item} key={item}>{item}</option>)}
        </select>
        <select value={filters.range} onChange={(event) => patch({ range: Number(event.target.value) })} aria-label="范围">
          <option value={0}>全部范围</option>
          <option value={10}>最近 10 局</option>
          <option value={5}>最近 5 局</option>
        </select>
        <span className="board-muted">命中 {games.length} 局</span>
        <button type="button" className="btn btn-sm" onClick={() => { setFilters(EMPTY_FILTERS); setLensHero('') }}>重置</button>
      </div>

      <JumpNav items={JUMP} />

      <AnalysisSection id="bp-profile" title="条件 BP 画像" note="当前筛选下四类名单的前 8；次数为英雄出现在对应名单的局数。">
        <div className="condition-grid">
          <ConditionColumn title="本队选用" rows={counts.ownPicks.slice(0, 8)} tone="own" />
          <ConditionColumn title="本队禁用" rows={counts.ownBans.slice(0, 8)} tone="muted" />
          <ConditionColumn title="对手选用" rows={counts.enemyPicks.slice(0, 8)} tone="foe" />
          <ConditionColumn title="对手禁用" rows={counts.enemyBans.slice(0, 8)} tone="muted" />
        </div>
      </AnalysisSection>

      <div className="board-grid-2" id="bp-picks">
        <AnalysisSection title="本队选用榜" note="前 10 个英雄；胜率为本队选用该英雄时的胜率。">
          <BarList
            items={counts.ownPicks.slice(0, 10).map((row) => ({ label: row.hero, value: row.count, note: `${percent(row.winRate)} 胜率`, tone: 'own' }))}
            digits={0}
          />
        </AnalysisSection>

        <AnalysisSection id="bp-bans" title="禁用资源" note="本方与对手各自禁用次数前 8；不推断针对意图。">
          <div className="bp-mini-grid">
            <div><h4>本队禁用</h4><BarList items={counts.ownBans.slice(0, 8).map((row) => ({ label: row.hero, value: row.count, tone: 'own' }))} digits={0} /></div>
            <div><h4>对手禁用</h4><BarList items={counts.enemyBans.slice(0, 8).map((row) => ({ label: row.hero, value: row.count, tone: 'foe' }))} digits={0} /></div>
          </div>
        </AnalysisSection>
      </div>

      <AnalysisSection id="bp-lens" title="英雄透镜" note="选中英雄后列出它出现在哪一侧的选用 / 禁用名单。">
        <div className="board-toolbar">
          <select value={lensHero} onChange={(event) => setLensHero(event.target.value)} aria-label="选择英雄">
            <option value="">选择英雄</option>
            {heroes.map((hero) => <option value={hero} key={hero}>{hero}</option>)}
          </select>
          <span className="board-muted">{lensHero ? `${lens.length} 局命中` : '选一个英雄看它的选禁记录'}</span>
        </div>
        {lensHero ? (
          lens.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>日期</th><th>对手</th><th>角色</th><th>结果</th><th>对局</th></tr></thead>
                <tbody>
                  {lens.map((row) => (
                    <tr key={`${row.game.key}-${row.role}`}>
                      <td>{row.game.start}</td>
                      <td>{row.game.opponent}</td>
                      <td><span className={`board-tag tone-${row.role.includes('本方') ? 'own' : 'foe'}`}>{row.role}</span></td>
                      <td>{row.win === null ? '—' : row.win ? '胜' : '负'}</td>
                      <td><span className="board-muted">{row.game.key}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选下没有这名英雄" />
        ) : <BoardEmpty title="还没有选择英雄" />}
      </AnalysisSection>

      <div className="board-grid-2" id="bp-combos">
        <AnalysisSection title="本队阵容组合" note="同一局本队同时选出的双人 / 三人组。">
          <div className="combo-mini">
            <h4>双人</h4>
            {combos2.length ? combos2.map((combo) => (
              <div className="combo-row" key={combo.heroes.join('|')}>
                <span>{combo.heroes.join(' + ')}</span><b>{combo.games} 局</b><span>{percent(combo.winRate)}</span>
              </div>
            )) : <p className="board-muted">暂无样本</p>}
            <h4>三人</h4>
            {combos3.length ? combos3.map((combo) => (
              <div className="combo-row" key={combo.heroes.join('|')}>
                <span>{combo.heroes.join(' + ')}</span><b>{combo.games} 局</b><span>{percent(combo.winRate)}</span>
              </div>
            )) : <p className="board-muted">暂无样本</p>}
          </div>
        </AnalysisSection>

        <AnalysisSection id="bp-sides" title="阵营与赛果" note="蓝 / 红 × 胜 / 负 四格；占比按当前筛选的决出局计算。">
          <div className="side-grid">
            {sides.map((cell) => (
              <div className={`side-cell is-${cell.result} is-${cell.side}`} key={`${cell.side}-${cell.result}`}>
                <span>{cell.side === 'blue' ? '蓝方' : '红方'} · {cell.result === 'win' ? '胜' : '负'}</span>
                <b>{cell.games}</b>
                <small>{percent(cell.share)}</small>
              </div>
            ))}
          </div>
        </AnalysisSection>
      </div>

      <AnalysisSection id="bp-games" title="逐局 BP 名单" note="最多 8 局；选用五人、禁用五格，按营地终局名单原样展示。">
        {games.length ? (
          <div className="bp-game-list">
            {games.slice(0, 8).map((game) => (
              <div className="bp-game" key={game.key}>
                <div className="bp-game-head">
                  <b>{game.start}</b>
                  <span>{game.opponent}</span>
                  <span className={`board-tag tone-${game.result === 'win' ? 'own' : 'foe'}`}>{game.result === 'win' ? '胜' : '负'}</span>
                  <small>{game.side === 'blue' ? '蓝方' : '红方'} · {fmtDuration(game.duration)}</small>
                </div>
                <div className="bp-game-row">
                  <span className="is-own">本队</span>
                  {game.picks.own.map((entry) => <span key={`own-${entry.name}`} title={entry.name}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
                  <small>禁 {game.bans.own.map((entry) => entry.name).join(' · ') || '—'}</small>
                </div>
                <div className="bp-game-row">
                  <span className="is-foe">对手</span>
                  {game.picks.enemy.map((entry) => <span key={`foe-${entry.name}`} title={entry.name}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
                  <small>禁 {game.bans.enemy.map((entry) => entry.name).join(' · ') || '—'}</small>
                </div>
              </div>
            ))}
          </div>
        ) : <BoardEmpty title="当前筛选没有对局" />}
      </AnalysisSection>

      <AnalysisSection id="bp-days" title="对局日分布" note="每个对局日的局数与胜率；只基于当前筛选。">
        <BarList items={days.map((day) => ({ label: day.day, value: day.games, note: `${day.wins} 胜 · ${percent(day.winRate)}` }))} digits={0} />
      </AnalysisSection>

      <div className="board-foot">BP 数据只含终局名单，不含禁选先后与首抢方；本页使用全部营地样本，不套用首页日期筛选。{data.source}</div>
    </div>
  )
}

function ConditionColumn({ title, rows, tone }: { title: string; rows: ReturnType<typeof pickBanCounts>['ownPicks']; tone: 'own' | 'foe' | 'muted' }) {
  const max = rows[0]?.count || 1
  return (
    <div className="condition-column">
      <h4>{title}</h4>
      {rows.length ? rows.map((row, index) => (
        <div className="condition-row" key={row.hero}>
          <span className="rank-index">{index + 1}</span>
          <span className="condition-name">{row.hero}</span>
          <i className={`tone-${tone}`}><em style={{ width: `${Math.min(100, row.count / max * 100)}%` }} /></i>
          <b>{row.count}</b>
        </div>
      )) : <p className="board-muted">暂无样本</p>}
    </div>
  )
}
