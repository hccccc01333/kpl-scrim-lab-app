import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { usePlayersBoard } from '../lib/hooks'
import { number, percent, signed } from '../lib/format'
import { playerPath } from '../lib/routes'
import {
  PERCENT_METRICS,
  formLabel,
  formTone,
  heroPool,
  keyGames,
  partnersOf,
  playstyleTags,
  playerPercent,
  playerSlice,
  playerValue,
  sameLaneMatchups,
  sameLanePeers,
  scoreTier,
  sideName,
  sliceOptions,
  styleAxes
} from '../lib/analysis/players'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, PercentBar, StatGrid, Tag, TierBadge } from '../components/analysis/BoardBits'
import { PercentileRadar } from '../components/charts/PercentileRadar'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'

type SliceKind = 'all' | 'day' | 'opponent'

export function PlayerPage() {
  const { baseUrl } = useConnection()
  const { key = '' } = useParams()
  const query = usePlayersBoard(baseUrl)
  const [sliceKind, setSliceKind] = useState<SliceKind>('all')
  const [sliceValue, setSliceValue] = useState('')
  const board = query.data
  const player = board?.players.find((item) => item.name === key)

  const view = useMemo(() => {
    if (!player || sliceKind === 'all' || !sliceValue) return player || null
    return playerSlice(player, sliceKind, sliceValue)
  }, [player, sliceKind, sliceValue])

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }
  if (!board || !player || !view) {
    return (
      <div className="page">
        <PageHeader eyebrow="PLAYER" title="选手详情" actions={<Link className="btn" to="/players/archive">选手档案</Link>} />
        <BoardEmpty title="找不到这名选手">可能昵称已经改名或这一期没有出场记录。</BoardEmpty>
      </div>
    )
  }

  const peers = board.players
    .filter((item) => item.side === player.side && item.lane === player.lane)
    .sort((a, b) => (b.score || 0) - (a.score || 0))
  const rank = peers.findIndex((item) => item.name === player.name) + 1
  const tags = playstyleTags(player)
  const axes = styleAxes(player)
  const best = keyGames(view)
  const partners = partnersOf(board, player.name)
  const matchups = sameLaneMatchups(board, player.name)
  const lanePeers = sameLanePeers(board, player.lane, player.side === 'enemy' ? 'enemy' : 'own')
  const optionList = sliceKind === 'all' ? [] : sliceOptions(player, sliceKind)
  const recent = view.recent || []

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="PLAYER"
        title={<>{player.name}<em>{[player.lane, sideName(player.side), player.bound ? '已认领' : '待认领'].join(' · ')}</em></>}
        actions={<>
          <Link className="btn" to="/players/archive">选手档案</Link>
          <Link className="btn" to={`/players/compare?a=${encodeURIComponent(player.name)}`}>加入对比</Link>
          <Link className="btn" to="/players">名单与状态</Link>
        </>}
      />

      <div className="board-toolbar">
        <div className="segmented">
          {(['all', 'day', 'opponent'] as SliceKind[]).map((kind) => (
            <button
              type="button"
              key={kind}
              className={sliceKind === kind ? 'is-active' : ''}
              onClick={() => { setSliceKind(kind); setSliceValue('') }}
            >
              {kind === 'all' ? '本期全部' : kind === 'day' ? '按日期' : '按对手'}
            </button>
          ))}
        </div>
        {sliceKind !== 'all' ? (
          <select
            value={sliceValue}
            onChange={(event) => setSliceValue(event.target.value)}
            aria-label="切片范围"
          >
            <option value="">选择{sliceKind === 'day' ? '日期' : '对手'}</option>
            {optionList.map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
        ) : null}
        {sliceKind !== 'all' && sliceValue
          ? <span className="board-muted">当前切片：{sliceValue} · {view.games} 局</span>
          : <span className="board-muted">分位保持全局口径，原始值随切片变化。</span>}
      </div>

      <StatGrid items={[
        { label: '出场', value: number(view.games), note: `${view.wins} 胜 / ${view.decided} 决出` },
        { label: '胜率', value: percent(view.winRate), note: `同位置第 ${rank || '—'} / ${peers.length}` },
        { label: '表现分', value: <>{number(player.score, 1)} <TierBadge tier={scoreTier(player.score)} /></>, note: '全局', tone: 'accent' },
        { label: 'KDA', value: number(view.kda, 2), note: `分均经济 ${number(view.gpm)}` },
        { label: '分均输出', value: number(view.dpm), note: `输出占比 ${percent(view.damageShare)}` },
        { label: '状态', value: formLabel(player.form), note: player.form?.samples ? `${player.form.samples} 局样本` : '样本不足', tone: formTone(player.form) === 'muted' ? 'muted' : formTone(player.form) === 'down' ? 'foe' : 'own' }
      ]} />

      <div className="board-grid-2">
        <AnalysisSection title="同位置分位" note="分位在「同分路同阵营」内计算；50 = 分路中位，条越长越靠前。">
          <div className="pct-radar-wrap">
            <PercentileRadar
              axes={PERCENT_METRICS.slice(0, 6).map((metric) => metric.label)}
              series={[{ label: player.name, tone: 'own', values: PERCENT_METRICS.slice(0, 6).map((metric) => playerPercent(player, metric.key)) }]}
              size={220}
            />
            <div className="pct-list">
              {PERCENT_METRICS.map((metric) => (
                <div className="pct-row" key={metric.key}>
                  <span>{metric.label}</span>
                  <PercentBar value={playerPercent(player, metric.key)} />
                  <b>{formatRaw(playerValue(view, metric.key), metric.key)}</b>
                </div>
              ))}
            </div>
          </div>
          <p className="board-note">表现分 = KDA / 分均经济 / 分均输出 / 参团四项分位均值；只作横向比较，不是选手评价。</p>
        </AnalysisSection>

        <AnalysisSection title="打法画像" note="六轴分位对齐个人在分路里的相对位置；标签只描述本期样本。">
          <div className="style-tags">
            {tags.length ? tags.map((tag) => <Tag key={tag} tone="own">{tag}</Tag>) : <span className="board-muted">样本不足以形成稳定画像。</span>}
          </div>
          <div className="axis-list">
            {axes.map((axis) => (
              <div className="axis-row" key={axis.key}>
                <span>{axis.label}</span>
                <i><em style={{ width: `${axis.value}%` }} /></i>
                <b>{Math.round(axis.value)}</b>
              </div>
            ))}
          </div>
          <div className="style-notes">
            <span><small>兼位</small><b>{player.laneMix.filter((mix) => mix.lane !== player.lane).map((mix) => `${mix.lane} ${mix.games} 局`).join(' · ') || '专职'}</b></span>
            <span><small>英雄池</small><b>{heroPool(player).length} 个英雄</b></span>
            <span><small>MVP</small><b>{player.mvp} 次</b></span>
          </div>
        </AnalysisSection>
      </div>

      <AnalysisSection title="逐局表现" note="最多最近 12 局；评分、KDA 与分均经济来自营地十人面板。">
        {recent.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>日期</th><th>对手</th><th>英雄</th><th>分路</th><th>结果</th><th>KDA</th><th>分均经济</th><th>分均输出</th><th>评分</th><th>MVP</th></tr></thead>
              <tbody>
                {recent.slice(0, 12).map((game) => (
                  <tr key={game.gameId}>
                    <td>{game.day}</td>
                    <td>{game.opponent || '—'}</td>
                    <td><span className="hero-line"><Portrait name={game.hero} size="sm" /><span>{game.hero || '—'}</span></span></td>
                    <td>{game.lane || '—'}</td>
                    <td><span className={`board-tag tone-${game.result === 'win' ? 'own' : 'foe'}`}>{game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '未定'}</span></td>
                    <td className="is-num">{number(game.kda, 2)}</td>
                    <td className="is-num">{number(game.gpm)}</td>
                    <td className="is-num">{number(game.dpm)}</td>
                    <td className="is-num">{number(game.rating, 1)}</td>
                    <td className="is-num">{game.mvp ? 'MVP' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="这个切片没有逐局记录">换一个日期或对手再看。</BoardEmpty>}
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="同局对位" note="同分路双方终局经济差；只统计同路各有一人的局。">
          {matchups.length ? (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>日期</th><th>对手</th><th>我方英雄</th><th>对方英雄</th><th>经济差</th><th>结果</th></tr></thead>
                <tbody>
                  {matchups.map((row) => (
                    <tr key={row.game.id}>
                      <td>{row.game.day}</td>
                      <td><Link className="text-link" to={`/matches/${encodeURIComponent(row.game.match)}`}>{row.game.opponent || '—'}</Link></td>
                      <td>{row.ownHero}</td>
                      <td>{row.enemyHero} <small className="board-muted">{row.enemyPlayer}</small></td>
                      <td className={`is-num ${(row.goldDiff || 0) >= 0 ? 'tone-text-own' : 'tone-text-foe'}`}>{signed(row.goldDiff)}</td>
                      <td>{row.win ? '胜' : '负'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <BoardEmpty title="没有可判定的同路对位">需要同一局同分路双方各有一人。</BoardEmpty>}
        </AnalysisSection>

        <AnalysisSection title="关键局" note="按个人评分排序，最高与最低各最多 3 局。">
          {best.length ? (
            <div className="key-games">
              {best.map((item) => (
                <div className={`key-game is-${item.tone}`} key={`${item.game.gameId}-${item.tone}`}>
                  <span>{item.tone === 'best' ? '高光' : '低谷'}</span>
                  <b>{number(item.game.rating, 1)}</b>
                  <small>{item.game.day} · {item.game.hero} · {item.game.result === 'win' ? '胜' : '负'}</small>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有可排序的评分" />}
        </AnalysisSection>
      </div>

      <div className="board-grid-2">
        <AnalysisSection title="搭档" note="同阵营共同出场次数；胜率为组合胜率。">
          {partners.length ? (
            <div className="partner-list">
              {partners.map((row) => (
                <div className="partner-row" key={row.name}>
                  <Link to={playerPath(row.name)}>{row.name}</Link>
                  <span>{row.games} 局</span>
                  <span>{percent(row.winRate)}</span>
                  <small>{row.hero || '—'}</small>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有搭档样本" />}
        </AnalysisSection>

        <AnalysisSection title="英雄池" note="按出场局数排序；评分与 KDA 为该英雄个人表现。">
          {heroPool(player).length ? (
            <div className="hero-pool-list">
              {heroPool(player).slice(0, 8).map((row) => (
                <div className="hero-pool-row" key={row.hero}>
                  <Portrait name={row.hero} size="sm" />
                  <Link to={`/heroes/${encodeURIComponent(row.hero)}`}>{row.hero}</Link>
                  <span>{row.games} 局</span>
                  <span>{percent(row.games ? row.wins / row.games * 100 : null)}</span>
                  <b>{number(row.rating, 1)}</b>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有英雄记录" />}
        </AnalysisSection>
      </div>

      <AnalysisSection title="同位置选手" note="同阵营同分路按表现分排序；点名字进入个人页。">
        {lanePeers.length ? (
          <div className="peer-grid">
            {lanePeers.map((peer) => (
              <Link to={playerPath(peer.name)} className={`peer-card${peer.name === player.name ? ' is-current' : ''}`} key={peer.name}>
                <span className="peer-rank">{peers.findIndex((item) => item.name === peer.name) + 1}</span>
                <span><b>{peer.name}</b><small>{peer.games} 局 · {percent(peer.winRate)}</small></span>
                <strong>{number(peer.score, 1)}</strong>
              </Link>
            ))}
          </div>
        ) : <BoardEmpty title="同位置没有其他选手" />}
      </AnalysisSection>

      <div className="board-foot">分位与表现分为同池横向相对值；切片只改变原始值，不重算全局分位。营地昵称未认领时按昵称累计。</div>
    </div>
  )
}

function formatRaw(value: number | null, key: string) {
  if (value === null) return '—'
  const percentKeys = ['participation', 'damageShare', 'goldShare', 'takenShare']
  return percentKeys.includes(key) ? percent(value) : number(value, key === 'kda' ? 2 : 0)
}
