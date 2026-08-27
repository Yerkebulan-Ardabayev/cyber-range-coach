import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { api, jsonBody } from '../api'
import type { CommandPracticePlan, CommandPracticeResult, CommandTechnique, Principal } from '../types'
import { ArrowIcon, RepeatIcon } from '../icons'
import { ErrorNotice, Eyebrow, LoadingBlock, StatusPill, formatDate } from './Common'

function newAttemptKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return `practice-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const reasonText: Record<CommandPracticeResult['reason'], string> = {
  correct: 'Верно, без помощи.',
  correct_with_help: 'Верно с помощью. Самостоятельный интервал не вырос.',
  wrong_tool: 'Выбран другой инструмент.',
  wrong_flag: 'Проверьте значимый флаг.',
  wrong_shell: 'Ответ относится к другой оболочке.',
  insufficient_data: 'Недостаточно данных для зачёта.',
}

export function CommandPracticePanel({ principal }: { principal: Principal }) {
  const plan = useQuery({
    queryKey: ['command-practice-plan'],
    queryFn: () => api<CommandPracticePlan>('/api/v2/command-practice/plan?limit=5&available_minutes=25'),
  })
  const [sessionItems, setSessionItems] = useState<CommandPracticePlan['items']>([])
  const [sessionComplete, setSessionComplete] = useState(false)
  const [additionalDebt, setAdditionalDebt] = useState(0)
  const [index, setIndex] = useState(0)
  const [attemptKey, setAttemptKey] = useState(newAttemptKey)
  const [answer, setAnswer] = useState('')
  const [observation, setObservation] = useState('')
  const [revealed, setRevealed] = useState<number[]>([])
  const [revealedHints, setRevealedHints] = useState<Array<{ level: 1 | 2 | 3 | 4; label: string; text: string }>>([])
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [catalogTechnique, setCatalogTechnique] = useState<CommandTechnique | null>(null)
  const [result, setResult] = useState<CommandPracticeResult | null>(null)
  const initializedPlan = useRef(false)
  const initializedIndex = useRef<number | null>(null)
  const leaveDraft = useRef<{
    attemptKey: string
    techniqueId: string
    shell: 'bash'
    timezone: string
    answer: string
    observationAnswer: string
    canSave: boolean
  } | null>(null)
  const item = sessionItems[index]
  const timezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    [],
  )

  useEffect(() => {
    if (!plan.data || initializedPlan.current) return
    initializedPlan.current = true
    setSessionItems(plan.data.items)
  }, [plan.data])

  useLayoutEffect(() => {
    if (!item || initializedIndex.current === index) return
    initializedIndex.current = index
    setAttemptKey(newAttemptKey())
    setAnswer(item.draft_answer)
    setObservation(item.draft_observation_answer)
    setRevealed([])
    setRevealedHints([])
    setCatalogOpen(false)
    setCatalogTechnique(null)
    setResult(null)
  }, [index, item])

  const basePayload = item ? {
    technique_id: item.technique_id,
    shell: item.shell,
    timezone,
  } : null
  leaveDraft.current = item ? {
    attemptKey,
    techniqueId: item.technique_id,
    shell: item.shell,
    timezone,
    answer,
    observationAnswer: observation,
    canSave: principal.role !== 'viewer' && !result,
  } : null

  useEffect(() => {
    const saveOnLeave = () => {
      const draft = leaveDraft.current
      if (!draft?.canSave) return
      void api(`/api/v2/command-practice/attempts/${draft.attemptKey}/draft`, {
        method: 'PUT',
        keepalive: true,
        ...jsonBody({
          technique_id: draft.techniqueId,
          shell: draft.shell,
          timezone: draft.timezone,
          answer: draft.answer,
          observation_answer: draft.observationAnswer,
        }),
      })
    }
    window.addEventListener('pagehide', saveOnLeave)
    return () => window.removeEventListener('pagehide', saveOnLeave)
  }, [])

  const saveDraft = useMutation({
    mutationFn: (value: { answer: string; observationAnswer: string }) => api<{ saved: boolean }>(`/api/v2/command-practice/attempts/${attemptKey}/draft`, {
      method: 'PUT',
      ...jsonBody({ ...basePayload, answer: value.answer, observation_answer: value.observationAnswer }),
    }),
  })

  useEffect(() => {
    if (!item || principal.role === 'viewer' || result) return
    const timer = window.setTimeout(() => saveDraft.mutate({ answer, observationAnswer: observation }), 600)
    return () => window.clearTimeout(timer)
  }, [answer, observation, item, principal.role, result])

  const revealHint = useMutation({
    mutationFn: async (targetLevel: number) => {
      if (!basePayload) return { levels: [] as number[], hints: [] as Array<{ level: 1 | 2 | 3 | 4; label: string; text: string }> }
      let levels = [...revealed]
      let hints = [...revealedHints]
      for (let level = levels.length + 1; level <= targetLevel; level += 1) {
        const response = await api<{ revealed_help: number[]; hints: Array<{ level: 1 | 2 | 3 | 4; label: string; text: string }> }>(
          `/api/v2/command-practice/attempts/${attemptKey}/hints/${level}`,
          { method: 'POST', ...jsonBody(basePayload) },
        )
        levels = response.revealed_help
        hints = response.hints
      }
      return { levels, hints }
    },
    onSuccess: (value) => {
      setRevealed(value.levels)
      setRevealedHints(value.hints)
    },
  })

  const complete = useMutation({
    mutationFn: (dontRemember: boolean) => api<CommandPracticeResult>(
      `/api/v2/command-practice/attempts/${attemptKey}/complete`,
      {
        method: 'POST',
        ...jsonBody({
          ...basePayload,
          answer,
          observation_answer: observation,
          dont_remember: dontRemember,
        }),
      },
    ),
    onSuccess: (value) => {
      setResult(value)
    },
  })

  async function openCatalog() {
    if (!item || principal.role === 'viewer') return
    const value = await revealHint.mutateAsync(4)
    setRevealed(value.levels)
    setRevealedHints(value.hints)
    const response = await api<{ technique: CommandTechnique }>(`/api/v2/command-techniques/${item.technique_id}?attempt_key=${encodeURIComponent(attemptKey)}`)
    setCatalogTechnique(response.technique)
    setCatalogOpen(true)
  }

  function nextItem() {
    if (!item) return
    const nextItems = [...sessionItems]
    const sessionLimit = plan.data?.session_limit ?? nextItems.length
    if (result?.retry_in_session && index + 1 < sessionLimit) {
      const retryItem = {
        ...item,
        retry_in_session: true,
        overdue: true,
        draft_answer: '',
        draft_observation_answer: '',
      }
      if (nextItems.length < sessionLimit) {
        nextItems.push(retryItem)
      } else {
        const displaced = nextItems[nextItems.length - 1]
        if (displaced.due_at || displaced.retry_in_session) setAdditionalDebt((value) => value + 1)
        nextItems[nextItems.length - 1] = retryItem
      }
    } else if (result?.retry_in_session) {
      setAdditionalDebt((value) => value + 1)
    }
    setSessionItems(nextItems)
    if (index + 1 < nextItems.length) {
      initializedIndex.current = null
      setIndex(index + 1)
      return
    }
    setSessionComplete(true)
  }

  if (plan.isPending) return <LoadingBlock />
  if (plan.error) return <ErrorNotice error={plan.error} />
  if (!initializedPlan.current) return <LoadingBlock />
  const visibleDebt = (plan.data?.debt_remaining ?? 0) + additionalDebt
  if (sessionComplete) {
    return (
      <section className="command-practice command-practice--empty" aria-live="polite">
        <RepeatIcon />
        <div>
          <Eyebrow>ПОВТОРЕНИЕ КОМАНД</Eyebrow>
          <h2>Разминка завершена</h2>
          <p>Лимит этой сессии исчерпан. Осталось в долге: {visibleDebt}.</p>
        </div>
      </section>
    )
  }
  if (!item) {
    return (
      <section className="command-practice command-practice--empty">
        <RepeatIcon />
        <div><Eyebrow>ПОВТОРЕНИЕ КОМАНД</Eyebrow><h2>Очередь на эту сессию пуста</h2><p>Новые приёмы появятся после обновления каталога, а повторения вернутся в назначенный срок.</p></div>
      </section>
    )
  }

  const nextHint = item.challenge.hints[revealed.length]
  return (
    <section className="command-practice" aria-labelledby="command-practice-title">
      <header className="command-practice__head">
        <div>
          <Eyebrow>КОМАНДНАЯ РАЗМИНКА / {index + 1} ИЗ {sessionItems.length}</Eyebrow>
          <h2 id="command-practice-title">Вспомните приём до подсказки</h2>
        </div>
        <div className="command-practice__status">
          <StatusPill status={item.overdue ? 'warning' : 'ok'}>{item.retry_in_session ? 'вернуть позже' : item.overdue ? 'просрочено' : 'новый приём'}</StatusPill>
          <small>долг после сессии: {visibleDebt}</small>
        </div>
      </header>

      <div className="command-practice__grid">
        <div className="command-practice__task">
          <p className="large-copy">{item.challenge.prompt}</p>
          <label>
            Команда в Bash
            <textarea
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              onBlur={() => principal.role !== 'viewer' && !result && saveDraft.mutate({ answer, observationAnswer: observation })}
              disabled={principal.role === 'viewer' || Boolean(result)}
              placeholder="Введите команду. Coach не исполняет этот ответ."
              rows={3}
            />
          </label>
          <label>
            Отдельно: что должен означать результат?
            <span className="field-help">{item.challenge.observation_prompt}</span>
            <textarea
              value={observation}
              onChange={(event) => setObservation(event.target.value)}
              onBlur={() => principal.role !== 'viewer' && !result && saveDraft.mutate({ answer, observationAnswer: observation })}
              disabled={principal.role === 'viewer' || Boolean(result)}
              placeholder="Опишите наблюдение, не повторяя синтаксис команды."
              rows={3}
            />
          </label>

          {result ? (
            <div className={`command-practice__result ${result.correct ? 'is-correct' : 'is-error'}`} role="status">
              <strong>{reasonText[result.reason]}</strong>
              <p>{result.observation_correct ? 'Объяснение результата принято отдельно.' : 'Объяснение результата пока не подтверждено.'}</p>
              <small>{result.next_due_at ? `Следующий срок: ${formatDate(result.next_due_at)}.` : 'Следующий срок ещё не назначен.'}</small>
              <button className="button button--primary" onClick={() => void nextItem()}>Следующий приём <ArrowIcon /></button>
            </div>
          ) : (
            <div className="button-row">
              <button className="button button--primary" onClick={() => complete.mutate(false)} disabled={principal.role === 'viewer' || complete.isPending || !answer}>Проверить на сервере</button>
              <button className="button" onClick={() => complete.mutate(true)} disabled={principal.role === 'viewer' || complete.isPending}>Не помню</button>
            </div>
          )}
          {complete.error || saveDraft.error ? <ErrorNotice error={complete.error ?? saveDraft.error} /> : null}
        </div>

        <aside className="command-practice__help" aria-label="Подсказки и карточка приёма">
          <Eyebrow>ПОМОЩЬ ЗАПИСЫВАЕТСЯ</Eyebrow>
          <p>Каждая открытая ступень сохраняется на сервере. Ответ после подсказки не продвигает самостоятельное воспроизведение.</p>
          <div className="hint-stack">
            {revealedHints.map((hint) => (
              <article key={hint.level}><span>0{hint.level}</span><div><strong>{hint.label}</strong><p>{hint.text}</p></div></article>
            ))}
          </div>
          {nextHint && !result ? (
            <button className="button" onClick={() => revealHint.mutate(nextHint.level)} disabled={principal.role === 'viewer' || revealHint.isPending}>
              Открыть: {nextHint.label}
            </button>
          ) : null}
          <button className="button button--ghost" onClick={() => void openCatalog()} disabled={principal.role === 'viewer' || revealHint.isPending}>Открыть карточку приёма</button>
          {catalogOpen && catalogTechnique ? (
            <div className="technique-card">
              <strong>{catalogTechnique.family}</strong>
              <p>{catalogTechnique.purpose}</p>
              <dl>
                <dt>Значимые флаги</dt><dd>{catalogTechnique.significant_flags.join(', ') || 'нет'}</dd>
                <dt>Типичная ошибка</dt><dd>{catalogTechnique.typical_error}</dd>
                <dt>Образ</dt><dd>{catalogTechnique.mnemonic_image}</dd>
                <dt>Источник</dt><dd>{catalogTechnique.source_refs.map((ref) => `${ref.source}, ${ref.address}`).join('; ')}</dd>
              </dl>
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  )
}
