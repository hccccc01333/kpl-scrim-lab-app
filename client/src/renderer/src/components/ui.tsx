import { useState, type ReactNode } from 'react'
import { assetUrl } from '../lib/api'
import { initials } from '../lib/format'
import { useAppMeta } from '../lib/meta-context'
import { Icon } from './Icon'

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  meta
}: {
  eyebrow?: string
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  meta?: ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
        <h1 className="page-title">{title}</h1>
        {subtitle ? <div className="page-subtitle">{subtitle}</div> : null}
        {meta ? <div className="page-meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  )
}

export function Card({
  title,
  subtitle,
  action,
  children,
  className = '',
  noBody = false
}: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  noBody?: boolean
}) {
  return (
    <section className={`card ${className}`}>
      {title || subtitle || action ? (
        <div className="card-head">
          <div>
            {title ? <h2 className="card-title">{title}</h2> : null}
            {subtitle ? <div className="card-sub">{subtitle}</div> : null}
          </div>
          {action}
        </div>
      ) : null}
      {noBody ? children : <div className="card-body">{children}</div>}
    </section>
  )
}

export function Ledger({
  items,
  className = ''
}: {
  items: { label: ReactNode; value: ReactNode; note?: ReactNode }[]
  className?: string
}) {
  return (
    <div className={`ledger ${className}`}>
      {items.map((item, index) => (
        <div className="ledger-item" key={index}>
          <span className="ledger-label">{item.label}</span>
          <strong className="ledger-value">{item.value}</strong>
          {item.note ? <p className="ledger-note">{item.note}</p> : null}
        </div>
      ))}
    </div>
  )
}

export function Badge({
  tone = 'neutral',
  children
}: {
  tone?: 'neutral' | 'win' | 'loss' | 'gold'
  children: ReactNode
}) {
  return <span className={`badge ${tone === 'neutral' ? '' : `badge-${tone}`}`}>{children}</span>
}

export function Portrait({
  name,
  size = 'md',
  className = ''
}: {
  name?: string | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  const { baseUrl, icons } = useAppMeta()
  const [failed, setFailed] = useState(false)
  const src = name ? assetUrl(baseUrl, icons[name]) : ''
  const showImage = Boolean(src && !failed)
  const sizeClass = size === 'lg' ? ' portrait-lg' : size === 'sm' ? ' portrait-sm' : ''
  return (
    <span className={`portrait${sizeClass} ${className}`.trim()} title={name || undefined}>
      {showImage ? (
        <img src={src} alt={name || ''} loading="lazy" onError={() => setFailed(true)} />
      ) : (
        initials(name)
      )}
    </span>
  )
}

export function SkeletonPage({ cards = 3 }: { cards?: number }) {
  return (
    <div className="page" aria-busy="true">
      <div>
        <div className="skeleton skeleton-line" style={{ width: 120 }} />
        <div className="skeleton skeleton-title" style={{ width: '48%', height: 48 }} />
        <div className="skeleton skeleton-line" style={{ width: '38%' }} />
      </div>
      <div className="overview-grid">
        <div className="skeleton skeleton-card" style={{ height: 306 }} />
        <div className="skeleton skeleton-card" style={{ height: 306 }} />
      </div>
      {Array.from({ length: cards }).map((_, index) => (
        <div className="skeleton skeleton-card" key={index} />
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  children,
  action
}: {
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <b>{title}</b>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  )
}

export function ErrorState({
  title = '这一页暂时读不到',
  error,
  onRetry
}: {
  title?: ReactNode
  error?: unknown
  onRetry?: () => void
}) {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : '工作台没有返回数据。'
  return (
    <div className="error-state">
      <Icon name="alert" size={24} />
      <b>{title}</b>
      <p>{message}</p>
      {onRetry ? <button type="button" className="btn" onClick={onRetry}><Icon name="refresh" />重新读取</button> : null}
    </div>
  )
}

export function HeroLine({ name }: { name?: string | null }) {
  return (
    <span className="hero-line">
      <Portrait name={name} size="sm" />
      <span>{name || '未知英雄'}</span>
    </span>
  )
}
