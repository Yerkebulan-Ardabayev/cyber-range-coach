import { useQuery } from '@tanstack/react-query'

import { api } from '../api'
import { EvidenceIcon } from '../icons'
import type { Curriculum, Evidence } from '../types'
import { EmptyState, ErrorNotice, Eyebrow, LoadingBlock, PageHeader, StatusPill, formatDate, shortHash } from '../components/Common'

const stages = ['introduced', 'guided', 'independent', 'transfer']
const stageLabels: Record<string, string> = {
  introduced: 'ознакомление',
  guided: 'с подсказкой',
  independent: 'самостоятельно',
  transfer: 'перенос навыка',
}

export function EvidencePage() {
  const evidence = useQuery({ queryKey: ['evidence'], queryFn: () => api<Evidence[]>('/api/v2/evidence') })
  const curriculum = useQuery({ queryKey: ['curriculum'], queryFn: () => api<Curriculum>('/api/v2/curriculum') })
  const grouped = new Map<string, Evidence[]>()
  for (const item of evidence.data ?? []) grouped.set(item.skill_id, [...(grouped.get(item.skill_id) ?? []), item])
  return (
    <div className="page">
      <PageHeader kicker="КАРТА ДОКАЗАТЕЛЬСТВ" title="Навык существует только там, где есть адрес доказательства." lead="AI не создаёт доказательства. Каждая карточка связана с лабораторным запуском и решением детерминированной проверки. Перенос навыка доступен только темам с Docker-целями." action={<StatusPill status="neutral">{evidence.data?.length ?? 0} записей</StatusPill>} />
      {evidence.isPending ? <LoadingBlock /> : null}
      {evidence.error ? <ErrorNotice error={evidence.error} /> : null}
      {!evidence.isPending && !evidence.data?.length ? <EmptyState index="E0" title="Карта пока пуста" text="Пройдите одну практику и запустите детерминированную проверку. Простое чтение теории не создаёт запись доказательства." /> : null}
      <div className="evidence-map">
        {[...grouped.entries()].map(([skill, items]) => {
          const current = items.sort((a, b) => stages.indexOf(b.stage) - stages.indexOf(a.stage))[0]
          const targetBacked = curriculum.data?.lessons.some((lesson) => lesson.skill_id === skill && lesson.requires_target) ?? false
          const visibleStages = targetBacked ? stages : stages.slice(0, 3)
          return <article key={skill}><header><span><EvidenceIcon /></span><div><Eyebrow>НАВЫК</Eyebrow><h2>{skill}</h2></div><span className={`evidence-stage evidence-stage--${current.stage}`}>{stageLabels[current.stage]}</span></header><div className="stage-track" style={{ gridTemplateColumns: `repeat(${visibleStages.length}, minmax(0, 1fr))` }}>{visibleStages.map((stage) => <div key={stage} className={stages.indexOf(stage) <= stages.indexOf(current.stage) ? 'reached' : ''}><i /><span>{stageLabels[stage]}</span></div>)}</div><ul>{items.map((item) => <li key={item.id}><div><strong>{item.fact}</strong><span>Запуск #{item.run_id} · {formatDate(item.created_at)}</span></div><code>{item.target_fingerprint ? shortHash(item.target_fingerprint) : 'контекст Linux VM'}</code></li>)}</ul></article>
        })}
      </div>
    </div>
  )
}
