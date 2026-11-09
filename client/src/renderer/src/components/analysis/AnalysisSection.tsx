import type { ReactNode } from 'react'

export function AnalysisSection({
  id,
  title,
  note,
  action,
  children,
  className = ''
}: {
  id?: string
  title: ReactNode
  note?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card md-section ${className}`.trim()} id={id}>
      <div className="card-head">
        <div>
          <h2 className="card-title">{title}</h2>
          {note ? <div className="card-sub">{note}</div> : null}
        </div>
        {action}
      </div>
      <div className="card-body">{children}</div>
    </section>
  )
}

export function JumpNav({ items }: { items: { id: string; label: string }[] }) {
  return (
    <nav className="md-jump" aria-label="单局分析锚点">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => {
            const target = document.getElementById(item.id)
            target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }}
        >
          {item.label}
        </button>
      ))}
    </nav>
  )
}

export function ScopeNote({ children }: { children: ReactNode }) {
  return <p className="md-scope-note">{children}</p>
}
