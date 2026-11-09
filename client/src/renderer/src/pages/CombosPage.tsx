import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useCampCombos } from '../lib/hooks'
import { number, percent } from '../lib/format'
import { heroPath } from '../lib/routes'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, Portrait, SkeletonPage } from '../components/ui'
import type { CampCombo } from '../lib/types'

export function CombosPage() {
  const { baseUrl } = useConnection()
  const query = useCampCombos(baseUrl, 3)
  const [side, setSide] = useState<'own' | 'enemy'>('own')
  const data = query.data

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError || !data) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const pairs = data.pairs[side]?.combos || []
  const trios = data.trios[side]?.combos || []
  const total = pairs.length + trios.length
  const positive = [...pairs, ...trios].filter((combo) => (combo.synergy || 0) > 0).length
  const top = [...pairs, ...trios].sort((a, b) => (b.synergy || 0) - (a.synergy || 0))[0]

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="HERO COMBOS"
        title="英雄组合"
        subtitle="观察本队双人、三人组合与协同加成；协同是与单英雄基准的差值，小样本仅供观察。"
        actions={<>
          <Link className="btn" to="/heroes">英雄榜</Link>
          <Link className="btn" to="/heroes/compare">英雄对比</Link>
        </>}
      />

      <StatGrid items={[
        { label: '样本局数', value: number(data.games), note: `${data.pairs.minGames} 局起进双人榜` },
        { label: '双人组合', value: number(pairs.length), note: `${data.pairs.size} 人组` },
        { label: '三人组合', value: number(trios.length), note: `${data.trios.minGames} 局起进三人榜` },
        { label: '正协同', value: number(positive), note: `共 ${total} 组` },
        { label: '最高协同', value: top ? `${top.heroes.join(' + ')}` : '—', note: top ? `${top.synergy === null ? '—' : `${top.synergy > 0 ? '+' : ''}${top.synergy.toFixed(1)} pp`}` : '' }
      ]} />

      <div className="board-toolbar">
        <div className="segmented">
          <button type="button" className={side === 'own' ? 'is-active' : ''} onClick={() => setSide('own')}>本队</button>
          <button type="button" className={side === 'enemy' ? 'is-active' : ''} onClick={() => setSide('enemy')}>对手</button>
        </div>
        <span className="board-muted">协同 = 组合胜率 − 成员单英雄胜率均值；达阈值才进入榜单。</span>
      </div>

      <AnalysisSection title={`双人组合 · ${pairs.length} 组`} note="最多 9 张卡；卡片下方表格给完整口径。">
        <ComboCards combos={pairs.slice(0, 9)} />
        <ComboTable combos={pairs.slice(0, 40)} />
      </AnalysisSection>

      <AnalysisSection title={`三人组合 · ${trios.length} 组`} note="三人组样本通常更少，小样本会标注。">
        <ComboCards combos={trios.slice(0, 9)} />
        <ComboTable combos={trios.slice(0, 40)} />
      </AnalysisSection>

      <div className="board-foot">组合来自同一局同阵营同时出场；不含禁选顺序，也不推断因果。本页使用全部营地面板。</div>
    </div>
  )
}

function ComboCards({ combos }: { combos: CampCombo[] }) {
  if (!combos.length) return <BoardEmpty title="还没有达到样本阈值的组合" />
  return (
    <div className="combo-card-grid">
      {combos.map((combo) => (
        <div className="combo-big-card" key={combo.heroes.join('|')}>
          <div className="combo-heroes">
            {combo.heroes.map((hero) => (
              <Link to={heroPath(hero)} key={hero}><Portrait name={hero} size="sm" /><span>{hero}</span></Link>
            ))}
          </div>
          <div className="combo-big-meta">
            <span><small>局数</small><b>{combo.games}</b></span>
            <span><small>胜率</small><b>{percent(combo.winRate)}</b></span>
            <span><small>基准</small><b>{percent(combo.expected)}</b></span>
            <span><small>协同</small><b className={`tone-text-${(combo.synergy || 0) >= 0 ? 'own' : 'foe'}`}>{combo.synergy === null ? '—' : `${combo.synergy > 0 ? '+' : ''}${combo.synergy.toFixed(1)} pp`}</b></span>
          </div>
          {combo.small ? <span className="board-tag tone-muted">小样本</span> : null}
        </div>
      ))}
    </div>
  )
}

function ComboTable({ combos }: { combos: CampCombo[] }) {
  if (!combos.length) return null
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead><tr><th>组合</th><th>局数</th><th>胜率</th><th>基准</th><th>加成</th><th>样本</th></tr></thead>
        <tbody>
          {combos.map((combo) => (
            <tr key={combo.heroes.join('|')}>
              <td>{combo.heroes.join(' + ')}</td>
              <td className="is-num">{combo.games}</td>
              <td className="is-num">{percent(combo.winRate)}</td>
              <td className="is-num">{percent(combo.expected)}</td>
              <td className={`is-num tone-text-${(combo.synergy || 0) >= 0 ? 'own' : 'foe'}`}>{combo.synergy === null ? '—' : `${combo.synergy > 0 ? '+' : ''}${combo.synergy.toFixed(1)} pp`}</td>
              <td>{combo.small ? '小样本' : '达标'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
