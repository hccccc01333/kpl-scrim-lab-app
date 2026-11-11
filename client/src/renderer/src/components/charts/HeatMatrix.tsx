import type { ReactNode } from 'react'

export function HeatMatrix({
  rows,
  cols,
  values,
  unit = '',
  empty = '暂无矩阵数据'
}: {
  rows: string[]
  cols: string[]
  values: (number | null)[][]
  unit?: string
  empty?: string
}) {
  if (!rows.length || !cols.length) return <p className="board-empty">{empty}</p>
  const max = Math.max(1, ...values.flat().filter((value): value is number => typeof value === 'number'))
  return (
    <div className="heat-matrix-wrap">
      <table className="heat-matrix">
        <thead>
          <tr>
            <th />
            {cols.map((col) => <th key={col}>{col}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={row}>
              <th>{row}</th>
              {cols.map((col, colIndex) => {
                const value = values[rowIndex]?.[colIndex]
                const ratio = typeof value === 'number' ? Math.min(1, value / max) : 0
                return (
                  <td
                    key={`${row}-${col}`}
                    style={ratio ? { background: `color-mix(in srgb, var(--accent) ${(ratio * 62).toFixed(0)}%, transparent)` } : undefined}
                    title={typeof value === 'number' ? `${row} × ${col}：${value.toFixed(1)}${unit}` : `${row} × ${col}：无样本`}
                  >
                    {typeof value === 'number' && value > 0 ? Math.round(value * 10) / 10 : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MatrixLegend({ children }: { children: ReactNode }) {
  return <p className="heat-matrix-legend">{children}</p>
}
