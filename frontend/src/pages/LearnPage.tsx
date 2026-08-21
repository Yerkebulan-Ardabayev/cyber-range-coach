import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useMemo, useState } from 'react'

import { api } from '../api'
import { ArrowIcon, CheckIcon } from '../icons'
import type { Curriculum, Evidence, Principal } from '../types'
import { ErrorNotice, LoadingBlock, PageHeader, StatusPill } from '../components/Common'

const stageOrder = ['introduced', 'guided', 'independent', 'transfer']
const stageLabels: Record<string, string> = {
  introduced: 'ознакомление',
  guided: 'с подсказкой',
  independent: 'самостоятельно',
  transfer: 'перенос навыка',
}

export function LearnPage({ principal }: { principal: Principal }) {
  const [query, setQuery] = useState('')
  const [stage, setStage] = useState('all')
  const curriculum = useQuery({ queryKey: ['curriculum'], queryFn: () => api<Curriculum>('/api/v2/curriculum') })
  const evidence = useQuery({ queryKey: ['evidence'], queryFn: () => api<Evidence[]>('/api/v2/evidence') })
  const stageBySkill = useMemo(() => {
    const result = new Map<string, string>()
    for (const item of evidence.data ?? []) {
      const current = result.get(item.skill_id)
      if (!current || stageOrder.indexOf(item.stage) > stageOrder.indexOf(current)) result.set(item.skill_id, item.stage)
    }
    return result
  }, [evidence.data])
  const lessons = (curriculum.data?.lessons ?? []).filter((lesson) => {
    const needle = query.toLocaleLowerCase('ru')
    const matchesText = !needle || `${lesson.title} ${lesson.summary} ${lesson.term.name}`.toLocaleLowerCase('ru').includes(needle)
    const current = stageBySkill.get(lesson.skill_id) ?? 'introduced'
    return matchesText && (stage === 'all' || current === stage)
  })
  return (
    <div className="page">
      <PageHeader kicker="КАРТА ПОДГОТОВКИ" title="Каталог без искусственных замков." lead="Маршрут рекомендует следующий шаг, но вы можете открыть любую тему, сравнить контекст и вернуться к пробелу тогда, когда он стал понятен." action={<StatusPill status="neutral">{curriculum.data?.lessons.length ?? 0} уроков</StatusPill>} />
      <section className="catalog-toolbar">
        <label><span>Поиск по смыслу курса</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Linux, TCP, доказательство…" /></label>
        <div className="filter-chips" role="group" aria-label="Фильтр этапа">
          {['all', ...stageOrder].map((item) => <button key={item} className={stage === item ? 'active' : ''} onClick={() => setStage(item)}>{item === 'all' ? 'все' : stageLabels[item]}</button>)}
        </div>
      </section>
      {curriculum.isPending ? <LoadingBlock label="Читаем учебную программу" /> : null}
      {curriculum.error ? <ErrorNotice error={curriculum.error} /> : null}
      <div className="lesson-ledger">
        {lessons.map((lesson, index) => {
          const current = stageBySkill.get(lesson.skill_id) ?? 'introduced'
          return (
            <article key={lesson.id} className="lesson-entry">
              <div className="lesson-entry__number">{String(index + 1).padStart(2, '0')}</div>
              <div className="lesson-entry__main">
                <div className="lesson-entry__meta"><span>{lesson.estimated_minutes} МИН</span><span>{lesson.requires_target ? 'ЦЕЛЬ В DOCKER' : 'LINUX-МАШИНА'}</span><span>{lesson.skill_id}</span></div>
                <h2>{lesson.title}</h2><p>{lesson.summary}</p>
                <div className="lesson-entry__term"><strong>{lesson.term.name}</strong><span>{lesson.term.definition}</span></div>
              </div>
              <div className="lesson-entry__state"><span className={`evidence-stage evidence-stage--${current}`}>{stageLabels[current]}</span>{stageBySkill.has(lesson.skill_id) ? <CheckIcon /> : null}</div>
              <Link className={`button ${principal.role === 'viewer' ? 'button--quiet' : 'button--ink'}`} to={`/lesson/${lesson.id}`}>{principal.role === 'viewer' ? 'Изучить' : 'Открыть'} <ArrowIcon /></Link>
            </article>
          )
        })}
      </div>
    </div>
  )
}
