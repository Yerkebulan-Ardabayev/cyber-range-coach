import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, jsonBody } from '../api'
import type { MissionPlan, MissionResult, Principal } from '../types'
import { ArrowIcon, RepeatIcon } from '../icons'
import { ErrorNotice, Eyebrow, LoadingBlock, StatusPill } from './Common'

function newAttemptKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return `mission-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const statusText: Record<MissionResult['status'], string> = {
  solved: 'Миссия решена: артефакт и объяснение подтверждены.',
  wrong_artifact: 'Артефакт не подтверждён подготовленными данными.',
  unexplained: 'Артефакт найден, но объяснение пока не принято.',
  needs_review: 'Вариант не подтверждён автоматически и ждёт ручной проверки.',
}

function readableSnapshot(value: string): string {
  return value.replaceAll('\\n', '\n')
}

export function MissionPanel({ principal }: { principal: Principal }) {
  const queryClient = useQueryClient()
  const plan = useQuery({
    queryKey: ['mission-plan'],
    queryFn: () => api<MissionPlan>('/api/v2/missions/plan'),
  })
  const [missionId, setMissionId] = useState<string | null>(null)
  const [attemptKey, setAttemptKey] = useState(newAttemptKey)
  const [artifact, setArtifact] = useState('')
  const [explanation, setExplanation] = useState('')
  const [dirty, setDirty] = useState(false)
  const [result, setResult] = useState<MissionResult | null>(null)
  const leaveDraft = useRef<{
    attemptKey: string
    missionId: string
    variantId: string
    artifact: string
    explanation: string
    canSave: boolean
  } | null>(null)
  const items = plan.data?.items ?? []
  const item = items.find((value) => value.mission_id === missionId) ?? items[0]
  const selectedMissionId = item?.mission_id ?? null

  useEffect(() => {
    if (missionId || !items[0]) return
    setMissionId(items[0].mission_id)
  }, [items, missionId])

  useLayoutEffect(() => {
    if (!item) return
    setAttemptKey(item.draft_attempt_key ?? newAttemptKey())
    setArtifact(item.draft_artifact)
    setExplanation(item.draft_explanation)
    setDirty(false)
    setResult(null)
  }, [item])

  const payload = item ? {
    mission_id: item.mission_id,
    variant_id: item.variant_id,
  } : null
  leaveDraft.current = item ? {
    attemptKey,
    missionId: item.mission_id,
    variantId: item.variant_id,
    artifact,
    explanation,
    canSave: dirty && principal.role !== 'viewer' && !result,
  } : null

  const saveDraft = useMutation({
    mutationFn: (value: { artifact: string; explanation: string }) => api<{ saved: boolean }>(
      `/api/v2/missions/attempts/${attemptKey}/draft`,
      { method: 'PUT', ...jsonBody({ ...payload, ...value }) },
    ),
  })

  useEffect(() => {
    if (!item || principal.role === 'viewer' || result || !dirty) return
    const timer = window.setTimeout(() => {
      saveDraft.mutate({ artifact, explanation })
    }, 600)
    return () => window.clearTimeout(timer)
  }, [artifact, dirty, explanation, item, principal.role, result, saveDraft])

  useEffect(() => {
    const saveOnLeave = () => {
      const draft = leaveDraft.current
      if (!draft?.canSave) return
      void api(`/api/v2/missions/attempts/${draft.attemptKey}/draft`, {
        method: 'PUT',
        keepalive: true,
        ...jsonBody({
          mission_id: draft.missionId,
          variant_id: draft.variantId,
          artifact: draft.artifact,
          explanation: draft.explanation,
        }),
      })
    }
    window.addEventListener('pagehide', saveOnLeave)
    return () => window.removeEventListener('pagehide', saveOnLeave)
  }, [])

  const complete = useMutation({
    mutationFn: () => api<MissionResult>(`/api/v2/missions/attempts/${attemptKey}/complete`, {
      method: 'POST',
      ...jsonBody({ ...payload, artifact, explanation }),
    }),
    onSuccess: (value) => {
      setResult(value)
      setDirty(false)
    },
  })

  const sourceTitle = useMemo(() => {
    if (!item) return ''
    return `Исходные данные: ${item.title}`
  }, [item])

  function selectMission(nextMissionId: string) {
    if (nextMissionId === selectedMissionId) return
    setMissionId(nextMissionId)
  }

  function refreshMission() {
    setResult(null)
    setDirty(false)
    void queryClient.invalidateQueries({ queryKey: ['mission-plan'] })
  }

  if (plan.isPending) return <LoadingBlock />
  if (plan.error) return <ErrorNotice error={plan.error} />
  if (!item) {
    return (
      <section className="mission-panel mission-panel--empty">
        <RepeatIcon />
        <div><Eyebrow>МИССИИ-РАССЛЕДОВАНИЯ</Eyebrow><h2>Миссии пока не опубликованы</h2><p>Когда каталог появится, здесь будут синтетические сценарии и проверка финального артефакта.</p></div>
      </section>
    )
  }

  return (
    <section className="mission-panel" aria-labelledby="mission-panel-title">
      <header className="mission-panel__head">
        <div>
          <Eyebrow>МИССИИ-РАССЛЕДОВАНИЯ</Eyebrow>
          <h2 id="mission-panel-title">Примените приём в новом контексте</h2>
          <p>Coach проверяет только заявленный финальный артефакт и объяснение. Последовательность команд не записывается и не оценивается в этой версии.</p>
        </div>
        <StatusPill status="warning">синтетические данные</StatusPill>
      </header>

      <div className="mission-panel__tabs" role="tablist" aria-label="Сценарии миссий">
        {items.map((candidate) => (
          <button
            key={candidate.mission_id}
            className={candidate.mission_id === selectedMissionId ? 'active' : ''}
            role="tab"
            aria-selected={candidate.mission_id === selectedMissionId}
            onClick={() => selectMission(candidate.mission_id)}
          >
            {candidate.title}
          </button>
        ))}
      </div>

      <div className="mission-panel__grid">
        <div className="mission-panel__task">
          <Eyebrow>ВАРИАНТ ДАННЫХ {item.variant_id}</Eyebrow>
          <h3>{item.title}</h3>
          <p className="large-copy">{item.story}</p>
          <p className="mission-panel__scenario">{readableSnapshot(item.scenario)}</p>
          <div className="mission-panel__environment"><strong>Разрешённая среда:</strong> {item.allowed_environment}</div>
          <h4 id="mission-source-title">{sourceTitle}</h4>
          <p className="field-help">{item.prepared_data_description}</p>
          <div className="mission-snapshot" aria-labelledby="mission-source-title">
            {item.prepared_data.map((entry) => (
              <article key={entry.path}>
                <code>{entry.path}</code><span>{entry.kind}</span>
                {entry.content ? <pre>{readableSnapshot(entry.content)}</pre> : null}
              </article>
            ))}
          </div>
          <h4>Что сделать</h4>
          <ol className="mission-actions">{item.required_actions.map((action) => <li key={action}>{action}</li>)}</ol>
          <label>
            Конечный артефакт
            <span className="field-help">{item.final_artifact_prompt}</span>
            <textarea
              aria-label="Конечный артефакт"
              value={artifact}
              onChange={(event) => { setArtifact(event.target.value); setDirty(true) }}
              onBlur={() => dirty && principal.role !== 'viewer' && !result && saveDraft.mutate({ artifact, explanation })}
              disabled={principal.role === 'viewer' || Boolean(result)}
              placeholder="Введите найденную строку, путь или исправленную команду. Coach не исполняет этот текст."
              rows={3}
            />
          </label>
          <label>
            Объяснение
            <span className="field-help">{item.explanation_prompt}</span>
            <textarea
              aria-label="Объяснение"
              value={explanation}
              onChange={(event) => { setExplanation(event.target.value); setDirty(true) }}
              onBlur={() => dirty && principal.role !== 'viewer' && !result && saveDraft.mutate({ artifact, explanation })}
              disabled={principal.role === 'viewer' || Boolean(result)}
              placeholder="Опишите связь артефакта с задачей своими словами."
              rows={3}
            />
          </label>
          {result ? (
            <div className={`mission-result mission-result--${result.status}`} role="status">
              <strong>{statusText[result.status]}</strong>
              <p>{result.reason}</p>
              <p><strong>Разбор после ответа.</strong> {result.debrief}</p>
              <small>Вид доказательства: {result.evidence_kind}.</small>
              <button className="button button--primary" onClick={refreshMission}>Следующий вариант <ArrowIcon /></button>
            </div>
          ) : (
            <div className="button-row">
              <button className="button button--primary" onClick={() => complete.mutate()} disabled={principal.role === 'viewer' || complete.isPending || !artifact}>Проверить на сервере</button>
            </div>
          )}
          {complete.error || saveDraft.error ? <ErrorNotice error={complete.error ?? saveDraft.error} /> : null}
        </div>

        <aside className="mission-panel__catalog" aria-label="Каталог приёмов миссии">
          <Eyebrow>ПРИЁМЫ РЯДОМ С ЗАДАНИЕМ</Eyebrow>
          <p>Карточки доступны без отдельного перехода. Их чтение не является доказательством самостоятельного ответа.</p>
          <div className="mission-techniques">
            {item.techniques.map((technique) => (
              <article key={technique.id}>
                <strong>{technique.family}</strong>
                <p>{technique.purpose}</p>
                <small>Типичная ошибка: {technique.typical_error}</small>
              </article>
            ))}
          </div>
          <p className="field-help">{item.variant_rule}</p>
        </aside>
      </div>
    </section>
  )
}
