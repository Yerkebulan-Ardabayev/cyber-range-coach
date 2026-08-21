import type { ReactNode } from 'react'

import { ApiError } from '../api'

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="eyebrow">{children}</p>
}

export function PageHeader({ kicker, title, lead, action }: { kicker: string; title: string; lead: string; action?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <Eyebrow>{kicker}</Eyebrow>
        <h1>{title}</h1>
        <p className="page-lead">{lead}</p>
      </div>
      {action ? <div className="page-header__action">{action}</div> : null}
    </header>
  )
}

export function StatusPill({ status, children }: { status: 'ok' | 'warning' | 'blocked' | 'neutral'; children: ReactNode }) {
  return <span className={`status-pill status-pill--${status}`}><span className="status-pill__dot" />{children}</span>
}

export function EmptyState({ index, title, text, action }: { index: string; title: string; text: string; action?: ReactNode }) {
  return (
    <section className="empty-state">
      <span className="empty-state__index">{index}</span>
      <div><h2>{title}</h2><p>{text}</p></div>
      {action}
    </section>
  )
}

export function ErrorNotice({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : 'Неизвестная ошибка'
  return <div className="notice notice--error" role="alert"><strong>Проверка остановлена.</strong><span>{message}</span></div>
}

export function LoadingBlock({ label = 'Сверяем факты' }: { label?: string }) {
  return <div className="loading-block" aria-live="polite"><span /><span /><span /><p>{label}</p></div>
}

export function formatDate(value: string | null): string {
  if (!value) return 'ещё не было'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export function shortHash(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
}
