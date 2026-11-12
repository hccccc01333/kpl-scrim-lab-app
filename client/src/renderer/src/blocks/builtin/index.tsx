/**
 * 上帝模式 · 内置注册块（第一批样板块）
 *
 * 这些块自带数据请求（组件内部调 hooks），所以可以放到任何页面。
 * 第二批开始把各页现有的内联分析逐步抽到这里，实现「所有分析都是块」。
 */
import { Link, useLocation } from 'react-router-dom'
import { useConnection } from '../../lib/app-context'
import { useBpBoard, useCampCompare, useMatch, useMatches } from '../../lib/hooks'
import { duration as fmtDuration, number, percent } from '../../lib/format'
import { heroRows } from '../../lib/analysis/heroes'
import { comboRows } from '../../lib/analysis/bp'
import { matchPath } from '../../lib/routes'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState, Portrait } from '../../components/ui'
import { dateInBlockRange } from '../filters'
import { useBlockFilter } from '../filter-context'
import { pageContextFromPath } from '../page-context'
import type { BpGame } from '../../lib/types'
import type { RegisteredBlock } from '../registry'
import { BP_BLOCKS } from './bp'
import { BP_ORDER_BLOCKS } from './bp-order'
import { DOMAIN_BLOCKS } from './domains'
import { MATCH_TEAM_BLOCKS } from './domains2'
import { HOME_BLOCKS } from './domains3'
import { MATCH_DETAIL_BLOCKS } from './domains4'
import { SERIES_BLOCKS } from './domains5'
import { RESOURCE_BLOCKS } from './domains6'
import { HERO_LANE_BLOCKS } from './domains7'
import { HERO_TEAM_BLOCKS } from './domains8'
import { PLAYER_CROSS_BLOCKS } from './domains9'
import { TEMPO_PLAYER_BLOCKS } from './domains10'
import { PARTNER_ROSTER_BLOCKS } from './domains11'
import { MATCHUP_CROSS_BLOCKS } from './domains12'
import { MATCH_TEAM_DEEP_BLOCKS } from './domains13'
import { COACH_MATCH_MISC_BLOCKS } from './domains14'
import { POOL_RESULT_BLOCKS } from './domains15'
import { DECISION_MISC_BLOCKS } from './domains16'
import { DECISION_RESOURCE_OBJECTIVE_BLOCKS } from './domains17'
import { DECISION_FIGHT_OPENING_BLOCKS } from './domains18'
import { DECISION_CATALOG_BLOCKS } from './domains19'
import { COMPARE_BLOCKS } from './domains20'
import { POSITION_REPORT_BLOCKS } from './domains21'
import { SUPER_BLOCKS } from './super'

function LoadingLine({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

function bpGamesMatching(games: BpGame[], values: ReturnType<typeof useBlockFilter>): BpGame[] {
  return games.filter((game) => {
    if (!dateInBlockRange(game.start, values)) return false
    if (values.opponent && game.opponent !== values.opponent) return false
    if (values.player && ![...game.players.own, ...game.players.enemy].includes(values.player)) return false
    if (values.hero) {
      const heroes = [...game.picks.own, ...game.picks.enemy, ...game.bans.own, ...game.bans.enemy]
      if (!heroes.some((entry) => entry.name === values.hero)) return false
    }
    return true
  })
}

/** 最近对局：块库第一个通用块 —— 比赛域，可放任何页面。 */
function MatchRecentBlock() {
  const { baseUrl } = useConnection()
  const query = useMatches(baseUrl)
  const filters = useBlockFilter()
  const matches = query.data || []
  const list = matches.filter((match) => {
    if (!dateInBlockRange(match.date, filters)) return false
    if (filters.opponent && match.opponent !== filters.opponent) return false
    if (filters.hero && !(match.heroes || []).includes(filters.hero)) return false
    if (filters.result && match.result !== filters.result) return false
    return true
  })
  return (
    <AnalysisSection title={`最近对局 · ${list.length} 局`} note="块库 · 分析块可加到任意页面；这里的筛选只作用于这一块。">
      {query.isLoading ? <LoadingLine label="正在读取对局…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : list.length ? (
            <div className="query-list">
              {list.slice(0, 8).map((match) => (
                <Link to={matchPath(match.key)} className="query-row" key={match.key}>
                  <span className="query-index">{match.date}</span>
                  <span className="query-main">
                    <b>{match.opponent ? `对阵 ${match.opponent}` : '对手未标注'}</b>
                    <small>{match.session || match.mode || '对局'}</small>
                  </span>
                  <span className={`board-tag tone-${match.result === 'win' ? 'own' : match.result === 'loss' ? 'foe' : 'muted'}`}>
                    {match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '—'}
                  </span>
                  <span className="query-metric"><small>时长</small>{fmtDuration(match.duration)}</span>
                  <span className="query-heroes">{(match.heroes || []).slice(0, 5).map((hero) => <Portrait name={hero} size="sm" key={hero} />)}</span>
                </Link>
              ))}
            </div>
          ) : <BoardEmpty title="当前筛选没有对局" />}
    </AnalysisSection>
  )
}

/** 本队英雄胜率：英雄域，自带 camp-compare 数据。 */
function HeroWinrateBlock() {
  const { baseUrl } = useConnection()
  const query = useCampCompare(baseUrl)
  if (query.isLoading) return <AnalysisSection title="本队英雄胜率"><LoadingLine label="正在读取英雄数据…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="本队英雄胜率"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const rows = heroRows(query.data, 'own').filter((row) => row.games > 0).sort((a, b) => b.games - a.games).slice(0, 12)
  return (
    <AnalysisSection title="本队英雄胜率" note="块库 · 全量营地面板口径；点英雄进详情。">
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>英雄</th><th>分路</th><th>局数</th><th>胜率</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.hero}-${row.lane}`}>
                  <td><span className="hero-line"><Portrait name={row.hero} size="sm" /><span>{row.hero}</span></span></td>
                  <td>{row.lane || '—'}</td>
                  <td className="is-num">{number(row.games)}</td>
                  <td className="is-num">{percent(row.winRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="还没有英雄样本" />}
    </AnalysisSection>
  )
}

/** 本队双人组合：BP 域，自带 bp-board 数据。 */
function BpComboBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const filters = useBlockFilter()
  const games = bpGamesMatching(query.data?.games || [], filters)
  const combos = comboRows(games, 'own', 2).slice(0, 12)
  return (
    <AnalysisSection title={`本队双人组合 · ${combos.length} 组`} note="块库 · 同一局同队同时选出的双人组，按出现局数排。">
      {query.isLoading ? <LoadingLine label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : combos.length ? (
            <div className="combo-mini">
              {combos.map((combo) => (
                <div className="combo-row" key={combo.heroes.join('|')}>
                  <span>{combo.heroes.join(' + ')}</span>
                  <b>{combo.games} 局</b>
                  <span>{percent(combo.winRate)}</span>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="当前筛选没有组合样本" />}
    </AnalysisSection>
  )
}

/** 同一种组合分析的另一种变体：表格版。 */
function BpComboTableBlock() {
  const { baseUrl } = useConnection()
  const query = useBpBoard(baseUrl)
  const filters = useBlockFilter()
  const combos = comboRows(bpGamesMatching(query.data?.games || [], filters), 'own', 2).slice(0, 16)
  return (
    <AnalysisSection title="本队双人组合 · 表格" note="块库 · 同一分析的不同变体：表格版。">
      {query.isLoading ? <LoadingLine label="正在读取 BP 名单…" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : combos.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>组合</th><th>局数</th><th>胜率</th></tr></thead>
                <tbody>
                  {combos.map((combo) => (
                    <tr key={combo.heroes.join('|')}>
                      <td>{combo.heroes.join(' + ')}</td>
                      <td className="is-num">{combo.games}</td>
                      <td className="is-num">{percent(combo.winRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="当前筛选没有组合样本" />}
    </AnalysisSection>
  )
}

/** 用页面上下文的块：加到单局页才出内容，换一局自动跟着变。 */
function CurrentMatchBlock() {
  const { baseUrl } = useConnection()
  const location = useLocation()
  const key = pageContextFromPath(location.pathname).matchKey || ''
  const query = useMatch(baseUrl, key)
  if (!key) {
    return (
      <AnalysisSection title="本局卡片" note="块库 · 需要单局页上下文。">
        <BoardEmpty title="这个块要放在单局页">打开任意一局，再从分析库添加。</BoardEmpty>
      </AnalysisSection>
    )
  }
  const detail = query.data
  const picks = detail?.draft?.picks
  const ownSide = detail?.ownCamp === 'red' || detail?.ownCamp === 'right' ? 'right' : 'left'
  const ownPicks = ownSide === 'right' ? picks?.right : picks?.left
  const enemyPicks = ownSide === 'right' ? picks?.left : picks?.right
  return (
    <AnalysisSection
      title={`本局 · ${detail?.opponent ? `对阵 ${detail.opponent}` : '对手未标注'}`}
      note="块库 · 用当前单局页的对局上下文；换一局自动跟着变。"
    >
      {query.isLoading ? <LoadingLine label="正在读取本局…" />
        : query.isError || !detail ? <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          : (
            <>
              <div className="board-muted" style={{ marginBottom: 8 }}>
                {detail.date} · {fmtDuration(detail.duration)} · {detail.result === 'win' ? '胜' : detail.result === 'loss' ? '负' : '无胜负'}
              </div>
              <div className="bp-game-row">
                <span className="is-own">本队</span>
                {(ownPicks || []).map((entry) => <span key={`own-${entry.name}`}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
              </div>
              <div className="bp-game-row">
                <span className="is-foe">对手</span>
                {(enemyPicks || []).map((entry) => <span key={`foe-${entry.name}`}><Portrait name={entry.name} size="sm" />{entry.name}</span>)}
              </div>
            </>
          )}
    </AnalysisSection>
  )
}

export const BUILTIN_BLOCKS: RegisteredBlock[] = [
  {
    id: 'match.recent',
    base: 'match.recent',
    variant: '列表',
    domain: 'match',
    title: '最近对局',
    question: '最近打了哪些局？按对手/英雄/赛果挑。',
    filters: ['range', 'opponent', 'hero', 'result'],
    Component: MatchRecentBlock
  },
  {
    id: 'match.current',
    base: 'match.current',
    variant: '本局卡片',
    domain: 'match',
    title: '本局卡片',
    question: '当前这一局的对手、结果与双方阵容（需要单局页上下文）。',
    filters: [],
    Component: CurrentMatchBlock
  },
  {
    id: 'hero.winrate',
    base: 'hero.winrate',
    variant: '表格',
    domain: 'hero',
    title: '本队英雄胜率',
    question: '这期英雄池里谁出场多、胜率多少？',
    filters: [],
    Component: HeroWinrateBlock
  },
  {
    id: 'bp.own-combos.cards',
    base: 'bp.own-combos',
    variant: '卡片',
    domain: 'bp',
    title: '本队双人组合',
    question: '本队最常一起拿的双人组是什么？胜率多少？',
    filters: ['range', 'opponent', 'player', 'hero'],
    Component: BpComboBlock
  },
  {
    id: 'bp.own-combos.table',
    base: 'bp.own-combos',
    variant: '表格',
    domain: 'bp',
    title: '本队双人组合',
    question: '本队最常一起拿的双人组是什么？胜率多少？',
    filters: ['range', 'opponent', 'player', 'hero'],
    Component: BpComboTableBlock
  },
  ...BP_BLOCKS,
  ...BP_ORDER_BLOCKS,
  ...DOMAIN_BLOCKS,
  ...MATCH_TEAM_BLOCKS,
  ...HOME_BLOCKS,
  ...MATCH_DETAIL_BLOCKS,
  ...SERIES_BLOCKS,
  ...RESOURCE_BLOCKS,
  ...HERO_LANE_BLOCKS,
  ...HERO_TEAM_BLOCKS,
  ...PLAYER_CROSS_BLOCKS,
  ...TEMPO_PLAYER_BLOCKS,
  ...PARTNER_ROSTER_BLOCKS,
  ...MATCHUP_CROSS_BLOCKS,
  ...MATCH_TEAM_DEEP_BLOCKS,
  ...COACH_MATCH_MISC_BLOCKS,
  ...POOL_RESULT_BLOCKS,
  ...DECISION_MISC_BLOCKS,
  ...DECISION_RESOURCE_OBJECTIVE_BLOCKS,
  ...DECISION_FIGHT_OPENING_BLOCKS,
  ...DECISION_CATALOG_BLOCKS,
  ...COMPARE_BLOCKS,
  ...POSITION_REPORT_BLOCKS,
  ...SUPER_BLOCKS
]
