import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useState } from 'react'

import { api, jsonBody } from '../api'
import { ArrowIcon, CheckIcon, RepeatIcon, TerminalIcon } from '../icons'
import type { Curriculum, Evidence, LabRun, LearningSession, Principal, Review, SessionPlan } from '../types'
import { EmptyState, ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, formatDate } from '../components/Common'

export function TodayPage({ principal }: { principal: Principal }) {
  const [duration, setDuration] = useState<15 | 45 | 90>(45)
  const queryClient = useQueryClient()
  const activeRuns = useQuery({ queryKey: ['lab-runs', 'active'], queryFn: () => api<LabRun[]>('/api/v2/lab-runs?status=active') })
  const reviews = useQuery({ queryKey: ['reviews'], queryFn: () => api<Review[]>('/api/v2/reviews') })
  const evidence = useQuery({ queryKey: ['evidence'], queryFn: () => api<Evidence[]>('/api/v2/evidence') })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api<LearningSession[]>('/api/v2/sessions') })
  const curriculum = useQuery({ queryKey: ['curriculum'], queryFn: () => api<Curriculum>('/api/v2/curriculum') })
  const plan = useMutation({
    mutationFn: async (minutes: number) => {
      const recommendation = await api<SessionPlan>('/api/v2/session-plans', { method: 'POST', ...jsonBody({ duration_minutes: minutes }) })
      if (principal.role === 'viewer') return { recommendation, session: null }
      const session = await api<LearningSession>('/api/v2/sessions', {
        method: 'POST',
        ...jsonBody({ duration_minutes: minutes, lesson_ids: recommendation.lessons.map((lesson) => lesson.id) }),
      })
      return { recommendation, session }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sessions'] }),
  })
  const active = activeRuns.data?.[0]
  const currentSession = sessions.data?.find((item) => item.status === 'planned' || item.status === 'active')
  const lessonIndex = new Map((curriculum.data?.lessons ?? []).map((lesson) => [lesson.id, lesson]))
  const openReviews = reviews.data?.filter((item) => !item.completed_at) ?? []
  const dueCount = openReviews.filter((item) => new Date(item.due_at) <= new Date()).length
  const nearestReview = openReviews[0]
  return (
    <div className="page page--today">
      <PageHeader
        kicker="ПОЛЕВАЯ СВОДКА / СЕГОДНЯ"
        title="Учимся доказывать, а не угадывать."
        lead="Выберите длину сессии. Академия рекомендует маршрут, но каталог остаётся открытым и не запирает вас в линейном курсе."
        action={<StatusPill status={principal.role === 'viewer' ? 'warning' : 'ok'}>{principal.role === 'viewer' ? 'режим чтения' : 'полный доступ'}</StatusPill>}
      />

      {active ? (
        <section className="resume-strip">
          <div className="resume-strip__icon"><TerminalIcon /></div>
          <div><Eyebrow>АКТИВНЫЙ LAB RUN #{active.id}</Eyebrow><h2>Точка работы сохранена</h2><p>Незавершённая сессия не закрывает каталог. Можно продолжить её или изучать теорию отдельно.</p></div>
          <Link className="button button--primary" to={`/lab/${active.id}`}>Продолжить <ArrowIcon /></Link>
        </section>
      ) : null}

      {!active && currentSession ? (
        <section className="plan-sheet">
          <div className="plan-sheet__edge">СЕССИЯ<br />{currentSession.duration_minutes}<br />МИН</div>
          <div className="plan-sheet__body"><Eyebrow>СОХРАНЁННЫЙ МАРШРУТ #{currentSession.id}</Eyebrow><ol>{currentSession.lesson_ids.map((lessonId) => { const lesson = lessonIndex.get(lessonId); return <li key={lessonId}><span>{lesson ? `${lesson.estimated_minutes} мин` : 'урок'}</span><div><strong>{lesson?.title ?? lessonId}</strong><p>{lesson?.summary ?? 'Откройте урок, чтобы продолжить сессию.'}</p></div><Link to={`/lesson/${lessonId}?sessionId=${currentSession.id}`} aria-label={`Продолжить ${lesson?.title ?? lessonId}`}><ArrowIcon /></Link></li> })}</ol></div>
        </section>
      ) : null}

      <section className="session-composer">
        <div className="session-composer__intro">
          <Eyebrow>КОНСТРУКТОР СЕССИИ</Eyebrow>
          <h2>Сколько внимания есть сейчас?</h2>
          <p>Академия заполняет выбранное время уроками по их оценочной длительности. В 90-минутном маршруте место заранее резервируется для доказательного отчёта.</p>
        </div>
        <div className="duration-switch" role="group" aria-label="Длительность сессии">
          {([15, 45, 90] as const).map((minutes) => (
            <button key={minutes} className={duration === minutes ? 'active' : ''} onClick={() => setDuration(minutes)}>
              <strong>{minutes}</strong><span>мин</span>
            </button>
          ))}
        </div>
        <button className="button button--ink" onClick={() => plan.mutate(duration)} disabled={plan.isPending}>
          {plan.isPending ? 'Собираем…' : 'Собрать маршрут'} <ArrowIcon />
        </button>
      </section>

      {plan.error ? <ErrorNotice error={plan.error} /> : null}
      {plan.data ? (
        <section className="plan-sheet">
            <div className="plan-sheet__edge">ПЛАН<br />{plan.data.recommendation.duration_minutes}<br />МИН</div>
          <div className="plan-sheet__body">
            <Eyebrow>РЕКОМЕНДАЦИЯ, НЕ БЛОКИРОВКА</Eyebrow>
            <ol>
              {plan.data.recommendation.lessons.map((lesson) => (
                <li key={lesson.id}>
                  <span>{String(lesson.estimated_minutes).padStart(2, '0')} мин</span>
                  <div><strong>{lesson.title}</strong><p>{lesson.summary}</p></div>
                  <Link aria-label={`Открыть ${lesson.title}`} to={`/lesson/${lesson.id}${plan.data.session ? `?sessionId=${plan.data.session.id}` : ''}`}><ArrowIcon /></Link>
                </li>
              ))}
            </ol>
          </div>
        </section>
      ) : null}

      <div className="metric-grid">
        <article><span className="metric-grid__icon"><CheckIcon /></span><p>Записи доказательств</p><strong>{evidence.data?.length ?? 0}</strong><small>только после полного учебного цикла</small></article>
        <article><span className="metric-grid__icon"><RepeatIcon /></span><p>Повторить сейчас</p><strong>{dueCount}</strong><small>{nearestReview ? `ближайшее: ${formatDate(nearestReview.due_at)}` : 'очередь чистая'}</small></article>
        <article><span className="metric-grid__icon"><TerminalIcon /></span><p>Активные попытки</p><strong>{active ? 1 : 0}</strong><small>не больше одной лаборатории</small></article>
      </div>

      {activeRuns.isPending || reviews.isPending ? <LoadingBlock /> : null}
      {!active && !plan.data ? (
        <EmptyState index="01" title="Начните с короткой уверенной сессии" text={principal.role === 'viewer' ? 'Выберите 15, 45 или 90 минут. В режиме чтения это создаст только рекомендацию.' : 'Выберите 15, 45 или 90 минут. Академия сохранит маршрут, а прогресс изменится только после полного лабораторного цикла.'} />
      ) : null}
    </div>
  )
}
