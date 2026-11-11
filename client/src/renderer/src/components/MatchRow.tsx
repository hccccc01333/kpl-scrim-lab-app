import { useNavigate } from 'react-router-dom'
import { resultLabel, resultTone, scoreText, shortDate, duration as fmtDuration } from '../lib/format'
import type { MatchSummary } from '../lib/types'
import { Portrait } from './ui'

export function MatchRow({ match }: { match: MatchSummary }) {
  const navigate = useNavigate()
  const tone = resultTone(match.result)
  return (
    <button type="button" className="match-row" onClick={() => navigate(`/matches/${encodeURIComponent(match.key)}`)}>
      <div className="match-date">
        <b>{shortDate(match.date)}</b>
        <small>{match.date ? String(match.date).slice(0, 4) : '—'}</small>
      </div>
      <div className="match-opponent">
        <small>{match.session || match.mode || '训练赛'}{match.version ? ` · ${match.version}` : ''}</small>
        <b>{match.opponent ? `对阵 ${match.opponent}` : '对手未标注'}</b>
      </div>
      <span className={`badge ${tone === 'win' ? 'badge-win' : tone === 'loss' ? 'badge-loss' : ''}`}>
        {resultLabel(match.result)}
      </span>
      <span className="match-score">{scoreText(match.scores, match.ownCamp)}</span>
      <span className="match-duration">{fmtDuration(match.duration)}</span>
      <span className="match-heroes">
        {(match.heroes || []).slice(0, 5).map((hero) => <Portrait key={hero} name={hero} size="sm" />)}
      </span>
      <span className="match-arrow">→</span>
    </button>
  )
}
