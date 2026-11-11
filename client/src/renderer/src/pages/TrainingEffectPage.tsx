import { Link } from 'react-router-dom'
import { useConnection } from '../lib/app-context'
import { useTrainingEffect } from '../lib/hooks'
import { number } from '../lib/format'
import { AnalysisSection } from '../components/analysis/AnalysisSection'
import { BoardEmpty, StatGrid } from '../components/analysis/BoardBits'
import { ErrorState, PageHeader, SkeletonPage } from '../components/ui'
import type { EffectResult } from '../lib/types'

export function TrainingEffectPage() {
  const { baseUrl } = useConnection()
  const query = useTrainingEffect(baseUrl)
  const results = query.data?.results || []

  if (query.isLoading) return <SkeletonPage cards={2} />
  if (query.isError) {
    return <div className="page"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>
  }

  const usable = results.filter((result) => result.effect?.available)
  const meanEffect = usable.length
    ? usable.reduce((sum, result) => sum + (result.effect?.effectSize || 0), 0) / usable.length
    : null
  const latest = results[0]

  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="TRAINING EFFECT"
        title="训练效果"
        subtitle="记录训练干预，对照干预前后指标；比较是描述性观察，不代表因果。"
        actions={<>
          <Link className="btn" to="/training">训练计划</Link>
          <Link className="btn" to="/training/reports">复盘与报告</Link>
        </>}
      />

      <StatGrid items={[
        { label: '干预记录', value: number(results.length), note: '训练目标' },
        { label: '可对比', value: number(usable.length), note: '两侧样本 ≥ 5 人次' },
        { label: '平均效应量', value: meanEffect === null ? '—' : number(meanEffect, 2), note: 'Cohen’s d', tone: 'accent' },
        { label: '最近一条', value: latest?.start_date || '—', note: latest?.goal || '' }
      ]} />

      <div className="board-banner">{query.data?.dateNote || '只有来源包含完整年份的营地记录才参与前后对比；缺年份不会自行补全。'}</div>

      <AnalysisSection title="干预记录" note="仅统计本队；每侧至少 5 条有效人次，才计算效应量。客户端只读。">
        {results.length ? (
          <div className="effect-list">
            {results.map((result) => {
              const effect: NonNullable<EffectResult['effect']> = result.effect || { available: false }
              return (
                <article className="effect-card" key={result.id}>
                  <div className="effect-head">
                    <span>{result.start_date || '日期未知'}</span>
                    <small>{effect.label || result.metric || '观察指标'}</small>
                    <b className={`board-tag tone-${effect.available ? 'own' : 'muted'}`}>{effect.available ? '可对比' : '样本不足'}</b>
                  </div>
                  <h3>{result.goal}</h3>
                  {result.intervention ? <p className="effect-method">{result.intervention}</p> : null}
                  {effect.available ? (
                    <div className="effect-values">
                      <span><small>干预前</small><b>{number(effect.preMean, 2)}</b><em>{number(effect.nPre)} 人次</em></span>
                      <i>→</i>
                      <span><small>干预后</small><b>{number(effect.postMean, 2)}</b><em>{number(effect.nPost)} 人次</em></span>
                      <span><small>效应量 d</small><b>{number(effect.effectSize, 2)}</b><em>描述性对比</em></span>
                    </div>
                  ) : <p className="board-muted">{effect.reason || '样本不足，暂不计算。'}</p>}
                  {result.review ? <p className="effect-review">{result.review}</p> : null}
                </article>
              )
            })}
          </div>
        ) : (
          <BoardEmpty title="还没有训练干预">
            工作台登记训练目标后，系统会把干预前后各至少 5 条本队营地记录放在一起比较。
          </BoardEmpty>
        )}
      </AnalysisSection>

      <div className="board-foot">训练干预的登记与编辑仍在工作台；客户端只读展示结果，不推断因果。</div>
    </div>
  )
}
