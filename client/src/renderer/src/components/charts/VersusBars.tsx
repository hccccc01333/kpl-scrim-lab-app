export interface VersusRow {
  label: string
  own: number | null | undefined
  foe: number | null | undefined
  ownLabel?: string
  foeLabel?: string
  digits?: number
  suffix?: string
}

export function VersusBars({
  rows,
  ownTitle = '本队',
  foeTitle = '对手',
  empty = '暂无可比样本'
}: {
  rows: VersusRow[]
  ownTitle?: string
  foeTitle?: string
  empty?: string
}) {
  if (!rows.length) return <p className="board-empty">{empty}</p>
  return (
    <div className="versus-bars">
      <div className="versus-head">
        <span>{ownTitle}</span><span /><span>{foeTitle}</span>
      </div>
      {rows.map((row) => {
        const own = typeof row.own === 'number' && Number.isFinite(row.own) ? row.own : null
        const foe = typeof row.foe === 'number' && Number.isFinite(row.foe) ? row.foe : null
        const max = Math.max(1, Math.abs(own || 0), Math.abs(foe || 0))
        return (
          <div className="versus-row" key={row.label}>
            <b className="is-own">{format(own, row.digits, row.suffix)}</b>
            <div className="versus-track">
              <span className="versus-half is-own">
                <i style={{ width: `${own === null ? 0 : Math.abs(own) / max * 100}%` }} />
              </span>
              <span className="versus-half is-foe">
                <i style={{ width: `${foe === null ? 0 : Math.abs(foe) / max * 100}%` }} />
              </span>
            </div>
            <b className="is-foe">{format(foe, row.digits, row.suffix)}</b>
            <span className="versus-label">{row.label}</span>
          </div>
        )
      })}
    </div>
  )
}

function format(value: number | null, digits = 0, suffix = '') {
  if (value === null) return '—'
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: digits })}${suffix}`
}
