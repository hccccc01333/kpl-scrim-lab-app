/**
 * 上帝模式 · 第二十一批注册块（英雄对比 / 选手对比）
 */
import { useEffect, useState } from 'react'
import { useConnection } from '../../lib/app-context'
import { useCampCompare, usePlayersBoard } from '../../lib/hooks'
import { number, percent } from '../../lib/format'
import { AnalysisSection } from '../../components/analysis/AnalysisSection'
import { BoardEmpty } from '../../components/analysis/BoardBits'
import { ErrorState } from '../../components/ui'
import type { RegisteredBlock } from '../registry'

function Loading({ label }: { label: string }) {
  return <div className="board-muted" style={{ padding: '10px 0' }}>{label}</div>
}

/** 英雄对比：两个英雄的指标并列。 */
function HeroCompareBlock() {
  const { baseUrl } = useConnection()
  const query = useCampCompare(baseUrl)
  const rows = query.data?.heroes?.own || []
  const options = [...new Set(rows.map((row) => row.hero))].sort()
  const [left, setLeft] = useState(options[0] || '')
  const [right, setRight] = useState(options[1] || '')
  useEffect(() => {
    if (!left && options.length) setLeft(options[0])
  }, [left, options])
  useEffect(() => {
    if (!right && options.length) setRight(options[1] || options[0])
  }, [right, options])
  if (query.isLoading) return <AnalysisSection title="英雄对比"><Loading label="正在读取英雄…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="英雄对比"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const pick = (hero: string) => {
    const candidates = rows.filter((row) => row.hero === hero)
    if (!candidates.length) return null
    return candidates.reduce((best, row) => (row.games > best.games ? row : best), candidates[0])
  }
  const a = pick(left)
  const b = pick(right)
  const metrics = [
    { label: '局数', a: a?.games, b: b?.games, digits: 0, suffix: '' },
    { label: '胜率', a: a?.winRate, b: b?.winRate, digits: 1, suffix: '%' },
    { label: 'KDA', a: a?.kda, b: b?.kda, digits: 2, suffix: '' },
    { label: '分均经济', a: a?.gpm, b: b?.gpm, digits: 0, suffix: '' },
    { label: '分均输出', a: a?.dpmTotal, b: b?.dpmTotal, digits: 0, suffix: '' }
  ]
  return (
    <AnalysisSection title="英雄对比" note="块库 · 两个英雄并列；取分路样本最多的那条记录。">
      <div className="board-toolbar">
        <select value={left} onChange={(event) => setLeft(event.target.value)} aria-label="英雄 A">
          {options.map((hero) => <option value={hero} key={hero}>{hero}</option>)}
        </select>
        <span className="board-muted">vs</span>
        <select value={right} onChange={(event) => setRight(event.target.value)} aria-label="英雄 B">
          {options.map((hero) => <option value={hero} key={hero}>{hero}</option>)}
        </select>
      </div>
      {a && b ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>指标</th><th>{a.hero}</th><th>{b.hero}</th></tr></thead>
            <tbody>
              {metrics.map((row) => (
                <tr key={row.label}>
                  <td>{row.label}</td>
                  <td className="is-num">{number(row.a, row.digits)}{row.suffix}</td>
                  <td className="is-num">{number(row.b, row.digits)}{row.suffix}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="选择两个英雄开始对比" />}
    </AnalysisSection>
  )
}

/** 选手对比：两名本队选手的指标并列。 */
function PlayerCompareBlock() {
  const { baseUrl } = useConnection()
  const query = usePlayersBoard(baseUrl)
  const players = (query.data?.players || []).filter((player) => player.side === 'own')
  const options = [...new Set(players.map((player) => player.name))].sort()
  const [left, setLeft] = useState(options[0] || '')
  const [right, setRight] = useState(options[1] || '')
  useEffect(() => {
    if (!left && options.length) setLeft(options[0])
  }, [left, options])
  useEffect(() => {
    if (!right && options.length) setRight(options[1] || options[0])
  }, [right, options])
  if (query.isLoading) return <AnalysisSection title="选手对比"><Loading label="正在读取选手…" /></AnalysisSection>
  if (query.isError || !query.data) return <AnalysisSection title="选手对比"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></AnalysisSection>
  const pick = (name: string) => players.find((player) => player.name === name) || null
  const a = pick(left)
  const b = pick(right)
  const metrics = [
    { label: '局数', a: a?.games, b: b?.games, digits: 0 },
    { label: '胜率', a: a?.winRate, b: b?.winRate, digits: 1 },
    { label: '评分', a: a?.score, b: b?.score, digits: 1 },
    { label: '分路', a: a?.lane, b: b?.lane, text: true }
  ]
  return (
    <AnalysisSection title="选手对比" note="块库 · 两名本队选手并列；数据来自选手看板。">
      <div className="board-toolbar">
        <select value={left} onChange={(event) => setLeft(event.target.value)} aria-label="选手 A">
          {options.map((name) => <option value={name} key={name}>{name}</option>)}
        </select>
        <span className="board-muted">vs</span>
        <select value={right} onChange={(event) => setRight(event.target.value)} aria-label="选手 B">
          {options.map((name) => <option value={name} key={name}>{name}</option>)}
        </select>
      </div>
      {a && b ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>指标</th><th>{a.name}</th><th>{b.name}</th></tr></thead>
            <tbody>
              {metrics.map((row) => (
                <tr key={row.label}>
                  <td>{row.label}</td>
                  <td className="is-num">{row.text ? String(row.a ?? '—') : `${number(row.a as number | null, row.digits)}${row.label === '胜率' ? '%' : ''}`}</td>
                  <td className="is-num">{row.text ? String(row.b ?? '—') : `${number(row.b as number | null, row.digits)}${row.label === '胜率' ? '%' : ''}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <BoardEmpty title="选择两名选手开始对比" />}
    </AnalysisSection>
  )
}

export const COMPARE_BLOCKS: RegisteredBlock[] = [
  { id: 'hero.compare', base: 'hero.compare', variant: '对比表', domain: 'hero', title: '英雄对比', question: '两个英雄的胜率与产出谁更好？', filters: [], Component: HeroCompareBlock },
  { id: 'player.compare', base: 'player.compare', variant: '对比表', domain: 'player', title: '选手对比', question: '两名选手的局数、胜率与评分谁更好？', filters: [], Component: PlayerCompareBlock }
]
