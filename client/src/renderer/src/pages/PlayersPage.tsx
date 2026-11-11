import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { usePlayersBoard } from '../lib/hooks'
import { number, percent, signed } from '../lib/format'
import { playerPath } from '../lib/routes'
import {
  PLAYER_LANES,
  formLabel,
  formTone,
  laneIndex,
  sideName
} from '../lib/analysis/players'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { BarList } from '../components/charts/BarList'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import { Icon } from '../components/Icon'

export function PlayersPage() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  const board = query.data

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !board) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const own = board.players.filter((player) => player.side === 'own')
  const status = own.filter((player) => player.form?.available).sort((a, b) => (b.form?.delta || 0) - (a.form?.delta || 0))
  const roster = [...board.roster].sort((a, b) => laneIndex(a.lane) - laneIndex(b.lane))
  const duos = [...board.duos].sort((a, b) => b.games - a.games).slice(0, 8)
  const dayRows = [...new Set(board.games.map((game) => game.day))]
    .sort((a, b) => b.localeCompare(a))
    .map((day) => {
      const games = board.games.filter((game) => game.day === day)
      const wins = games.filter((game) => game.result === 'win').length
      return { day, games: games.length, wins, losses: games.length - wins }
    })
  const buckets = [
    { label: '1 局', min: 1, max: 1 },
    { label: '2–5 局', min: 2, max: 5 },
    { label: '6–10 局', min: 6, max: 10 },
    { label: '11 局以上', min: 11, max: Infinity }
  ].map((bucket) => ({
    ...bucket,
    players: own.filter((player) => player.games >= bucket.min && player.games <= bucket.max).length
  }))
  const recentDays = [...new Set(board.games.map((game) => game.day))].sort((a, b) => b.localeCompare(a)).slice(0, 3)

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="PLAYERS"
        title="名单与状态"
        subtitle="本期谁在打、谁有可比样本、状态往哪走；表现分按同位置分位合成，50 = 分路平均。"
        actions={<>
          <Link className="btn" to="/players/archive">选手档案</Link>
          <Link className="btn" to="/players/compare">选手对比</Link>
        </>}
      />

      <StatGrid items={[
        { label: '样本对局', value: number(board.summary.games), note: `${board.summary.days} 个对局日` },
        { label: '整体胜率', value: percent(board.summary.winRate), note: `${board.summary.wins} 胜 / ${board.summary.decided} 局` },
        { label: '本队出场', value: number(board.summary.ownPlayers), note: `${board.summary.bound} 人已认领` },
        { label: '状态可用', value: number(board.summary.formReady), note: `上升 ${board.summary.rising} · 回落 ${board.summary.falling}` },
        { label: '固定搭档', value: number(board.summary.pairs), note: `${board.duos.length} 组有同场记录 · ${board.lineups.length} 套五人组` },
        { label: '待认领昵称', value: number(board.summary.unclaimed), note: '只读展示，认领在工作台' }
      ]} />

      {board.summary.unclaimed > 0 ? (
        <div className="board-banner">
          <Icon name="info" size={15} />
          <span>还有 {board.summary.unclaimed} 个营地昵称未认领；这些记录按昵称单独累计，不并入本队名单。</span>
          <Link to="/players/archive">去档案看全部昵称</Link>
        </div>
      ) : null}

      <AnalysisSection title="位置名册" note="按分路看本期主力与轮换；表现分与胜率来自同池样本。">
        <div className="roster-grid">
          {PLAYER_LANES.map((lane) => {
            const slot = roster.find((item) => item.lane === lane)
            const player = slot?.player ? own.find((item) => item.name === slot.player) : null
            return (
              <div className="roster-card" key={lane}>
                <span className="roster-lane">{lane}</span>
                {slot?.player ? (
                  <Link to={playerPath(slot.player)} className="roster-player">
                    <Portrait name={slot.player} size="md" />
                    <span><b>{slot.player}</b><small>{slot.bound ? '已认领' : '待认领'}</small></span>
                  </Link>
                ) : <span className="quiet">暂无记录</span>}
                <div className="roster-meta">
                  <span><small>局数</small><b>{number(slot?.games)}</b></span>
                  <span><small>胜率</small><b>{percent(slot?.winRate)}</b></span>
                  <span><small>表现</small><b>{player?.score ?? '—'}</b></span>
                </div>
              </div>
            )
          })}
        </div>
      </AnalysisSection>

      <AnalysisSection title="状态榜" note="最近三局均分减去之前三局均分；样本达到 6 局才给状态。">
        {status.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>选手</th><th>分路</th><th>近期</th><th>此前</th><th>变化</th><th>样本</th><th>状态</th></tr></thead>
              <tbody>
                {status.map((player) => (
                  <tr key={player.name}>
                    <td><Link className="text-link" to={playerPath(player.name)}>{player.name}</Link></td>
                    <td>{player.lane}</td>
                    <td className="is-num">{number(player.form?.recent, 1)}</td>
                    <td className="is-num">{number(player.form?.prior, 1)}</td>
                    <td className={`is-num tone-text-${formTone(player.form)}`}>{signed(player.form?.delta, 1)}</td>
                    <td className="is-num">{number(player.form?.samples)}</td>
                    <td><span className={`board-tag tone-${formTone(player.form)}`}>{formLabel(player.form)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <BoardEmpty title="还没有选手达到状态样本">至少需要 6 局才能比较最近与此前三段。</BoardEmpty>}
      </AnalysisSection>

      <div className="board-grid-2">
        <AnalysisSection title="固定搭档" note={`同阵营共同出场；与全队胜率 ${percent(board.summary.winRate)} 对照。`}>
          {duos.length ? (
            <div className="duo-list">
              {duos.map((duo) => (
                <div className="duo-row" key={`${duo.a}-${duo.b}`}>
                  <span className="duo-names">
                    <Link to={playerPath(duo.a)}>{duo.a}</Link>
                    <i>×</i>
                    <Link to={playerPath(duo.b)}>{duo.b}</Link>
                  </span>
                  <b>{number(duo.games)} 局</b>
                  <span>{percent(duo.winRate)}</span>
                  <small>{signed((duo.winRate || 0) - (board.summary.winRate || 0), 1)} pp</small>
                </div>
              ))}
            </div>
          ) : <BoardEmpty title="还没有固定搭档">需要同一阵营共同出场至少一局。</BoardEmpty>}
        </AnalysisSection>

        <AnalysisSection title="对局日一览" note="按对局日期汇总胜负，不推断训练质量。">
          <div className="day-list">
            {dayRows.map((row) => (
              <div className="day-row" key={row.day}>
                <b>{row.day}</b>
                <span>{row.games} 局</span>
                <span className="is-own">{row.wins} 胜</span>
                <span className="is-foe">{row.losses} 负</span>
                <i style={{ width: `${row.games ? row.wins / row.games * 100 : 0}%` }} />
              </div>
            ))}
          </div>
        </AnalysisSection>
      </div>

      <AnalysisSection title="出场结构" note="按本期出场局数分桶；样本少的人不进入状态比较。">
        <BarList
          items={buckets.map((bucket) => ({ label: bucket.label, value: bucket.players, note: '人' }))}
          digits={0}
        />
      </AnalysisSection>

      <AnalysisSection title="最近对局与阵容" note="最近 3 个对局日；每局列出双方十人昵称与英雄。">
        {board.games.length ? (
          <div className="recent-games">
            {recentDays.map((day) => (
              <div key={day} className="recent-day">
                <div className="recent-day-head"><b>{day}</b><span>{board.games.filter((game) => game.day === day).length} 局</span></div>
                {board.games.filter((game) => game.day === day).map((game) => (
                  <div className="recent-game" key={game.id}>
                    <div className="recent-game-head">
                      <Link to={`/matches/${encodeURIComponent(game.match)}`}>{game.opponent || '对手未标注'}</Link>
                      <span className={`board-tag tone-${game.result === 'win' ? 'own' : 'foe'}`}>{game.result === 'win' ? '胜' : game.result === 'loss' ? '负' : '未定'}</span>
                      <small>{game.map || '训练赛'} · {game.duration ? `${game.duration} 分` : '时长未知'}</small>
                    </div>
                    <div className="recent-lineup">
                      <div><span className="is-own">本队</span>{game.own.map((row) => <span key={`${row.name}-${row.hero}`} title={`${row.name} · ${row.kda ?? '—'} KDA`}>{row.hero}</span>)}</div>
                      <div><span className="is-foe">对手</span>{game.enemy.map((row) => <span key={`${row.name}-${row.hero}`} title={`${row.name} · ${row.kda ?? '—'} KDA`}>{row.hero}</span>)}</div>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : <BoardEmpty title="还没有对局记录" />}
      </AnalysisSection>

      <div className="board-foot">{board.identity.teamName} · 本页使用全部营地面板；{sideName('own')}与{sideName('enemy')}两侧选手都能在档案里查到。</div>
    </div>
  )
}
