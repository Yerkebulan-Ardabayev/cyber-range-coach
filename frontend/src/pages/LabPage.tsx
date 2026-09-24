import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, jsonBody } from '../api'
import { ArrowIcon, CheckIcon, CloseIcon, EvidenceIcon, TerminalIcon } from '../icons'
import type { GradeResult, LabRun, Principal, RunLesson, TutorFeedback } from '../types'
import { ErrorNotice, Eyebrow, LoadingBlock, StatusPill } from '../components/Common'
import { InlineCode } from '../components/SimpleTheoryCard'
import { TerminalPanel } from '../components/TerminalPanel'

const runStatusLabels: Record<string, string> = { active: 'активна', completed: 'завершена', stopped: 'остановлена', abandoned: 'сброшена' }
const gradeStatusLabels: Record<string, string> = { passed: 'наблюдение подтверждено', failed: 'проверка не пройдена', needs_evidence: 'нужна чистая попытка' }
const evidenceStageLabels: Record<string, string> = { introduced: 'ознакомление', guided: 'с подсказкой', independent: 'самостоятельно', transfer: 'перенос навыка' }

function checkLabel(kind: string): string {
  if (kind === 'command') return 'Введена утверждённая команда'
  if (kind === 'attempt_boundary') return 'Команда была первой в чистой попытке'
  if (kind === 'responses') return 'Получены все ответы интерактивной команды'
  if (kind === 'required') return 'Найден требуемый факт'
  return 'Ошибочный признак отсутствует'
}

export function LabPage({ principal }: { principal: Principal }) {
  const { runId = '' } = useParams()
  const id = Number(runId)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [explanation, setExplanation] = useState('')
  const [correction, setCorrection] = useState('')
  const [limitation, setLimitation] = useState('')
  const [nextTest, setNextTest] = useState('')
  const [copied, setCopied] = useState(false)
  const run = useQuery({ queryKey: ['lab-run', id], queryFn: () => api<LabRun>(`/api/v2/lab-runs/${id}`), refetchInterval: 3000 })
  const lesson = useQuery({ queryKey: ['lab-run-lesson', id], queryFn: () => api<RunLesson>(`/api/v2/lab-runs/${id}/lesson`) })
  const grade = useMutation({
    mutationFn: () => api<GradeResult>(`/api/v2/lab-runs/${id}/grade`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lab-run', id] }),
  })
  const saveExplanation = useMutation({
    mutationFn: () => api<LabRun>(`/api/v2/lab-runs/${id}/explanation`, { method: 'POST', ...jsonBody({ text: explanation }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['lab-run', id] }),
  })
  const tutor = useMutation({
    mutationFn: () => api<TutorFeedback>('/api/v2/tutor-feedback', {
      method: 'POST',
      ...jsonBody({ run_id: id }),
    }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['lab-run', id] }) },
  })
  const finalize = useMutation({
    mutationFn: () => api<GradeResult>(`/api/v2/lab-runs/${id}/finalize`, { method: 'POST', ...jsonBody({ corrected_conclusion: correction, limitation, next_test: nextTest }) }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['lab-run', id] }); void queryClient.invalidateQueries({ queryKey: ['reviews'] }); void queryClient.invalidateQueries({ queryKey: ['evidence'] }) },
  })
  const stop = useMutation({
    mutationFn: () => api<LabRun>(`/api/v2/lab-runs/${id}/stop`, { method: 'POST' }),
    onSuccess: () => navigate('/learn'),
  })
  const reset = useMutation({
    mutationFn: () => api<LabRun>(`/api/v2/lab-runs/${id}/reset`, { method: 'POST', ...jsonBody({ prediction: run.data?.prediction ?? 'Повторяю проверяемую попытку.' }) }),
    onSuccess: (replacement) => { void queryClient.invalidateQueries({ queryKey: ['lab-runs'] }); void navigate(`/lab/${replacement.id}`) },
  })
  useEffect(() => {
    if (run.data?.explanation && !explanation) setExplanation(run.data.explanation)
    if (run.data?.correction && !correction) setCorrection(run.data.correction)
  }, [run.data?.explanation, run.data?.correction, explanation, correction])
  if (run.isPending || lesson.isPending) return <LoadingBlock label="Поднимаем lab workspace" />
  if (run.error || lesson.error || !run.data || !lesson.data) return <ErrorNotice error={run.error ?? lesson.error ?? new Error('Лабораторный запуск не найден')} />
  const currentGrade = finalize.data ?? grade.data ?? (run.data.grader_status ? run.data.grader_report as unknown as GradeResult : null)
  return (
    <div className="lab-workspace">
      <header className="lab-topline">
        <div><Eyebrow>ЛАБОРАТОРИЯ #{run.data.id} / {lesson.data.skill_id}</Eyebrow><h1>{lesson.data.title}</h1></div>
        <div className="lab-topline__actions"><StatusPill status={run.data.status === 'active' ? 'ok' : 'warning'}>{runStatusLabels[run.data.status] ?? run.data.status}</StatusPill>{principal.role !== 'viewer' ? <button className="icon-button" title="Остановить лабораторию" onClick={() => stop.mutate()}><CloseIcon /></button> : null}</div>
      </header>
      <div className="lab-grid">
        <aside className="lab-guide">
          <section><Eyebrow>01 / ОПОРА</Eyebrow><h2>{lesson.data.term.name}</h2>{lesson.data.simple_theory ? <p><InlineCode text={lesson.data.simple_theory.analogy} /></p> : null}<p>{lesson.data.term.definition}</p></section>
          <section><Eyebrow>02 / ВАШ ПРОГНОЗ</Eyebrow><blockquote>{run.data.prediction}</blockquote></section>
          <section><Eyebrow>03 / КОМАНДА</Eyebrow><div className="command-slip"><code>{lesson.data.rendered_command}</code><button onClick={() => { void navigator.clipboard.writeText(lesson.data.rendered_command); setCopied(true); window.setTimeout(() => setCopied(false), 1200) }}>{copied ? 'скопировано' : 'копировать'}</button></div><ol>{lesson.data.command_explanation.map((line) => <li key={line}>{line}</li>)}</ol></section>
          <Link className="quiet-link" to={`/lesson/${lesson.data.id}`}>Вернуться к примеру</Link>
        </aside>
        <section className="terminal-deck">
          <div className="terminal-deck__head"><div><TerminalIcon /><span>linux-vm / student</span></div><span>UTF-8 · xterm-256color</span></div>
          <TerminalPanel runId={run.data.id} role={principal.role} transcript={run.data.transcript} />
          <div className="terminal-deck__foot"><span>Команды выполняются в Linux VM</span><span>Известные Docker sockets: доступа нет</span><span>Non-interactive sudo: доступа нет</span></div>
        </section>
        <aside className="lab-evidence">
          <section className="evidence-check">
            <div className="evidence-check__head"><EvidenceIcon /><div><Eyebrow>ДЕТЕРМИНИРОВАННАЯ ПРОВЕРКА</Eyebrow><h2>Проверить наблюдение</h2></div></div>
            <p>Для зачёта утверждённая команда должна быть первой командой текущего запуска. Это отделяет её вывод от предыдущих процессов. Если вы уже вводили другую команду, начните новую попытку. Для Docker-целей результат независимо повторяет ограниченный range-runner. AI не участвует в решении.</p>
            {principal.role !== 'viewer' ? <button className="button button--primary" onClick={() => grade.mutate()} disabled={grade.isPending || run.data.status !== 'active'}>{grade.isPending ? 'Сверяем…' : 'Проверить наблюдение'} <ArrowIcon /></button> : null}
            {principal.role !== 'viewer' ? <button className="button button--quiet" onClick={() => reset.mutate()} disabled={reset.isPending || run.data.status !== 'active'}>{reset.isPending ? 'Сбрасываем…' : 'Начать чистую попытку'}</button> : null}
            {grade.error || reset.error ? <ErrorNotice error={grade.error ?? reset.error} /> : null}
            {currentGrade ? (
              <div className={`grade-result grade-result--${currentGrade.status}`}>
                <strong>{gradeStatusLabels[currentGrade.status] ?? currentGrade.status}</strong>
                <ul>{currentGrade.checks?.map((check, index) => <li key={`${check.pattern}-${index}`} className={check.passed ? 'pass' : 'fail'}>{check.passed ? <CheckIcon /> : <CloseIcon />}<span>{checkLabel(check.kind)}</span></li>)}</ul>
                {currentGrade.evidence_stage ? <StatusPill status="ok">этап: {evidenceStageLabels[currentGrade.evidence_stage] ?? currentGrade.evidence_stage}</StatusPill> : currentGrade.status === 'passed' ? <StatusPill status="warning">нужны объяснение, наставник и разбор</StatusPill> : null}
              </div>
            ) : null}
          </section>
          <section className="explanation-box">
            <Eyebrow>ОБЪЯСНЕНИЕ СВОИМИ СЛОВАМИ</Eyebrow>
            <h2>{lesson.data.explanation_prompt}</h2>
            <textarea value={explanation} onChange={(event) => setExplanation(event.target.value)} rows={7} placeholder="Факт… Ограничение… Следующий тест…" disabled={principal.role === 'viewer'} />
            {principal.role !== 'viewer' ? <div className="button-row"><button className="button button--ink" disabled={currentGrade?.status !== 'passed' || explanation.trim().length < 3 || saveExplanation.isPending} onClick={() => saveExplanation.mutate()}>Сохранить объяснение</button><button className="button button--quiet" disabled={!run.data.explanation || tutor.isPending} onClick={() => tutor.mutate()}>Спросить наставника</button></div> : null}
            {saveExplanation.error || tutor.error ? <ErrorNotice error={saveExplanation.error ?? tutor.error} /> : null}
            {tutor.data || run.data.tutor_question ? <div className="mentor-note"><span>НАСТАВНИК / {tutor.data?.provider ?? 'local_method'}</span><p>{tutor.data?.explanation ?? run.data.tutor_explanation}</p><strong>{tutor.data?.question ?? run.data.tutor_question}</strong>{tutor.data?.caution ? <small>{tutor.data.caution}</small> : null}</div> : null}
            {run.data.tutor_feedback_at || tutor.data ? <><label>Исправленный вывод<textarea value={correction} onChange={(event) => setCorrection(event.target.value)} rows={4} placeholder="Переформулируйте вывод после вопроса наставника." /></label><label>Ограничение доказательства<textarea value={limitation} onChange={(event) => setLimitation(event.target.value)} rows={3} placeholder="Что эта проверка пока не доказывает?" /></label><label>Следующая проверка<textarea value={nextTest} onChange={(event) => setNextTest(event.target.value)} rows={3} placeholder="Какой конкретный тест уменьшит неопределённость?" /></label><button className="button button--primary" disabled={correction.trim().length < 12 || limitation.trim().length < 8 || nextTest.trim().length < 8 || correction.trim().toLocaleLowerCase() === explanation.trim().toLocaleLowerCase() || finalize.isPending || run.data.status !== 'active'} onClick={() => finalize.mutate()}>{finalize.isPending ? 'Фиксируем…' : 'Завершить debrief и записать evidence'} <ArrowIcon /></button></> : null}
            {finalize.error ? <ErrorNotice error={finalize.error} /> : null}
          </section>
        </aside>
      </div>
    </div>
  )
}
