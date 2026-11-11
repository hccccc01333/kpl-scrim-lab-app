export interface StackSegment {
  key: string
  label: string
  value: number | null | undefined
  tone?: 'own' | 'foe' | 'accent' | 'muted'
}

export function StackedBars({
  rows,
  unit = '%'
}: {
  rows: { label: string; segments: StackSegment[] }[]
  unit?: string
}) {
  return (
    <div className="stacked-bars">
      {rows.map((row) => {
        const total = row.segments.reduce((sum, segment) => sum + Math.max(0, segment.value || 0), 0) || 1
        return (
          <div className="stacked-row" key={row.label}>
            <span className="stacked-label">{row.label}</span>
            <div className="stacked-track">
              {row.segments.map((segment) => (
                <i
                  key={segment.key}
                  className={`tone-${segment.tone || 'own'}`}
                  style={{ width: `${Math.max(0, (segment.value || 0) / total * 100).toFixed(1)}%` }}
                  title={`${segment.label}：${(segment.value || 0).toFixed(1)}${unit}`}
                />
              ))}
            </div>
            <span className="stacked-legend">
              {row.segments.map((segment) => (
                <small key={segment.key} className={`tone-${segment.tone || 'own'}`}>
                  {segment.label} {segment.value === null || segment.value === undefined ? '—' : `${Math.round((segment.value || 0) * 10) / 10}${unit}`}
                </small>
              ))}
            </span>
          </div>
        )
      })}
    </div>
  )
}
