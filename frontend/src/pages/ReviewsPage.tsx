import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../api'
import { ArrowIcon, RepeatIcon } from '../icons'
import type { Review } from '../types'
import { EmptyState, ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, formatDate } from '../components/Common'

export function ReviewsPage() {
  const reviews = useQuery({ queryKey: ['reviews'], queryFn: () => api<Review[]>('/api/v2/reviews') })
  const now = Date.now()
  const open = reviews.data?.filter((item) => !item.completed_at) ?? []
  return (
    <div className="page">
      <PageHeader kicker="ИНТЕРВАЛЬНОЕ ПОВТОРЕНИЕ" title="Возвращаем навык до того, как он станет знакомым только на вид." lead="Очередь повторения строится из реальных успешных проверок. Просроченное предлагается первым, но не блокирует остальные темы." action={<StatusPill status={open.some((item) => new Date(item.due_at).getTime() <= now) ? 'warning' : 'ok'}>{open.length} открыто</StatusPill>} />
      {reviews.isPending ? <LoadingBlock /> : null}
      {reviews.error ? <ErrorNotice error={reviews.error} /> : null}
      {!reviews.isPending && !open.length ? <EmptyState index="R0" title="Очередь спокойна" text="После первого доказанного навыка здесь появится адресное повторение." /> : null}
      <div className="review-timeline">{open.map((item, index) => { const due = new Date(item.due_at).getTime() <= now; return <article key={item.id} className={due ? 'due' : ''}><div className="timeline-pin"><RepeatIcon /></div><div><Eyebrow>{due ? 'НУЖНО СЕЙЧАС' : `ЗАПЛАНИРОВАНО ${String(index + 1).padStart(2, '0')}`}</Eyebrow><h2>{item.skill_id}</h2><p>{item.reason}</p><span>{formatDate(item.due_at)}</span></div><Link className="button button--quiet" to={`/lesson/${item.lesson_id}`}>Открыть <ArrowIcon /></Link></article> })}</div>
    </div>
  )
}
