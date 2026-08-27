import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MissionPanel } from './MissionPanel'

const missionPlan = {
  items: [{
    mission_id: 'magpie-missing-clue',
    title: 'Сорока: пропавшая улика',
    story: 'Найдите полезный след.',
    allowed_environment: 'Учебный Linux.',
    prepared_data_description: 'Только синтетические данные.',
    required_actions: ['Найдите файл.', 'Объясните связь.'],
    final_artifact_prompt: 'Укажите строку.',
    explanation_prompt: 'Объясните маркер.',
    technique_ids: ['linux-grep-text-pattern'],
    techniques: [{ id: 'linux-grep-text-pattern', family: 'grep', shell: 'bash', purpose: 'Оставить строку с меткой.', significant_flags: [], typical_error: 'Перепутать шаблон.', mnemonic_image: 'сито', source_refs: [], version: 1 }],
    variant_rule: 'При повторе меняется маркер.', requires_free_text: true, version: 1,
    variant_id: 'magpie-aurora', scenario: 'Дело Аврора.',
    prepared_data: [{ path: 'casefiles/trace.txt', kind: 'text', content: 'trace: marker=ORBIT-41' }],
    draft_attempt_key: null, draft_artifact: '', draft_explanation: '',
  }],
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('MissionPanel', () => {
  it('shows source data and submits separately saved artifact and explanation', async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> | null }> = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) as Record<string, unknown> : null
      requests.push({ path, body })
      if (path.endsWith('/missions/plan')) {
        return Promise.resolve(new Response(JSON.stringify(missionPlan), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      if (path.endsWith('/complete')) {
        return Promise.resolve(new Response(JSON.stringify({
          run_id: 1, mission_id: 'magpie-missing-clue', variant_id: 'magpie-aurora', status: 'solved',
          reason: 'Финальный артефакт и объяснение подтверждены.', explanation_accepted: true,
          debrief: 'Разбор открыт после ответа.', evidence_kind: 'mission_final_artifact', duplicate: false,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return Promise.resolve(new Response(JSON.stringify({ run_id: 1, saved: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MissionPanel principal={{ role: 'owner', device_id: null, local_owner: true }} />
      </QueryClientProvider>,
    )

    await screen.findByRole('heading', { name: 'Сорока: пропавшая улика' })
    expect(screen.getByText('casefiles/trace.txt')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Конечный артефакт'), { target: { value: 'trace: marker=ORBIT-41' } })
    fireEvent.change(screen.getByLabelText('Объяснение'), { target: { value: 'Маркер связан с сектором.' } })
    fireEvent(window, new Event('pagehide'))
    await waitFor(() => expect(requests.some((request) => request.path.endsWith('/draft') && request.body?.artifact === 'trace: marker=ORBIT-41')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }))
    await screen.findByText('Миссия решена: артефакт и объяснение подтверждены.')
    const completion = requests.find((request) => request.path.endsWith('/complete'))
    expect(completion?.body).toMatchObject({
      artifact: 'trace: marker=ORBIT-41',
      explanation: 'Маркер связан с сектором.',
    })
    expect(screen.getByText('Разбор открыт после ответа.')).toBeInTheDocument()
  })
})
