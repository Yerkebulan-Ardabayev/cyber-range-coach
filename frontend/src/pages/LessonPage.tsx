import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMemo, useState } from 'react'

import { api, jsonBody } from '../api'
import { ArrowIcon, TerminalIcon } from '../icons'
import type { LabRun, LearningSession, Lesson, Principal, Target } from '../types'
import { ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, shortHash } from '../components/Common'
import { SimpleTheoryCard } from '../components/SimpleTheoryCard'

export function LessonPage({ principal }: { principal: Principal }) {
  const { lessonId = '' } = useParams()
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const plannedSessionId = Number(search.get('sessionId')) || null
  const [prediction, setPrediction] = useState('')
  const [targetId, setTargetId] = useState<number | null>(null)
  const lesson = useQuery({ queryKey: ['lesson', lessonId], queryFn: () => api<Lesson>(`/api/v2/lessons/${lessonId}`) })
  const targets = useQuery({ queryKey: ['targets'], queryFn: () => api<Target[]>('/api/v2/targets') })
  const compatibleTargets = useMemo(() => (targets.data ?? []).filter((target) => !lesson.data?.target_tags.length || lesson.data.target_tags.some((tag) => target.allowed_curriculum_tags.includes(tag))), [lesson.data, targets.data])
  const start = useMutation({
    mutationFn: async () => {
      const learningSession = plannedSessionId
        ? { id: plannedSessionId }
        : await api<LearningSession>('/api/v2/sessions', {
          method: 'POST',
          ...jsonBody({ duration_minutes: 15, lesson_ids: [lessonId] }),
        })
      return api<LabRun>('/api/v2/lab-runs', {
        method: 'POST',
        ...jsonBody({ session_id: learningSession.id, lesson_id: lessonId, target_id: targetId, prediction }),
      })
    },
    onSuccess: (run) => navigate(`/lab/${run.id}`),
  })
  if (lesson.isPending) return <LoadingBlock label="Открываем полевую карточку" />
  if (lesson.error || !lesson.data) return <ErrorNotice error={lesson.error ?? new Error('Урок не найден')} />
  const item = lesson.data
  return (
    <div className="page lesson-detail">
      <PageHeader kicker={`УРОК ${String(item.order).padStart(3, '0')} / ${item.skill_id}`} title={item.title} lead={item.summary} action={<StatusPill status={item.requires_target ? 'warning' : 'neutral'}>{item.requires_target ? 'нужна Docker-цель' : 'только Linux VM'}</StatusPill>} />
      <div className="lesson-brief">
        {item.simple_theory ? <SimpleTheoryCard theory={item.simple_theory} /> : null}
        {item.simple_theory ? (
          <details className="lesson-more">
            <summary>Подробнее: термин и разобранный пример</summary>
            <section className="paper-card paper-card--term"><Eyebrow>ТЕРМИН</Eyebrow><h2>{item.term.name}</h2><p>{item.term.definition}</p></section>
            <section className="paper-card"><Eyebrow>РАЗОБРАННЫЙ ПРИМЕР</Eyebrow><p className="large-copy">{item.worked_example}</p></section>
          </details>
        ) : (
          <>
            <section className="paper-card paper-card--term"><Eyebrow>ТЕРМИН</Eyebrow><h2>{item.term.name}</h2><p>{item.term.definition}</p></section>
            <section className="paper-card"><Eyebrow>РАЗОБРАННЫЙ ПРИМЕР</Eyebrow><p className="large-copy">{item.worked_example}</p></section>
          </>
        )}
        <section className="paper-card paper-card--prediction">
          <div><Eyebrow>ПРОГНОЗ ДО КОМАНДЫ</Eyebrow><h2>{item.prediction_question}</h2><p>Команда появится только после сохранения прогноза и создания lab run.</p></div>
          <textarea value={prediction} onChange={(event) => setPrediction(event.target.value)} rows={5} placeholder="Я ожидаю увидеть… Потому что…" disabled={principal.role === 'viewer'} />
        </section>
        {item.requires_target ? (
          <section className="target-selector">
            <div><Eyebrow>ПОДТВЕРЖДЁННАЯ ЦЕЛЬ</Eyebrow><h2>Выберите профиль, а не вводите произвольный IP.</h2></div>
            {compatibleTargets.length ? compatibleTargets.map((target) => (
              <button key={target.id} className={targetId === target.id ? 'target-option active' : 'target-option'} onClick={() => setTargetId(target.id)}>
                <span className="connection-light" /><strong>{target.display_name}</strong><small>{shortHash(target.fingerprint)}</small>
              </button>
            )) : <p className="notice notice--warning">Нет цели с подходящими tags. <Link to="/range">Откройте полигон</Link> и подтвердите существующий контейнер.</p>}
          </section>
        ) : null}
      </div>
      {start.error ? <ErrorNotice error={start.error} /> : null}
      <footer className="lesson-launch">
        <div><TerminalIcon /><span>Следующий экран откроет shell Linux VM. Никакого Windows PowerShell.</span></div>
        {principal.role === 'viewer' ? <StatusPill status="warning">viewer: теория без запуска</StatusPill> : (
          <button className="button button--primary" disabled={start.isPending || prediction.trim().length < 3 || (item.requires_target && !targetId)} onClick={() => start.mutate()}>
            {start.isPending ? 'Проверяем маршрут…' : 'Сохранить прогноз и открыть lab'} <ArrowIcon />
          </button>
        )}
      </footer>
    </div>
  )
}
