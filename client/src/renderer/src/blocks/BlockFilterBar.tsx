import {
  FILTER_LABELS,
  RANGE_OPTIONS,
  RESULT_OPTIONS,
  SIDE_OPTIONS,
  activeFilterCount,
  type BlockFilterKey,
  type BlockFilterOptions,
  type BlockFilterValues
} from './filters'

interface BlockFilterBarProps {
  keys: BlockFilterKey[]
  options: BlockFilterOptions
  values: BlockFilterValues
  onChange: (patch: Partial<BlockFilterValues>) => void
  onClear: () => void
}

export function BlockFilterBar({ keys, options, values, onChange, onClear }: BlockFilterBarProps) {
  const active = activeFilterCount(values)

  const select = (key: BlockFilterKey, current: string, items: { value: string; label: string }[]) => (
    <label className="god-filter-field" key={key}>
      <span>{FILTER_LABELS[key]}</span>
      <select value={current} onChange={(event) => onChange({ [key]: event.target.value })} aria-label={FILTER_LABELS[key]}>
        {items.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
    </label>
  )

  return (
    <div className="god-filter-bar">
      {keys.includes('range') ? (
        <label className="god-filter-field">
          <span>{FILTER_LABELS.range}</span>
          <select
            value={values.range}
            onChange={(event) => {
              const range = Number(event.target.value)
              if (range === -1) onChange({ range })
              else onChange({ range, from: '', to: '' })
            }}
            aria-label="时间"
          >
            {RANGE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </label>
      ) : null}
      {keys.includes('range') && values.range === -1 ? (
        <span className="god-date-pair">
          <input type="date" value={values.from} onChange={(event) => onChange({ from: event.target.value })} aria-label="开始日期" />
          <i>~</i>
          <input type="date" value={values.to} onChange={(event) => onChange({ to: event.target.value })} aria-label="结束日期" />
        </span>
      ) : null}
      {keys.includes('opponent') ? select('opponent', values.opponent, [{ value: '', label: '全部对手' }, ...(options.opponents || []).map((item) => ({ value: item, label: item }))]) : null}
      {keys.includes('player') ? select('player', values.player, [{ value: '', label: '全部选手' }, ...(options.players || []).map((item) => ({ value: item, label: item }))]) : null}
      {keys.includes('hero') ? select('hero', values.hero, [{ value: '', label: '全部英雄' }, ...(options.heroes || []).map((item) => ({ value: item, label: item }))]) : null}
      {keys.includes('side') ? select('side', values.side, SIDE_OPTIONS) : null}
      {keys.includes('result') ? select('result', values.result, RESULT_OPTIONS) : null}
      {active > 0 ? (
        <button type="button" className="god-filter-clear" onClick={onClear} title="清除这个块的筛选">
          清除 {active}
        </button>
      ) : null}
    </div>
  )
}
