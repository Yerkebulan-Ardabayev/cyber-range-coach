import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CommandPracticePanel } from './CommandPracticePanel'

const practicePlan = {
  items: [{
    technique_id: 'linux-find-executable-files',
    shell: 'bash',
    execution_status: 'range_ready',
    challenge: {
      id: 'linux-find-executable-files-recall',
      prompt: 'Найдите обычные исполняемые файлы в синтетическом дереве.', estimated_minutes: 5,
      context: { shell: 'bash', working_directory: '/home/student/training', named_inputs: { input_1: '.' }, constraints: ['Только синтетические данные.'] },
      answer_fields: [{ id: 'command', label: 'Команда в Bash', kind: 'command' }],
      hints: [
        { level: 1, label: 'Смысл и образ' },
        { level: 2, label: 'Название команды' },
        { level: 3, label: 'Скелет' },
        { level: 4, label: 'Полный пример' },
      ],
      observation_prompt: 'Что подтверждает результат?',
      version: 1,
    },
    due_at: '2026-08-26T00:00:00Z', overdue: true, retry_in_session: false,
    draft_answer: '', draft_observation_answer: '',
    draft_attempt_key: null, attempt_type: 'assessment', eligible_at: null, window_id: null, phase: 'recall',
  }],
  due_total: 1, new_total: 72, debt_remaining: 0, session_limit: 5,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CommandPracticePanel', () => {
  it('records a hint and keeps observation text separate from the command', async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> | null }> = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) as Record<string, unknown> : null
      requests.push({ path, body })
      if (path.includes('/command-practice/plan')) {
        return Promise.resolve(new Response(JSON.stringify(practicePlan), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.includes('/hints/1')) {
        return Promise.resolve(new Response(JSON.stringify({
          attempt_id: 1,
          revealed_help: [1],
          hints: [{ level: 1, label: 'Смысл и образ', text: 'Флажок x выделяет исполняемый файл.' }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.endsWith('/complete')) {
        return Promise.resolve(new Response(JSON.stringify({
          attempt_id: 1, technique_id: 'linux-find-executable-files', reason: 'correct_with_help',
          correct: true, independent: false, observation_correct: false,
          next_due_at: '2026-08-28T00:00:00Z', interval_days: null, retry_in_session: false, duplicate: false,
          verification_status: 'verified', detail: 'Команда совпала.', attempt_type: 'assessment', completed: false,
          observation_example: 'SYNTHETIC RESULT\nobserved_path=путь',
          observation_fields: [{ id: 'observed_path', label: 'Наблюдаемый путь', required: true }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.endsWith('/observation')) {
        return Promise.resolve(new Response(JSON.stringify({
          attempt_id: 1, technique_id: 'linux-find-executable-files', observation_correct: true,
          field_errors: {}, free_text_review_status: 'not_assessed', completed: true,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response(JSON.stringify({ attempt_id: 1, saved: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <CommandPracticePanel principal={{ role: 'owner', device_id: null, local_owner: true }} />
      </QueryClientProvider>,
    )

    await screen.findByText('Найдите обычные исполняемые файлы в синтетическом дереве.')
    fireEvent.click(screen.getByRole('button', { name: 'Открыть: Смысл и образ' }))
    await screen.findByText('Флажок x выделяет исполняемый файл.')
    fireEvent.change(screen.getByLabelText('Команда в Bash'), { target: { value: 'find . -type f -perm -111' } })
    fireEvent(window, new Event('pagehide'))
    await waitFor(() => expect(requests.some((request) => request.path.endsWith('/draft') && request.body?.answer === 'find . -type f -perm -111')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }))
    await screen.findByText('Верно с помощью. Самостоятельный интервал не вырос.')
    fireEvent.change(screen.getByLabelText('Наблюдаемый путь'), { target: { value: 'путь' } })
    fireEvent.change(screen.getByLabelText(/Свободное объяснение/), { target: { value: 'Вывод содержит путь.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить факты' }))
    await screen.findByText('Структурированный разбор подтверждён.')
    await waitFor(() => expect(requests.some((request) => request.path.endsWith('/complete'))).toBe(true))
    const completion = requests.find((request) => request.path.endsWith('/complete'))
    expect(completion?.body).toMatchObject({
      answer: 'find . -type f -perm -111',
      observation_answer: '',
      dont_remember: false,
    })
    fireEvent.click(screen.getByRole('button', { name: /Следующий приём/ }))
    await screen.findByRole('heading', { name: 'Разминка завершена' })
    expect(requests.filter((request) => request.path.includes('/command-practice/plan'))).toHaveLength(1)
  })

  it('returns an error later inside the finite session budget', async () => {
    const boundedPlan = { ...practicePlan, session_limit: 2 }
    let completions = 0
    const paths: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      paths.push(path)
      if (path.includes('/command-practice/plan')) {
        return Promise.resolve(new Response(JSON.stringify(boundedPlan), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.endsWith('/complete')) {
        completions += 1
        const correct = completions === 2
        return Promise.resolve(new Response(JSON.stringify({
          attempt_id: completions,
          technique_id: 'linux-find-executable-files',
          reason: correct ? 'correct' : 'wrong_tool',
          correct,
          independent: correct,
          observation_correct: false,
          next_due_at: '2026-08-28T00:00:00Z',
          interval_days: correct ? 1 : null,
          retry_in_session: !correct,
          duplicate: false,
          verification_status: 'verified', detail: correct ? 'Команда совпала.' : 'Другой инструмент.',
          attempt_type: 'assessment', completed: !correct,
          observation_example: correct ? 'SYNTHETIC RESULT\nobserved_path=путь' : null,
          observation_fields: correct ? [{ id: 'observed_path', label: 'Наблюдаемый путь', required: true }] : [],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.endsWith('/observation')) {
        return Promise.resolve(new Response(JSON.stringify({
          attempt_id: 2, technique_id: 'linux-find-executable-files', observation_correct: true,
          field_errors: {}, free_text_review_status: 'not_assessed', completed: true,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response(JSON.stringify({ attempt_id: 1, saved: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <CommandPracticePanel principal={{ role: 'owner', device_id: null, local_owner: true }} />
      </QueryClientProvider>,
    )

    await screen.findByText('Найдите обычные исполняемые файлы в синтетическом дереве.')
    fireEvent.change(screen.getByLabelText('Команда в Bash'), { target: { value: 'cat .' } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }))
    await screen.findByText('Выбран другой инструмент.')
    fireEvent.click(screen.getByRole('button', { name: /Следующий приём/ }))
    await screen.findByText('вернуть позже')
    fireEvent.change(screen.getByLabelText('Команда в Bash'), { target: { value: 'find . -type f -perm -111' } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }))
    await screen.findByText('Верно, без помощи.')
    fireEvent.change(screen.getByLabelText('Наблюдаемый путь'), { target: { value: 'путь' } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить факты' }))
    await screen.findByText('Структурированный разбор подтверждён.')
    fireEvent.click(screen.getByRole('button', { name: /Следующий приём/ }))
    await screen.findByRole('heading', { name: 'Разминка завершена' })
    expect(completions).toBe(2)
    expect(paths.filter((path) => path.includes('/command-practice/plan'))).toHaveLength(1)
  })

  it('submits on Enter, keeps Shift+Enter, and shows the correction after a wrong answer', async () => {
    let completions = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      if (path.includes('/command-practice/plan')) {
        return Promise.resolve(new Response(JSON.stringify(practicePlan), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.endsWith('/complete')) {
        completions += 1
        return Promise.resolve(new Response(JSON.stringify({
          attempt_id: 1, technique_id: 'linux-find-executable-files', reason: 'wrong_tool',
          correct: false, independent: false, observation_correct: false,
          next_due_at: '2026-09-25T00:00:00Z', interval_days: null, retry_in_session: true, duplicate: false,
          verification_status: 'verified', detail: 'Другой инструмент.', attempt_type: 'assessment', completed: true,
          observation_example: null, observation_fields: [],
          correction: { answer: 'find . -type f -perm -111', purpose: 'Найти исполняемые файлы.', typical_error: 'Забыть -type f.' },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response(JSON.stringify({ attempt_id: 1, saved: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <CommandPracticePanel principal={{ role: 'owner', device_id: null, local_owner: true }} />
      </QueryClientProvider>,
    )

    await screen.findByText('Найдите обычные исполняемые файлы в синтетическом дереве.')
    const field = screen.getByLabelText('Команда в Bash')
    fireEvent.change(field, { target: { value: 'ls' } })
    fireEvent.keyDown(field, { key: 'Enter', shiftKey: true })
    expect(completions).toBe(0)
    fireEvent.keyDown(field, { key: 'Enter' })
    await screen.findByText('Правильно так')
    expect(completions).toBe(1)
    expect(screen.getByText('find . -type f -perm -111')).toBeTruthy()
    expect(screen.getByText('Частая ошибка: Забыть -type f.')).toBeTruthy()
  })

  it('skips the output step when the example is still pending', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      if (path.includes('/command-practice/plan')) {
        return Promise.resolve(new Response(JSON.stringify(practicePlan), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.endsWith('/complete')) {
        return Promise.resolve(new Response(JSON.stringify({
          attempt_id: 1, technique_id: 'linux-find-executable-files', reason: 'correct',
          correct: true, independent: true, observation_correct: false,
          next_due_at: '2026-09-25T00:00:00Z', interval_days: 1, retry_in_session: false, duplicate: false,
          verification_status: 'verified', detail: 'Команда совпала.', attempt_type: 'assessment', completed: true,
          observation_example: null, observation_fields: [], correction: null,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response(JSON.stringify({ attempt_id: 1, saved: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <CommandPracticePanel principal={{ role: 'owner', device_id: null, local_owner: true }} />
      </QueryClientProvider>,
    )

    await screen.findByText('Найдите обычные исполняемые файлы в синтетическом дереве.')
    fireEvent.change(screen.getByLabelText('Команда в Bash'), { target: { value: 'find . -type f -perm -111' } })
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }))
    await screen.findByText(/Пример вывода появится после снимка со стенда/)
    expect(screen.queryByRole('button', { name: 'Проверить факты' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Следующий приём/ }))
    await screen.findByRole('heading', { name: 'Разминка завершена' })
  })
})
